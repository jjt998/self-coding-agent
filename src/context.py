from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


STRUCTURE_SUMMARY_MAX_ITEMS = 80


def _is_text_file(path: Path) -> bool:
    """判断文件是否适合按文本处理，避免把二进制文件拉进上下文。"""
    if not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _truncate_structure_line(value: str, limit: int = 240) -> str:
    """截断结构摘要里的单行文本，避免初始上下文过长。"""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _build_structure_summary(relative_path: str, content: str) -> list[dict[str, Any]]:
    """为召回文件生成轻量结构摘要，帮助模型按行号继续读取。"""
    lines = content.splitlines()
    if Path(relative_path).suffix.lower() == ".py":
        return _build_python_structure_summary(lines)
    return _build_generic_structure_summary(lines)


def _build_python_structure_summary(lines: list[str]) -> list[dict[str, Any]]:
    """提取 Python 文件中的 class/def 名称和行号。"""
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
        if len(items) >= STRUCTURE_SUMMARY_MAX_ITEMS:
            break
    return items


def _build_generic_structure_summary(lines: list[str]) -> list[dict[str, Any]]:
    """为普通文本提取 heading、分节行和非空行索引。"""
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
                "line": _truncate_structure_line(stripped),
            }
        )
        if len(items) >= STRUCTURE_SUMMARY_MAX_ITEMS:
            break
    return items


def _extract_task_keywords(task: str) -> list[str]:
    """从任务文本里提取最小关键词，供文件召回打分使用。"""
    normalized_task = task.strip()
    parts = [part for part in re.split(r"[\s,，。；:：/\\\-]+", normalized_task) if part]
    keywords = [normalized_task] if normalized_task else []
    for part in parts:
        if part not in keywords:
            keywords.append(part)
    return keywords


@dataclass(slots=True)
class FileContext:
    """表示一个被召回的仓库文件，以及为什么把它放进本次上下文。"""

    path: str
    injection_mode: str
    reason: str
    injection_content: str
    content_preview: str
    score: int
    total_line_count: int
    included_line_count: int
    was_clipped: bool
    structure_summary: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return asdict(self)


@dataclass(slots=True)
class TaskContext:
    """保存本次任务本身的上下文。"""

    task: str
    task_type: str
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return asdict(self)


@dataclass(slots=True)
class RepoContext:
    """保存从仓库里召回出来的文件上下文。"""

    repo_root: str
    recall_strategy: str
    selected_files: list[FileContext] = field(default_factory=list)
    candidate_file_count: int = 0
    selected_file_count: int = 0
    total_selected_lines: int = 0
    total_original_lines: int = 0
    clipped_file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        data = asdict(self)
        data["selected_files"] = [file_context.to_dict() for file_context in self.selected_files]
        return data


@dataclass(slots=True)
class RuntimeContext:
    """保存本次运行中与当前阶段相关的上下文。"""

    current_state: str
    completed_states: list[str] = field(default_factory=list)
    step_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return asdict(self)


@dataclass(slots=True)
class MemoryContext:
    """保存本次分析阶段拿到的 memory 结果。"""

    enabled: bool = False
    query: str = ""
    matched_entries: list[dict[str, Any]] = field(default_factory=list)
    runtime_rule_entries: list[dict[str, Any]] = field(default_factory=list)
    long_term_entries: list[dict[str, Any]] = field(default_factory=list)
    suppressed_long_term_entries: list[dict[str, Any]] = field(default_factory=list)
    conflict_evidence: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_labels: list[str] = field(default_factory=list)
    source: str = "disabled"

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return asdict(self)


@dataclass(slots=True)
class ContextSnapshot:
    """汇总本次运行某个阶段拿到的四层上下文。"""

    task_context: TaskContext
    repo_context: RepoContext
    runtime_context: RuntimeContext
    memory_context: MemoryContext

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return {
            "task_context": self.task_context.to_dict(),
            "repo_context": self.repo_context.to_dict(),
            "runtime_context": self.runtime_context.to_dict(),
            "memory_context": self.memory_context.to_dict(),
        }


class ContextBuilder:
    """根据任务和仓库内容构建当前阶段可检查的最小上下文快照。"""

    def __init__(self, repo_root: str, strategy_config: dict[str, Any] | None = None) -> None:
        """绑定仓库根目录，后面统一从这里做文件召回。"""
        self.repo_root = Path(repo_root).resolve()
        self.strategy_config = strategy_config or {}
        self.strategy_name = str(self.strategy_config.get("strategy", "file_recall_context")).strip() or "file_recall_context"
        # 第一版先把裁剪规则固定成简单常量，后面更换策略时只改这里即可。
        self.original_line_limit = 40
        self.summary_line_limit = 8
        self.index_line_limit = 5

    def build_context_snapshot(
        self,
        task: str,
        task_type: str,
        current_state: str,
        completed_states: list[str],
        step_count: int,
        memory_query: str = "",
        matched_memory_entries: list[dict[str, Any]] | None = None,
        runtime_rule_entries: list[dict[str, Any]] | None = None,
        long_term_memory_entries: list[dict[str, Any]] | None = None,
        suppressed_long_term_entries: list[dict[str, Any]] | None = None,
        memory_conflict_evidence: list[dict[str, Any]] | None = None,
        memory_diagnostic_labels: list[str] | None = None,
    ) -> ContextSnapshot:
        """收集任务信息、召回相关文件，并整理成四层上下文结构。"""
        task_keywords = _extract_task_keywords(task)
        selected_files, candidate_file_count = self._select_repo_files(
            task_keywords=task_keywords,
            task_type=task_type,
        )
        matched_entries = matched_memory_entries or []
        runtime_entries = runtime_rule_entries or []
        long_term_entries = long_term_memory_entries or []
        suppressed_entries = suppressed_long_term_entries or []
        conflict_evidence = memory_conflict_evidence or []
        diagnostic_labels = memory_diagnostic_labels or []
        return ContextSnapshot(
            task_context=TaskContext(task=task, task_type=task_type, keywords=task_keywords),
            repo_context=RepoContext(
                repo_root=str(self.repo_root),
                recall_strategy=self._describe_recall_strategy(task_type=task_type),
                selected_files=selected_files,
                candidate_file_count=candidate_file_count,
                selected_file_count=len(selected_files),
                total_selected_lines=sum(file_context.included_line_count for file_context in selected_files),
                total_original_lines=sum(file_context.total_line_count for file_context in selected_files),
                clipped_file_count=sum(1 for file_context in selected_files if file_context.was_clipped),
            ),
            runtime_context=RuntimeContext(
                current_state=current_state,
                completed_states=list(completed_states),
                step_count=step_count,
            ),
            memory_context=MemoryContext(
                enabled=bool(matched_entries or runtime_entries or long_term_entries),
                query=memory_query,
                matched_entries=matched_entries,
                runtime_rule_entries=runtime_entries,
                long_term_entries=long_term_entries,
                suppressed_long_term_entries=suppressed_entries,
                conflict_evidence=conflict_evidence,
                diagnostic_labels=diagnostic_labels,
                source="runtime_memory_manager"
                if (matched_entries or runtime_entries or long_term_entries or suppressed_entries)
                else "disabled",
            ),
        )

    def _select_repo_files(self, task_keywords: list[str], task_type: str) -> tuple[list[FileContext], int]:
        """按最小规则从仓库里挑出值得放进上下文的文件。"""
        if self.strategy_name == "naive_recent_context":
            return self._select_recent_repo_files()

        candidate_files: list[FileContext] = []
        candidate_count = 0
        for path in sorted(self.repo_root.rglob("*")):
            if not _is_text_file(path):
                continue
            candidate_count += 1
            relative_path = path.relative_to(self.repo_root).as_posix()
            content = path.read_text(encoding="utf-8")
            score, reason = self._score_file(
                relative_path=relative_path,
                content=content,
                task_keywords=task_keywords,
                task_type=task_type,
            )
            if score <= 0:
                continue
            injection_mode = self._choose_injection_mode(content=content, score=score)
            injection_content, included_line_count, was_clipped = self._build_injection_content(
                relative_path=relative_path,
                content=content,
                injection_mode=injection_mode,
            )
            structure_summary = _build_structure_summary(relative_path=relative_path, content=content)
            candidate_files.append(
                FileContext(
                    path=relative_path,
                    injection_mode=injection_mode,
                    reason=reason,
                    injection_content=injection_content,
                    content_preview=self._build_content_preview(content=content),
                    score=score,
                    total_line_count=len(content.splitlines()),
                    included_line_count=included_line_count,
                    was_clipped=was_clipped,
                    structure_summary=structure_summary,
                )
            )

        candidate_files.sort(key=lambda item: (-item.score, item.path))
        return candidate_files[:3], candidate_count

    def _select_recent_repo_files(self) -> tuple[list[FileContext], int]:
        """按最近修改时间挑出文件，作为第一版 `naive_recent_context` 对照策略。"""
        candidate_paths: list[Path] = []
        for path in self.repo_root.rglob("*"):
            if _is_text_file(path):
                candidate_paths.append(path)

        selected_files: list[FileContext] = []
        sorted_paths = sorted(
            candidate_paths,
            key=lambda item: (-item.stat().st_mtime_ns, item.relative_to(self.repo_root).as_posix()),
        )
        for rank, path in enumerate(sorted_paths[:3], start=1):
            relative_path = path.relative_to(self.repo_root).as_posix()
            content = path.read_text(encoding="utf-8")
            line_count = len(content.splitlines())
            pseudo_score = 4 if line_count <= self.original_line_limit else 3
            injection_mode = self._choose_injection_mode(content=content, score=pseudo_score)
            injection_content, included_line_count, was_clipped = self._build_injection_content(
                relative_path=relative_path,
                content=content,
                injection_mode=injection_mode,
            )
            structure_summary = _build_structure_summary(relative_path=relative_path, content=content)
            selected_files.append(
                FileContext(
                    path=relative_path,
                    injection_mode=injection_mode,
                    reason=f"当前使用 naive recent context，按最近修改时间选中第 {rank} 个文件。",
                    injection_content=injection_content,
                    content_preview=self._build_content_preview(content=content),
                    score=max(1, 4 - rank),
                    total_line_count=line_count,
                    included_line_count=included_line_count,
                    was_clipped=was_clipped,
                    structure_summary=structure_summary,
                )
            )
        return selected_files, len(candidate_paths)

    def _score_file(
        self,
        relative_path: str,
        content: str,
        task_keywords: list[str],
        task_type: str,
    ) -> tuple[int, str]:
        """给文件做一个简单分数，分数越高表示越值得先读。"""
        score = 0
        reasons: list[str] = []
        lowered_path = relative_path.lower()
        if "readme" in lowered_path:
            score += 1
            reasons.append("文件名像项目说明")
        if "test" in lowered_path:
            score += 1
            reasons.append("文件名像测试")

        for keyword in task_keywords:
            if keyword and keyword in relative_path:
                score += 2
                reasons.append(f"文件路径包含任务关键词“{keyword}”")
            if keyword and keyword in content:
                score += 3
                reasons.append(f"文件内容包含任务关键词“{keyword}”")

        task_type_bonus, task_type_reasons = self._score_by_task_type(
            lowered_path=lowered_path,
            content=content,
            task_type=task_type,
        )
        score += task_type_bonus
        reasons.extend(task_type_reasons)

        if score == 0 and relative_path.endswith(".md"):
            score = 1
            reasons.append("当前先保守保留一个文档文件，方便理解仓库")

        return score, "；".join(reasons) if reasons else "未命中召回规则"

    def _score_by_task_type(self, lowered_path: str, content: str, task_type: str) -> tuple[int, list[str]]:
        """按任务类型补充分数，让不同任务优先看到更合适的文件。"""
        reasons: list[str] = []
        score = 0
        normalized_task_type = task_type.lower()

        if normalized_task_type == "bug_fix":
            if lowered_path.endswith(".py"):
                score += 2
                reasons.append("当前任务像修 bug，先提高代码文件优先级")
            if "test" in lowered_path:
                score += 3
                reasons.append("当前任务像修 bug，测试文件更值得优先检查")
            if "error" in content or "fail" in content:
                score += 2
                reasons.append("文件内容里出现失败相关词，可能和 bug 线索有关")
            return score, reasons

        if normalized_task_type == "code_understanding":
            if lowered_path.endswith(".md"):
                score += 3
                reasons.append("当前任务偏理解代码，说明文档优先级更高")
            if "readme" in lowered_path:
                score += 2
                reasons.append("当前任务偏理解代码，README 往往更适合先读")
            return score, reasons

        if normalized_task_type == "test_generation":
            if "test" in lowered_path:
                score += 3
                reasons.append("当前任务要补测试，测试文件优先级更高")
            if lowered_path.endswith(".py"):
                score += 2
                reasons.append("当前任务要补测试，需要先看代码文件")
            return score, reasons

        if normalized_task_type == "refactor":
            if lowered_path.endswith(".py"):
                score += 3
                reasons.append("当前任务偏重构，代码文件优先级更高")
            if "utils" in lowered_path or "helper" in lowered_path:
                score += 1
                reasons.append("当前任务偏重构，公共辅助文件值得先检查")
            return score, reasons

        return score, reasons

    def _describe_recall_strategy(self, task_type: str) -> str:
        """用一句白话说明当前任务类型使用的召回倾向。"""
        if self.strategy_name == "naive_recent_context":
            return "优先最近修改的文本文件（naive_recent_context）"

        normalized_task_type = task_type.lower()
        if normalized_task_type == "bug_fix":
            return "优先测试文件和相关代码文件"
        if normalized_task_type == "code_understanding":
            return "优先说明文档和仓库介绍文件"
        if normalized_task_type == "test_generation":
            return "优先现有测试文件和目标代码文件"
        if normalized_task_type == "refactor":
            return "优先核心代码文件和公共辅助文件"
        return "按任务关键词和通用文件规则做保守召回"

    def _choose_injection_mode(self, content: str, score: int) -> str:
        """按文件长度和相关性，决定放原文、摘要还是索引说明。"""
        line_count = len(content.splitlines())
        if score >= 4 and line_count <= self.original_line_limit:
            return "original"
        if score >= 3:
            return "summary"
        return "index"

    def _build_injection_content(
        self,
        relative_path: str,
        content: str,
        injection_mode: str,
    ) -> tuple[str, int, bool]:
        """根据注入方式生成真正放进上下文的内容，并记录是否裁剪。"""
        lines = content.splitlines()
        if injection_mode == "original":
            selected_lines = lines[: self.original_line_limit]
            was_clipped = len(lines) > self.original_line_limit
            return "\n".join(selected_lines), len(selected_lines), was_clipped

        if injection_mode == "summary":
            selected_lines = [line.strip() for line in lines if line.strip()][: self.summary_line_limit]
            summary_lines = [
                f"文件：{relative_path}",
                f"总行数：{len(lines)}",
                "内容摘要：",
            ]
            summary_lines.extend(f"- {line}" for line in selected_lines)
            was_clipped = len([line for line in lines if line.strip()]) > self.summary_line_limit
            return "\n".join(summary_lines), len(selected_lines), was_clipped

        index_lines = [line.strip() for line in lines if line.strip()][: self.index_line_limit]
        index_text = "；".join(index_lines) if index_lines else "文件为空。"
        return (
            f"文件：{relative_path}\n总行数：{len(lines)}\n索引提示：{index_text}",
            len(index_lines),
            len([line for line in lines if line.strip()]) > self.index_line_limit,
        )

    def _build_content_preview(self, content: str) -> str:
        """截一小段内容预览，方便 trace 和报告快速看懂选中文件。"""
        preview_lines = [line.strip() for line in content.splitlines() if line.strip()][:3]
        if not preview_lines:
            return "文件为空。"
        return "\n".join(preview_lines)
