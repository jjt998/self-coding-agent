from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import unified_diff
from pathlib import Path
import re
import subprocess
from typing import Any


FULL_READ_FILE_MAX_LINES = 200
FULL_READ_FILE_MAX_CHARS = 8000
READ_FILE_RANGE_MAX_LINES = 40
STRUCTURE_SUMMARY_MAX_ITEMS = 200


def _is_text_file(path: Path) -> bool:
    """用最小规则判断文件是否适合按 UTF-8 文本读取。"""
    if not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _line_count(content: str) -> int:
    """按工具反馈口径统计文本行数，空文件为 0 行。"""
    return len(content.splitlines())


def _read_coverage(start_line: int, end_line: int) -> str:
    """把闭区间行号转成稳定的覆盖范围字符串。"""
    return f"{start_line}-{end_line}"


def _truncate_text(value: str, limit: int = 4000) -> str:
    """截断进入工具输出的长文本，避免大文件撑爆 trace。"""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _build_structure_summary(path: str, content: str) -> list[dict[str, Any]]:
    """为大文件生成轻量结构摘要，优先暴露可定位的行号。"""
    lines = content.splitlines()
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return _build_python_structure_summary(lines)
    return _build_generic_structure_summary(lines)


def _build_python_structure_summary(lines: list[str]) -> list[dict[str, Any]]:
    """提取 Python class/def 名称与行号，帮助模型后续按范围读取。"""
    items: list[dict[str, Any]] = []
    pattern = re.compile(r"^(?P<indent>\s*)(?P<kind>class|def)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
    for line_number, line in enumerate(lines, start=1):
        match = pattern.match(line)
        if not match:
            continue
        items.append(
            {
                "line_number": line_number,
                "kind": match.group("kind"),
                "name": match.group("name"),
                "indent": len(match.group("indent")),
                "line": line.strip(),
            }
        )
        # 截取化结构不限制数量，避免遗漏重要结构线索。
        # if len(items) >= STRUCTURE_SUMMARY_MAX_ITEMS:
        #     break
    return items


def _build_generic_structure_summary(lines: list[str]) -> list[dict[str, Any]]:
    """为普通文本提取 heading、明显分节行和非空行索引。"""
    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        kind = "non_empty"
        if stripped.startswith("#"):
            kind = "heading"
        elif stripped.endswith(":") and len(stripped) <= 120:
            kind = "section"
        items.append(
            {
                "line_number": line_number,
                "kind": kind,
                "line": _truncate_text(stripped, limit=240),
            }
        )
        if len(items) >= STRUCTURE_SUMMARY_MAX_ITEMS:
            break
    return items


@dataclass(slots=True)
class ToolExecution:
    """统一描述一次工具调用的输入和输出。"""

    tool_name: str
    tool_input: dict[str, Any]
    tool_output: dict[str, Any]

    def to_trace_payload(self) -> dict[str, Any]:
        """转换成便于直接写入 trace 的字典。"""
        return asdict(self)


class CoreToolRunner:
    """承载真实 loop 可调用的本地核心工具。"""

    def __init__(self, repo_root: str) -> None:
        """绑定仓库根目录，并记录启动时的文本快照供 diff 使用。"""
        self.repo_root = Path(repo_root).resolve()
        self._baseline_snapshot = self._snapshot_repo_texts()

    def search_text(self, query: str, limit: int = 20) -> ToolExecution:
        """在仓库里做最小文本搜索，返回命中的文件和行号。"""
        matches: list[dict[str, Any]] = []
        for path in sorted(self.repo_root.rglob("*")):
            if len(matches) >= limit:
                break
            if not _is_text_file(path):
                continue
            relative_path = path.relative_to(self.repo_root).as_posix()
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if query in line:
                    matches.append(
                        {
                            "path": relative_path,
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= limit:
                        break

        return ToolExecution(
            tool_name="search_text",
            tool_input={"query": query, "limit": limit},
            tool_output={
                "match_count": len(matches),
                "matches": matches,
            },
        )

    def read_file(self, path: str) -> ToolExecution:
        """读取仓库内 UTF-8 文本文件；大文件只返回结构摘要，不返回全文。"""
        target_path = self._resolve_repo_path(path=path, tool_name="read_file")
        if isinstance(target_path, ToolExecution):
            return target_path

        content_result = self._read_utf8_text(target_path=target_path, tool_name="read_file", path=path)
        if isinstance(content_result, ToolExecution):
            return content_result
        content = content_result
        line_count = _line_count(content)
        if line_count <= FULL_READ_FILE_MAX_LINES or len(content) <= FULL_READ_FILE_MAX_CHARS:
            return ToolExecution(
                tool_name="read_file",
                tool_input={"path": path},
                tool_output={
                    "ok": True,
                    "content": content,
                    "line_count": line_count,
                    "content_mode": "full",
                    "content_truncated": False,
                    "read_coverage": _read_coverage(1, line_count) if line_count else "0-0",
                },
            )

        return ToolExecution(
            tool_name="read_file",
            tool_input={"path": path},
            tool_output={
                "ok": True,
                "line_count": line_count,
                "content_mode": "structure_summary",
                "content_truncated": True,
                "structure_summary": _build_structure_summary(path=path, content=content),
            },
        )

    def read_file_range(self, path: str, start_line: int, end_line: int) -> ToolExecution:
        """读取仓库内 UTF-8 文本文件的闭区间行号范围。"""
        invalid_input = self._validate_line_range_input(
            tool_name="read_file_range",
            path=path,
            start_line=start_line,
            end_line=end_line,
        )
        if invalid_input:
            return invalid_input
        requested_line_count = end_line - start_line + 1
        if requested_line_count > READ_FILE_RANGE_MAX_LINES:
            return self._failed_tool(
                tool_name="read_file_range",
                tool_input={"path": path, "start_line": start_line, "end_line": end_line},
                error="range_too_large",
                detail=f"read_file_range 最多一次读取 {READ_FILE_RANGE_MAX_LINES} 行；本次请求 {requested_line_count} 行。",
            )
        target_path = self._resolve_repo_path(path=path, tool_name="read_file_range")
        if isinstance(target_path, ToolExecution):
            return target_path
        content_result = self._read_utf8_text(target_path=target_path, tool_name="read_file_range", path=path)
        if isinstance(content_result, ToolExecution):
            return content_result

        lines = content_result.splitlines()
        line_count = len(lines)
        if start_line > line_count:
            return self._failed_tool(
                tool_name="read_file_range",
                tool_input={"path": path, "start_line": start_line, "end_line": end_line},
                error="line_range_out_of_bounds",
            )
        actual_end_line = min(end_line, line_count)
        excerpt_lines = lines[start_line - 1 : actual_end_line]
        return ToolExecution(
            tool_name="read_file_range",
            tool_input={"path": path, "start_line": start_line, "end_line": end_line},
            tool_output={
                "ok": True,
                "content_excerpt": "\n".join(excerpt_lines),
                "read_coverage": _read_coverage(start_line, actual_end_line),
                "excerpt_line_start": start_line,
                "excerpt_line_end": actual_end_line,
                "line_count": line_count,
                "content_mode": "range",
                "content_truncated": False,
            },
        )

    def apply_patch(self, path: str, old_text: str | None, new_text: str) -> ToolExecution:
        """对仓库内文件做一次最小文本替换；文件不存在时按新内容创建。"""
        if not isinstance(path, str) or not isinstance(new_text, str) or not (
            isinstance(old_text, str) or old_text is None
        ):
            return ToolExecution(
                tool_name="apply_patch",
                tool_input={"path": path, "old_text": old_text, "new_text": new_text},
                tool_output={
                    "ok": False,
                    "error": "invalid_tool_input",
                    "expected": "path:string, old_text:string|null, new_text:string",
                },
            )
        target_path = self._resolve_repo_path(path=path, tool_name="apply_patch")
        if isinstance(target_path, ToolExecution):
            return target_path

        try:
            original_content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        except UnicodeDecodeError:
            return self._failed_tool(
                tool_name="apply_patch",
                tool_input={"path": path, "old_text": old_text, "new_text": new_text},
                error="non_utf8_text_file",
            )
        except OSError as error:
            return self._failed_tool(
                tool_name="apply_patch",
                tool_input={"path": path, "old_text": old_text, "new_text": new_text},
                error="file_read_failed",
                detail=str(error),
            )

        if old_text is None:
            updated_content = new_text
            action = "create_or_replace"
        elif old_text in original_content:
            updated_content = original_content.replace(old_text, new_text, 1)
            action = "replace_once"
        else:
            return ToolExecution(
                tool_name="apply_patch",
                tool_input={"path": path, "old_text": old_text, "new_text": new_text},
                tool_output={"ok": False, "error": "old_text_not_found"},
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(updated_content, encoding="utf-8")
        return ToolExecution(
            tool_name="apply_patch",
            tool_input={"path": path, "old_text": old_text, "new_text": new_text},
            tool_output={
                "ok": True,
                "action": action,
                "bytes_written": len(updated_content.encode("utf-8")),
            },
        )

    def replace_lines(self, path: str, start_line: int, end_line: int, new_text: str) -> ToolExecution:
        """按闭区间行号替换仓库内 UTF-8 文本文件内容。"""
        invalid_input = self._validate_line_range_input(
            tool_name="replace_lines",
            path=path,
            start_line=start_line,
            end_line=end_line,
            extra_required={"new_text": new_text},
        )
        if invalid_input:
            return invalid_input
        target_path = self._resolve_repo_path(path=path, tool_name="replace_lines")
        if isinstance(target_path, ToolExecution):
            return target_path
        content_result = self._read_utf8_text(target_path=target_path, tool_name="replace_lines", path=path)
        if isinstance(content_result, ToolExecution):
            return content_result

        original_content = content_result
        lines = original_content.splitlines()
        line_count_before = len(lines)
        if start_line > line_count_before or end_line > line_count_before:
            return self._failed_tool(
                tool_name="replace_lines",
                tool_input={"path": path, "start_line": start_line, "end_line": end_line, "new_text": new_text},
                error="line_range_out_of_bounds",
            )

        replacement_lines = new_text.splitlines()
        updated_lines = lines[: start_line - 1] + replacement_lines + lines[end_line:]
        updated_content = "\n".join(updated_lines)
        if original_content.endswith("\n"):
            updated_content += "\n"
        target_path.write_text(updated_content, encoding="utf-8")
        return ToolExecution(
            tool_name="replace_lines",
            tool_input={"path": path, "start_line": start_line, "end_line": end_line, "new_text": new_text},
            tool_output={
                "ok": True,
                "action": "replace_lines",
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "line_count_before": line_count_before,
                "line_count_after": len(updated_lines),
                "bytes_written": len(updated_content.encode("utf-8")),
            },
        )

    def run_command(self, command: list[str] | str) -> ToolExecution:
        """在仓库目录执行命令，保留返回码、标准输出和启动失败原因。"""
        shell = isinstance(command, str)
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
                shell=shell,
            )
        except OSError as error:
            return ToolExecution(
                tool_name="run_command",
                tool_input={"command": command},
                tool_output={
                    "ok": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": str(error),
                    "error": str(error),
                    "error_type": type(error).__name__,
                },
            )
        return ToolExecution(
            tool_name="run_command",
            tool_input={"command": command},
            tool_output={
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

    def git_diff(self, paths: list[str] | None = None) -> ToolExecution:
        """基于启动快照生成最小统一 diff。"""
        candidate_paths = paths or sorted(self._collect_changed_paths())
        diffs: list[dict[str, Any]] = []
        for relative_path in candidate_paths:
            before = self._baseline_snapshot.get(relative_path, "").splitlines()
            current_path = self.repo_root / relative_path
            after_text = current_path.read_text(encoding="utf-8") if current_path.exists() else ""
            after = after_text.splitlines()
            diff_text = "\n".join(
                unified_diff(
                    before,
                    after,
                    fromfile=f"a/{relative_path}",
                    tofile=f"b/{relative_path}",
                    lineterm="",
                )
            )
            if diff_text:
                diffs.append({"path": relative_path, "diff": diff_text})

        return ToolExecution(
            tool_name="git_diff",
            tool_input={"paths": paths},
            tool_output={
                "changed_file_count": len(diffs),
                "diffs": diffs,
            },
        )

    def _resolve_repo_path(self, path: str, tool_name: str) -> Path | ToolExecution:
        """解析仓库内相对路径，并拒绝越界访问。"""
        if not isinstance(path, str) or not path.strip():
            return self._failed_tool(tool_name=tool_name, tool_input={"path": path}, error="invalid_tool_input")
        target_path = (self.repo_root / path).resolve()
        try:
            target_path.relative_to(self.repo_root)
        except ValueError:
            return self._failed_tool(tool_name=tool_name, tool_input={"path": path}, error="path_outside_repo")
        return target_path

    def _read_utf8_text(self, target_path: Path, tool_name: str, path: str) -> str | ToolExecution:
        """读取 UTF-8 文本文件，所有失败都收口为工具结果。"""
        if not target_path.exists():
            return self._failed_tool(tool_name=tool_name, tool_input={"path": path}, error="file_not_found")
        if not target_path.is_file():
            return self._failed_tool(tool_name=tool_name, tool_input={"path": path}, error="not_a_file")
        try:
            return target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return self._failed_tool(tool_name=tool_name, tool_input={"path": path}, error="non_utf8_text_file")
        except OSError as error:
            return self._failed_tool(
                tool_name=tool_name,
                tool_input={"path": path},
                error="file_read_failed",
                detail=str(error),
            )

    def _validate_line_range_input(
        self,
        *,
        tool_name: str,
        path: Any,
        start_line: Any,
        end_line: Any,
        extra_required: dict[str, Any] | None = None,
    ) -> ToolExecution | None:
        """校验行号型工具的输入，避免非法值进入文件写入层。"""
        tool_input = {"path": path, "start_line": start_line, "end_line": end_line}
        if extra_required:
            tool_input.update(extra_required)
        if not isinstance(path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            return self._failed_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                error="invalid_tool_input",
                expected="path:string, start_line:integer, end_line:integer",
            )
        if extra_required and not all(isinstance(value, str) for value in extra_required.values()):
            return self._failed_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                error="invalid_tool_input",
                expected="new_text:string",
            )
        if start_line < 1 or end_line < 1 or start_line > end_line:
            return self._failed_tool(tool_name=tool_name, tool_input=tool_input, error="invalid_line_range")
        return None

    def _failed_tool(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        error: str,
        detail: str | None = None,
        expected: str | None = None,
    ) -> ToolExecution:
        """生成稳定失败工具结果，避免抛出 Python traceback。"""
        output: dict[str, Any] = {"ok": False, "error": error}
        if detail:
            output["detail"] = detail
        if expected:
            output["expected"] = expected
        return ToolExecution(tool_name=tool_name, tool_input=tool_input, tool_output=output)

    def _snapshot_repo_texts(self) -> dict[str, str]:
        """抓取仓库启动时的文本文件快照。"""
        snapshot: dict[str, str] = {}
        if not self.repo_root.exists():
            return snapshot
        for path in sorted(self.repo_root.rglob("*")):
            if not _is_text_file(path):
                continue
            snapshot[path.relative_to(self.repo_root).as_posix()] = path.read_text(encoding="utf-8")
        return snapshot

    def _collect_changed_paths(self) -> set[str]:
        """对比当前仓库与启动快照，找出发生变化的文本文件。"""
        current_paths = {
            path.relative_to(self.repo_root).as_posix()
            for path in self.repo_root.rglob("*")
            if _is_text_file(path)
        }
        return set(self._baseline_snapshot) | current_paths
