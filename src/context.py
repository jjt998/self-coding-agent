from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


def _is_text_file(path: Path) -> bool:
    """判断文件是否适合按文本处理，避免把二进制文件拉进上下文。"""
    if not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


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
    content_preview: str
    score: int

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
    selected_files: list[FileContext] = field(default_factory=list)
    candidate_file_count: int = 0

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
    """为后续 memory 接入预留统一位置，当前先保持为空结构。"""

    enabled: bool = False
    matched_entries: list[dict[str, Any]] = field(default_factory=list)

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

    def __init__(self, repo_root: str) -> None:
        """绑定仓库根目录，后面统一从这里做文件召回。"""
        self.repo_root = Path(repo_root).resolve()

    def build_context_snapshot(
        self,
        task: str,
        task_type: str,
        current_state: str,
        completed_states: list[str],
        step_count: int,
    ) -> ContextSnapshot:
        """收集任务信息、召回相关文件，并整理成四层上下文结构。"""
        task_keywords = _extract_task_keywords(task)
        selected_files, candidate_file_count = self._select_repo_files(task_keywords=task_keywords)
        return ContextSnapshot(
            task_context=TaskContext(task=task, task_type=task_type, keywords=task_keywords),
            repo_context=RepoContext(
                repo_root=str(self.repo_root),
                selected_files=selected_files,
                candidate_file_count=candidate_file_count,
            ),
            runtime_context=RuntimeContext(
                current_state=current_state,
                completed_states=list(completed_states),
                step_count=step_count,
            ),
            memory_context=MemoryContext(),
        )

    def _select_repo_files(self, task_keywords: list[str]) -> tuple[list[FileContext], int]:
        """按最小规则从仓库里挑出值得放进上下文的文件。"""
        candidate_files: list[FileContext] = []
        candidate_count = 0
        for path in sorted(self.repo_root.rglob("*")):
            if not _is_text_file(path):
                continue
            candidate_count += 1
            relative_path = path.relative_to(self.repo_root).as_posix()
            content = path.read_text(encoding="utf-8")
            score, reason = self._score_file(relative_path=relative_path, content=content, task_keywords=task_keywords)
            if score <= 0:
                continue
            candidate_files.append(
                FileContext(
                    path=relative_path,
                    injection_mode=self._choose_injection_mode(content=content, score=score),
                    reason=reason,
                    content_preview=self._build_content_preview(content=content),
                    score=score,
                )
            )

        candidate_files.sort(key=lambda item: (-item.score, item.path))
        return candidate_files[:3], candidate_count

    def _score_file(self, relative_path: str, content: str, task_keywords: list[str]) -> tuple[int, str]:
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

        if score == 0 and relative_path.endswith(".md"):
            score = 1
            reasons.append("当前先保守保留一个文档文件，方便理解仓库")

        return score, "；".join(reasons) if reasons else "未命中召回规则"

    def _choose_injection_mode(self, content: str, score: int) -> str:
        """按文件长度和相关性，决定放原文、摘要还是索引说明。"""
        line_count = len(content.splitlines())
        if score >= 4 and line_count <= 40:
            return "original"
        if score >= 3:
            return "summary"
        return "index"

    def _build_content_preview(self, content: str) -> str:
        """截一小段内容预览，方便 trace 和报告快速看懂选中文件。"""
        preview_lines = [line.strip() for line in content.splitlines() if line.strip()][:3]
        if not preview_lines:
            return "文件为空。"
        return "\n".join(preview_lines)
