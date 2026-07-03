"""整理模型每轮能看到的上下文输入。

这里刻意把上下文分成两层：
`initial_guide` 只在 analyze 阶段生成一次，负责给模型一个首轮导航；
`context_snapshot` 每轮 plan 前重建，负责把当前仍可信的运行事实交给模型。
ContextBuilder 只负责整理事实和结构，不替模型决定下一步该读哪个文件。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from file_structure import build_structure_summary


STRUCTURE_SUMMARY_MAX_ITEMS = 80
SNIPPET_TEXT_LIMIT = 4000
COMMAND_OUTPUT_LIMIT = 4000
STALE_CONTEXT_REASON = "file_was_edited_and_previous_snippets_are_stale"
STALE_CONTEXT_SEQUENCE = ["read_file_structure_summary", "read_file_range"]
# stale 文件的建议放在 stale_context 顶层，因为同一轮里所有 stale 文件共享同一套重读原则。
STALE_CONTEXT_SUGGEST = (
    "先重新建立当前文件结构和最新行号，再按新的行号范围精读，"
    "不要直接重复读取旧片段附近的小范围。"
)


def _is_text_file(path: Path) -> bool:
    """只让 UTF-8 文本文件进入召回，避免二进制或异常编码污染模型上下文。"""
    if not path.is_file():
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _extract_task_keywords(task: str) -> list[str]:
    """保留完整任务文本，再拆出短关键词，用于兼顾精确匹配和宽松召回。"""
    normalized_task = task.strip()
    parts = [
        part
        for part in re.split(r"[\s,，。；:：?？\\/\-]+", normalized_task)
        if part
    ]
    keywords = [normalized_task] if normalized_task else []
    for part in parts:
        if part not in keywords:
            keywords.append(part)
    return keywords


def _truncate_text(value: Any, limit: int) -> str:
    """压缩会进入模型请求的长文本，避免 diff、命令输出或片段内容挤占上下文。"""
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _normalize_string_list(value: Any) -> list[str]:
    """把模型工作记忆收紧为字符串列表，丢弃不符合当前 schema 的临时形态。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass(slots=True)
class SelectedFileGuide:
    """首轮仓库导航里的一项候选文件，只给结构摘要和推荐理由，不提前注入正文。"""

    path: str
    score: int
    reason: str
    structure_summary: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InitialGuide:
    """首轮导航信息，告诉模型任务、候选文件和长期记忆，但不夹带 harness 约束。"""

    task: dict[str, Any]
    repo_guide: dict[str, Any]
    memory_guide: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """导出稳定 schema，避免 dataclass 内部形态泄漏到 trace 或模型请求里。"""
        return {
            "task": dict(self.task),
            "repo_guide": {
                **self.repo_guide,
                "selected_files": [
                    item.to_dict() if hasattr(item, "to_dict") else dict(item)
                    for item in self.repo_guide.get("selected_files", [])
                ],
            },
            "memory_guide": {
                "long_term_memory": list(self.memory_guide.get("long_term_memory", [])),
                "suppressed_long_term_memory": list(
                    self.memory_guide.get("suppressed_long_term_memory", [])
                ),
                "diagnostic_labels": list(self.memory_guide.get("diagnostic_labels", [])),
            },
        }


@dataclass(slots=True)
class ContextSnapshot:
    """每轮 plan 前的运行时事实快照，承接 fresh/stale 上下文和模型工作记忆。"""

    iteration: int
    task: dict[str, Any]
    working_memory: dict[str, Any]
    fresh_context: dict[str, Any]
    stale_context: dict[str, Any]
    recent_facts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """导出模型可消费的当前轮事实，并把缺失字段补成稳定空列表或空字符串。"""
        return {
            "iteration": self.iteration,
            "task": dict(self.task),
            "working_memory": {
                "confirmed_facts": list(self.working_memory.get("confirmed_facts", [])),
                "invalidated_beliefs": list(self.working_memory.get("invalidated_beliefs", [])),
                "completed_actions": list(self.working_memory.get("completed_actions", [])),
                "next_risks": list(self.working_memory.get("next_risks", [])),
                "last_rational": str(self.working_memory.get("last_rational", "")),
            },
            "fresh_context": {
                "file_snippets": list(self.fresh_context.get("file_snippets", [])),
                "diffs": list(self.fresh_context.get("diffs", [])),
                "command_results": list(self.fresh_context.get("command_results", [])),
            },
            "stale_context": {
                "stale_file_paths": list(self.stale_context.get("stale_file_paths", [])),
                "details": list(self.stale_context.get("details", [])),
                "reason": str(self.stale_context.get("reason", "")),
                "recommended_sequence": list(self.stale_context.get("recommended_sequence", [])),
                "suggest": str(self.stale_context.get("suggest", "")),
            },
            "recent_facts": {
                "recent_tool_results": list(self.recent_facts.get("recent_tool_results", [])),
                "failed_tools": list(self.recent_facts.get("failed_tools", [])),
                "signals": list(self.recent_facts.get("signals", [])),
            },
        }


class ContextBuilder:
    """把仓库静态导航和运行时事实整理成模型请求里的两层上下文。

    这个类是上下文边界的唯一入口：首轮用 `build_initial_guide()` 给模型导航，
    后续每轮用 `build_context_snapshot()` 给模型最新事实。它不做语义合并，
    也不把 runtime/max_steps 这类 harness 内部约束暴露给模型。
    """

    def __init__(self, repo_root: str, strategy_config: dict[str, Any] | None = None) -> None:
        """固定仓库根目录和召回策略，保证不同启动目录下得到的相对路径一致。"""
        self.repo_root = Path(repo_root).resolve()
        self.strategy_config = strategy_config or {}
        self.strategy_name = str(self.strategy_config.get("strategy", "file_recall_context")).strip()
        if not self.strategy_name:
            self.strategy_name = "file_recall_context"

    def build_initial_guide(
        self,
        *,
        task: str,
        task_type: str,
        long_term_memory_entries: list[dict[str, Any]] | None = None,
        suppressed_long_term_entries: list[dict[str, Any]] | None = None,
        memory_diagnostic_labels: list[str] | None = None,
    ) -> InitialGuide:
        """生成首轮导航：抽取任务关键词、召回候选文件，并整理长期记忆提示。"""
        task_keywords = _extract_task_keywords(task)
        selected_files, candidate_file_count = self._select_repo_files(
            task_keywords=task_keywords,
            task_type=task_type,
        )
        return InitialGuide(
            task={
                "text": task,
                "task_type": task_type,
                "keywords": task_keywords,
            },
            repo_guide={
                "recall_strategy": self._describe_recall_strategy(task_type=task_type),
                "candidate_file_count": candidate_file_count,
                "selected_files": selected_files,
            },
            memory_guide={
                "long_term_memory": list(long_term_memory_entries or []),
                "suppressed_long_term_memory": list(suppressed_long_term_entries or []),
                "diagnostic_labels": list(memory_diagnostic_labels or []),
            },
        )

    def build_context_snapshot(self, *, runtime_state: Any) -> ContextSnapshot:
        """从 RuntimeState 读取当前事实，生成本轮 plan 要交给模型的运行快照。"""
        task = str(getattr(runtime_state, "task", ""))
        task_type = str(getattr(runtime_state, "task_type", ""))
        observe_content = getattr(runtime_state, "observe_content", {}) or {}
        return ContextSnapshot(
            iteration=int(getattr(runtime_state, "current_iteration", 0) or 0),
            task={
                "text": task,
                "task_type": task_type,
                "keywords": self._task_keywords_from_runtime_state(runtime_state=runtime_state),
            },
            working_memory=self._build_working_memory(runtime_state=runtime_state),
            fresh_context={
                "file_snippets": self._build_file_snippets(runtime_state=runtime_state),
                "diffs": self._build_diff_context(runtime_state=runtime_state),
                "command_results": self._build_command_results(runtime_state=runtime_state),
            },
            stale_context=self._build_stale_context(runtime_state=runtime_state),
            recent_facts={
                "recent_tool_results": list(observe_content.get("recent_tool_results", [])),
                "failed_tools": list(observe_content.get("failed_tools", [])),
                "signals": list(observe_content.get("signals", [])),
            },
        )

    def _task_keywords_from_runtime_state(self, *, runtime_state: Any) -> list[str]:
        """优先复用首轮关键词，避免后续轮次因为重新拆词导致召回口径漂移。"""
        initial_guide = getattr(runtime_state, "initial_guide", None)
        if initial_guide is not None and hasattr(initial_guide, "to_dict"):
            guide_payload = initial_guide.to_dict()
            keywords = guide_payload.get("task", {}).get("keywords", [])
            if isinstance(keywords, list):
                return _normalize_string_list(keywords)
        return _extract_task_keywords(str(getattr(runtime_state, "task", "")))

    def _build_working_memory(self, *, runtime_state: Any) -> dict[str, Any]:
        """把上一轮模型维护的工作记忆放回快照，并补入上一轮显式推理理由。"""
        raw_working_memory = getattr(runtime_state, "working_memory", {}) or {}
        return {
            "confirmed_facts": _normalize_string_list(raw_working_memory.get("confirmed_facts", [])),
            "invalidated_beliefs": _normalize_string_list(raw_working_memory.get("invalidated_beliefs", [])),
            "completed_actions": _normalize_string_list(raw_working_memory.get("completed_actions", [])),
            "next_risks": _normalize_string_list(raw_working_memory.get("next_risks", [])),
            "last_rational": self._last_rational_from_runtime_state(runtime_state=runtime_state),
        }

    def _last_rational_from_runtime_state(self, *, runtime_state: Any) -> str:
        """把上一轮 rationale 注入 working_memory，帮助模型沿着之前的思路继续推理。"""
        model_decision = getattr(runtime_state, "model_decision", None)
        rationale = getattr(model_decision, "rationale", "")
        return str(rationale).strip() if rationale else ""

    def _build_file_snippets(self, *, runtime_state: Any) -> list[dict[str, Any]]:
        """只暴露仍为 fresh 的已读片段，避免模型继续相信编辑前的旧源码。"""
        file_context_cache = getattr(runtime_state, "file_context_cache", {}) or {}
        snippets: list[dict[str, Any]] = []
        for path, cache_entry in sorted(file_context_cache.items()):
            if not isinstance(cache_entry, dict):
                continue
            if cache_entry.get("cache_status") != "fresh":
                continue
            for snippet in cache_entry.get("snippets", []):
                if not isinstance(snippet, dict):
                    continue
                item = {
                    "path": path,
                    "source_tool": str(snippet.get("tool_name", "")),
                    "read_coverage": str(snippet.get("read_coverage", "")),
                    "content": _truncate_text(snippet.get("content_excerpt", ""), SNIPPET_TEXT_LIMIT),
                    "freshness": "fresh",
                }
                structure_summary = snippet.get("structure_summary")
                if structure_summary:
                    item["structure_summary"] = structure_summary
                    if not item["content"]:
                        # 显式结构摘要也属于 fresh 上下文；没有正文时，用 JSON 形式放进 content。
                        item["content"] = _truncate_text(
                            json.dumps(structure_summary, ensure_ascii=False),
                            SNIPPET_TEXT_LIMIT,
                        )
                snippets.append(item)
        return snippets

    def _build_diff_context(self, *, runtime_state: Any) -> list[dict[str, Any]]:
        """整理最近 git_diff 的完整文本摘要，并标出它来自哪一轮 observe 后的事实。"""
        diff_context: list[dict[str, Any]] = []
        from_iteration = self._recent_context_iteration(runtime_state=runtime_state)
        for execution in getattr(runtime_state, "recent_tool_executions", []) or []:
            if getattr(execution, "tool_name", "") != "git_diff":
                continue
            output = getattr(execution, "tool_output", {}) or {}
            paths: list[str] = []
            content_parts: list[str] = []
            for diff in output.get("diffs", []):
                if not isinstance(diff, dict):
                    continue
                path = str(diff.get("path", "")).strip()
                if path:
                    paths.append(path)
                diff_text = str(diff.get("diff", ""))
                if diff_text:
                    content_parts.append(diff_text)
            diff_context.append(
                {
                    "from_iteration": from_iteration,
                    "paths": list(dict.fromkeys(paths)),
                    "content": _truncate_text("\n".join(content_parts), SNIPPET_TEXT_LIMIT),
                }
            )
        return diff_context

    def _build_command_results(self, *, runtime_state: Any) -> list[dict[str, Any]]:
        """把最近命令的返回码和输出压缩进快照，方便模型判断验证或脚本失败原因。"""
        command_results: list[dict[str, Any]] = []
        from_iteration = self._recent_context_iteration(runtime_state=runtime_state)
        for execution in getattr(runtime_state, "recent_tool_executions", []) or []:
            if getattr(execution, "tool_name", "") != "run_command":
                continue
            tool_input = getattr(execution, "tool_input", {}) or {}
            output = getattr(execution, "tool_output", {}) or {}
            command_results.append(
                {
                    "from_iteration": from_iteration,
                    "command": tool_input.get("command", []),
                    "returncode": int(output.get("returncode", 0) or 0),
                    "stdout": _truncate_text(output.get("stdout", ""), COMMAND_OUTPUT_LIMIT),
                    "stderr": _truncate_text(output.get("stderr", ""), COMMAND_OUTPUT_LIMIT),
                }
            )
        return command_results

    def _build_stale_context(self, *, runtime_state: Any) -> dict[str, Any]:
        """列出当前仍 stale 的文件，并给出统一重读顺序，提醒模型先重建结构再精读。"""
        file_context_cache = getattr(runtime_state, "file_context_cache", {}) or {}
        details: list[dict[str, Any]] = []
        for path, cache_entry in sorted(file_context_cache.items()):
            if not isinstance(cache_entry, dict):
                continue
            if cache_entry.get("cache_status") != "stale":
                continue
            details.append(
                {
                    "path": path,
                    "stale_reason": str(cache_entry.get("stale_reason", "")),
                    "previous_covered_ranges": list(cache_entry.get("stale_covered_ranges", [])),
                }
            )
        stale_file_paths = [item["path"] for item in details]
        return {
            "stale_file_paths": stale_file_paths,
            "details": details,
            "reason": STALE_CONTEXT_REASON if stale_file_paths else "",
            "recommended_sequence": list(STALE_CONTEXT_SEQUENCE) if stale_file_paths else [],
            "suggest": STALE_CONTEXT_SUGGEST if stale_file_paths else "",
        }

    def _recent_context_iteration(self, *, runtime_state: Any) -> int:
        """给 diff 和命令结果标注来源轮次，让模型能自行判断这些事实是否偏旧。"""
        observe_content = getattr(runtime_state, "observe_content", {}) or {}
        if isinstance(observe_content, dict) and observe_content.get("iteration"):
            return int(observe_content.get("iteration") or 0)
        return max(0, int(getattr(runtime_state, "current_iteration", 0) or 0) - 1)

    def _select_repo_files(self, task_keywords: list[str], task_type: str) -> tuple[list[SelectedFileGuide], int]:
        """按任务关键词和任务类型选出首轮候选文件，只取前三个，避免首轮上下文过重。"""
        if self.strategy_name == "naive_recent_context":
            return self._select_recent_repo_files()

        candidate_files: list[SelectedFileGuide] = []
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
            candidate_files.append(
                SelectedFileGuide(
                    path=relative_path,
                    score=score,
                    reason=reason,
                    structure_summary=build_structure_summary(
                        path=relative_path,
                        content=content,
                        max_items=STRUCTURE_SUMMARY_MAX_ITEMS,
                    ),
                )
            )

        candidate_files.sort(key=lambda item: (-item.score, item.path))
        return candidate_files[:3], candidate_count

    def _select_recent_repo_files(self) -> tuple[list[SelectedFileGuide], int]:
        """naive_recent_context 策略只按修改时间选文件，用来和任务相关召回做对照实验。"""
        candidate_paths = [path for path in self.repo_root.rglob("*") if _is_text_file(path)]
        selected_files: list[SelectedFileGuide] = []
        sorted_paths = sorted(
            candidate_paths,
            key=lambda item: (-item.stat().st_mtime_ns, item.relative_to(self.repo_root).as_posix()),
        )
        for rank, path in enumerate(sorted_paths[:3], start=1):
            relative_path = path.relative_to(self.repo_root).as_posix()
            content = path.read_text(encoding="utf-8")
            selected_files.append(
                SelectedFileGuide(
                    path=relative_path,
                    score=max(1, 4 - rank),
                    reason=f"当前使用 naive recent context，按最近修改时间选中第 {rank} 个文件。",
                    structure_summary=build_structure_summary(
                        path=relative_path,
                        content=content,
                        max_items=STRUCTURE_SUMMARY_MAX_ITEMS,
                    ),
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
        """给单个文件打召回分数，并保留可写进 trace/report 的中文推荐理由。"""
        score = 0
        reasons: list[str] = []
        lowered_path = relative_path.lower()
        lowered_content = content.lower()
        if "readme" in lowered_path:
            score += 1
            reasons.append("文件名像项目说明")
        if "test" in lowered_path:
            score += 1
            reasons.append("文件名像测试")

        for keyword in task_keywords:
            if keyword and keyword in relative_path:
                score += 2
                reasons.append(f"文件路径包含任务关键词 `{keyword}`")
            if keyword and keyword in content:
                score += 3
                reasons.append(f"文件内容包含任务关键词 `{keyword}`")

        task_type_bonus, task_type_reasons = self._score_by_task_type(
            lowered_path=lowered_path,
            lowered_content=lowered_content,
            task_type=task_type,
        )
        score += task_type_bonus
        reasons.extend(task_type_reasons)

        if score == 0 and relative_path.endswith(".md"):
            score = 1
            reasons.append("保守保留一个文档文件，方便理解仓库")

        return score, "；".join(reasons) if reasons else "未命中召回规则"

    def _score_by_task_type(
        self,
        lowered_path: str,
        lowered_content: str,
        task_type: str,
    ) -> tuple[int, list[str]]:
        """根据任务类型补召回偏好，让 bug_fix、补测试、重构等任务先看到更可能相关的文件。"""
        reasons: list[str] = []
        score = 0
        normalized_task_type = task_type.lower()

        if normalized_task_type == "bug_fix":
            if lowered_path.endswith(".py"):
                score += 2
                reasons.append("bug_fix 优先相关代码文件")
            if "test" in lowered_path:
                score += 3
                reasons.append("bug_fix 优先测试文件")
            if "error" in lowered_content or "fail" in lowered_content:
                score += 2
                reasons.append("文件内容出现失败相关词")
            return score, reasons

        if normalized_task_type == "code_understanding":
            if lowered_path.endswith(".md"):
                score += 3
                reasons.append("理解任务优先说明文档")
            if "readme" in lowered_path:
                score += 2
                reasons.append("README 通常适合先读")
            return score, reasons

        if normalized_task_type == "test_generation":
            if "test" in lowered_path:
                score += 3
                reasons.append("补测试优先现有测试文件")
            if lowered_path.endswith(".py"):
                score += 2
                reasons.append("补测试需要先看代码文件")
            return score, reasons

        if normalized_task_type == "refactor":
            if lowered_path.endswith(".py"):
                score += 3
                reasons.append("重构优先核心代码文件")
            if "utils" in lowered_path or "helper" in lowered_path:
                score += 1
                reasons.append("重构可优先查看公共 helper 文件")
            return score, reasons

        return score, reasons

    def _describe_recall_strategy(self, task_type: str) -> str:
        """生成给模型和报告看的召回策略说明，帮助人回看首轮导航为什么这样选文件。"""
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

