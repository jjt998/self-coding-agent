from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import unified_diff
from pathlib import Path
import subprocess
import sys
from typing import Any


def _is_text_file(path: Path) -> bool:
    """用最小规则判断文件是否适合按文本读取。"""
    if not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


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
    """承载 Phase 3 的五个核心本地工具。"""

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
        """读取仓库内文本文件，返回是否存在及内容。"""
        target_path = (self.repo_root / path).resolve()
        if not str(target_path).startswith(str(self.repo_root)):
            return ToolExecution(
                tool_name="read_file",
                tool_input={"path": path},
                tool_output={"ok": False, "error": "path_outside_repo"},
            )
        if not target_path.exists():
            return ToolExecution(
                tool_name="read_file",
                tool_input={"path": path},
                tool_output={"ok": False, "error": "file_not_found"},
            )

        content = target_path.read_text(encoding="utf-8")
        return ToolExecution(
            tool_name="read_file",
            tool_input={"path": path},
            tool_output={
                "ok": True,
                "content": content,
                "line_count": len(content.splitlines()),
            },
        )

    def apply_patch(self, path: str, old_text: str | None, new_text: str) -> ToolExecution:
        """对仓库内文件做一次最小文本替换；文件不存在时按新内容创建。"""
        target_path = (self.repo_root / path).resolve()
        if not str(target_path).startswith(str(self.repo_root)):
            return ToolExecution(
                tool_name="apply_patch",
                tool_input={"path": path, "old_text": old_text, "new_text": new_text},
                tool_output={"ok": False, "error": "path_outside_repo"},
            )

        original_content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
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

    def run_command(self, command: list[str]) -> ToolExecution:
        """在仓库目录执行命令，保留返回码与标准输出。"""
        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
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
        """基于启动快照生成最小统一 diff，先把接口稳定下来。"""
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


def build_phase_3_tool_sequence(task: str) -> list[tuple[str, dict[str, Any]]]:
    """按固定顺序准备五个工具调用步骤，供 `act` 阶段依次执行。"""
    notes_path = "agent_notes.md"
    notes_content = (
        "# Agent Notes\n\n"
        f"- 任务：{task}\n"
        "- 当前情况：已记录到 Phase 3 工具闭环。\n"
    )
    # 这里故意用更直白的 notes 命名，避免后续继续引入难懂英文词。
    # 这一组步骤会先搜索，再写入说明文件，然后读回文件内容、执行一次检查命令，最后收集 diff。
    return [
        ("search_text", {"query": "Agent Notes", "limit": 5}),
        ("apply_patch", {"path": notes_path, "old_text": None, "new_text": notes_content}),
        ("read_file", {"path": notes_path}),
        (
            "run_command",
            {
                "command": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; print(Path('agent_notes.md').read_text(encoding='utf-8').splitlines()[0])",
                ]
            },
        ),
        ("git_diff", {"paths": [notes_path]}),
    ]
