from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


@dataclass(slots=True)
class MemoryEntry:
    """表示一条当前可供上下文读取的 memory 记录。"""

    title: str
    summary: str
    source: str
    tags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和上下文的字典。"""
        return asdict(self)


@dataclass(slots=True)
class LongTermMemoryEntry:
    """表示一条可落盘保存的长期 memory 记录。"""

    run_id: str
    task: str
    task_type: str
    summary: str
    tags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 JSONL 的字典。"""
        return asdict(self)


@dataclass(slots=True)
class MemorySearchResult:
    """保存一次 memory 查询得到的结构化结果。"""

    runtime_rule_entries: list[MemoryEntry] = field(default_factory=list)
    long_term_entries: list[MemoryEntry] = field(default_factory=list)
    suppressed_long_term_entries: list[dict[str, Any]] = field(default_factory=list)
    conflict_evidence: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_labels: list[str] = field(default_factory=list)

    def all_entries(self) -> list[MemoryEntry]:
        """按展示顺序返回本次查询的全部 memory 条目。"""
        return [*self.runtime_rule_entries, *self.long_term_entries]


def _extract_keywords(text: str) -> list[str]:
    """从任务文本中提取一组稳定关键词，供长期 memory 做最小匹配。"""
    normalized = text.strip().lower()
    parts = [part for part in re.split(r"[\s,，。；:：/\\\-_]+", normalized) if part]
    keywords: list[str] = []
    for part in parts:
        if part not in keywords:
            keywords.append(part)
    if normalized and normalized not in keywords:
        keywords.insert(0, normalized)
    return keywords


def _normalize_file_paths(paths: list[str]) -> list[str]:
    """把文件路径整理成稳定去重格式，避免长期 memory 因路径写法不同而难匹配。"""
    normalized_paths: list[str] = []
    for raw_path in paths:
        normalized_path = str(raw_path).strip().replace("\\", "/")
        if normalized_path and normalized_path not in normalized_paths:
            normalized_paths.append(normalized_path)
    return normalized_paths


def _compress_memory_summary(summary: str, max_length: int = 80) -> tuple[str, int, bool]:
    """把长期 memory 摘要压到稳定长度，避免注入上下文和 trace 时事件体积持续膨胀。"""
    normalized_summary = " ".join(summary.split())
    original_length = len(normalized_summary)
    safe_max_length = max(10, max_length)
    if original_length <= safe_max_length:
        return normalized_summary or "该长期 memory 未提供摘要。", original_length, False
    return f"{normalized_summary[: safe_max_length - 1]}…", original_length, True


class RuntimeMemoryManager:
    """提供当前阶段最小可用的 runtime memory 查询接口。"""

    def __init__(self, repo_root: str, strategy_config: dict[str, Any] | None = None) -> None:
        """绑定仓库根目录，并加载当前 memory 策略配置。"""
        self.repo_root = Path(repo_root).resolve()
        self.long_term_store = LongTermMemoryStore(repo_root=str(self.repo_root))
        self.strategy_config = strategy_config or {}
        self.weak_conflict_penalty = int(self.strategy_config.get("weak_conflict_penalty", 3))
        self.summary_max_length = int(self.strategy_config.get("summary_max_length", 80))

    def build_query(self, task: str, task_type: str) -> str:
        """把任务描述和任务类型整理成统一查询词。"""
        normalized_task = task.strip()
        normalized_task_type = task_type.strip() or "general"
        return f"{normalized_task_type}:{normalized_task}"

    def search(self, task: str, task_type: str) -> MemorySearchResult:
        """返回运行时规则和长期 memory 的组合结果。"""
        normalized_task_type = task_type.strip().lower() or "general"
        runtime_entries: list[MemoryEntry] = []

        # 先保留运行时规则提示，保证没有长期 memory 时也有稳定结果。
        runtime_entries.append(
            MemoryEntry(
                title="MVP 开发节奏提示",
                summary="当前阶段优先保证控制面、trace 和测试稳定，不要过早引入复杂智能策略。",
                source="runtime_rule",
                tags=["mvp", "process", normalized_task_type],
                evidence={"task_type": normalized_task_type},
            )
        )

        if normalized_task_type == "bug_fix":
            runtime_entries.append(
                MemoryEntry(
                    title="Bug 修复检查顺序",
                    summary="先看失败相关测试，再看触发错误的代码文件，最后确认修复后的 diff 和验证结果。",
                    source="runtime_rule",
                    tags=["bug_fix", "tests", "verify"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "code_understanding":
            runtime_entries.append(
                MemoryEntry(
                    title="代码理解阅读顺序",
                    summary="先看 README 和说明文档，再看核心代码文件，最后结合 trace 理解运行流程。",
                    source="runtime_rule",
                    tags=["code_understanding", "docs", "trace"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "test_generation":
            runtime_entries.append(
                MemoryEntry(
                    title="补测试时的关注点",
                    summary="优先定位目标代码文件和现有测试模式，生成测试后要确认断言是否覆盖关键行为。",
                    source="runtime_rule",
                    tags=["test_generation", "tests", "coverage"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "refactor":
            runtime_entries.append(
                MemoryEntry(
                    title="重构时的保守原则",
                    summary="先理解公共辅助函数和调用方，再做小步修改，并保留验证与 diff 证据。",
                    source="runtime_rule",
                    tags=["refactor", "safety", "diff"],
                    evidence={"task": task},
                )
            )

        long_term_entries, conflict_evidence, diagnostic_labels, suppressed_long_term_entries = self._search_long_term_memory(
            task=task,
            task_type=normalized_task_type,
        )
        return MemorySearchResult(
            runtime_rule_entries=runtime_entries,
            long_term_entries=long_term_entries,
            suppressed_long_term_entries=suppressed_long_term_entries,
            conflict_evidence=conflict_evidence,
            diagnostic_labels=diagnostic_labels,
        )

    def _search_long_term_memory(
        self,
        task: str,
        task_type: str,
    ) -> tuple[list[MemoryEntry], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        """按 task type、tags、关键词和路径交集做最小长期 memory 检索。"""
        store_entries = self.long_term_store.read_entries()
        if not store_entries:
            return [], [], [], []

        repo_paths = {
            path.relative_to(self.repo_root).as_posix()
            for path in self.repo_root.rglob("*")
            if path.is_file()
        }
        task_keywords = set(_extract_keywords(task))
        scored_entries: list[dict[str, Any]] = []
        matched_candidates: list[dict[str, Any]] = []

        for item in store_entries:
            score = 0
            matched_on: dict[str, Any] = {}
            entry_task_type = str(item.get("task_type", "")).strip().lower()
            entry_tags = [str(tag).strip().lower() for tag in item.get("tags", []) if str(tag).strip()]
            entry_task = str(item.get("task", ""))
            entry_summary = str(item.get("summary", ""))
            evidence = item.get("evidence", {}) if isinstance(item.get("evidence", {}), dict) else {}
            stored_task_keywords = [
                str(keyword).strip().lower()
                for keyword in evidence.get("task_keywords", [])
                if str(keyword).strip()
            ]
            stored_summary_keywords = [
                str(keyword).strip().lower()
                for keyword in evidence.get("summary_keywords", [])
                if str(keyword).strip()
            ]
            entry_keywords = set(stored_task_keywords + stored_summary_keywords)
            if not entry_keywords:
                # 兼容旧格式 memory：老数据没有显式关键词时，继续从 task + summary 兜底提取。
                entry_keywords = set(_extract_keywords(f"{entry_task} {entry_summary}"))
            matched_keywords = sorted(task_keywords.intersection(entry_keywords))
            selected_paths = _normalize_file_paths(evidence.get("selected_context_files", []))
            matched_paths = sorted(path for path in selected_paths if path in repo_paths)
            summary_excerpt = str(evidence.get("task_summary_excerpt", "")).strip()

            if entry_task_type == task_type:
                score += 3
                matched_on["task_type"] = task_type
            if task_type in entry_tags:
                score += 2
                matched_on["tags"] = [task_type]
            if matched_keywords:
                score += min(4, len(matched_keywords) * 2)
                matched_on["keywords"] = matched_keywords
            if matched_paths:
                score += min(3, len(matched_paths))
                matched_on["file_paths"] = matched_paths

            if score <= 0:
                continue

            matched_candidates.append(
                {
                    "run_id": str(item.get("run_id", "")),
                    "task": entry_task,
                    "task_type": entry_task_type,
                    "matched_keywords": matched_keywords,
                    "matched_paths": matched_paths,
                    "matched_on": matched_on,
                }
            )
            compressed_summary, original_summary_length, summary_was_compressed = _compress_memory_summary(
                entry_summary or "该长期 memory 未提供摘要。",
                max_length=self.summary_max_length,
            )
            scored_entries.append(
                {
                    "run_id": str(item.get("run_id", "")),
                    "task_type": entry_task_type,
                    "raw_score": score,
                    "entry": MemoryEntry(
                        title=f"长期经验：{entry_task[:30] or '未命名任务'}",
                        summary=compressed_summary,
                        source="long_term_memory",
                        tags=entry_tags,
                        evidence={
                            "run_id": item.get("run_id", ""),
                            "task": entry_task,
                            "task_type": entry_task_type,
                            "task_summary_excerpt": summary_excerpt,
                            "original_summary_length": original_summary_length,
                            "summary_was_compressed": summary_was_compressed,
                            "stored_task_keywords": stored_task_keywords,
                            "stored_summary_keywords": stored_summary_keywords,
                            "selected_context_files": selected_paths,
                            "matched_on": matched_on,
                        },
                    ),
                }
            )

        conflict_evidence = self._detect_conflicts(matched_candidates=matched_candidates)
        weak_penalty_by_run_id = self._build_weak_conflict_penalties(
            current_task_type=task_type,
            conflict_evidence=conflict_evidence,
        )
        for item in scored_entries:
            run_id = str(item["run_id"]).strip()
            weak_penalty = weak_penalty_by_run_id.get(run_id, 0)
            item["adjusted_score"] = item["raw_score"] - weak_penalty
            item["entry"].evidence["raw_score"] = item["raw_score"]
            item["entry"].evidence["ranking_penalty"] = weak_penalty
            item["entry"].evidence["adjusted_score"] = item["adjusted_score"]
            if weak_penalty > 0:
                item["entry"].evidence["ranking_adjustment_reason"] = "weak_conflict_with_current_task"
        suppressed_long_term_entries = self._build_suppressed_long_term_entries(
            current_task_type=task_type,
            conflict_evidence=conflict_evidence,
            scored_entries=scored_entries,
        )
        diagnostic_labels = self._build_diagnostic_labels(
            conflict_evidence=conflict_evidence,
            suppressed_long_term_entries=suppressed_long_term_entries,
        )
        scored_entries.sort(
            key=lambda item: (
                -int(item.get("adjusted_score", item["raw_score"])),
                -int(item["raw_score"]),
                str(item["entry"].evidence.get("run_id", "")),
                item["entry"].title,
            )
        )
        suppressed_run_ids = {
            str(item.get("run_id", "")).strip()
            for item in suppressed_long_term_entries
            if str(item.get("run_id", "")).strip()
        }
        long_term_entries = [
            item["entry"]
            for item in scored_entries
            if str(item["entry"].evidence.get("run_id", "")).strip() not in suppressed_run_ids
        ][:3]
        return long_term_entries, conflict_evidence, diagnostic_labels, suppressed_long_term_entries

    def _detect_conflicts(self, matched_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按共享线索强弱记录冲突或提醒，为后续抗污染策略保留梯度。"""
        conflicts: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str, str]] = set()

        for index, left in enumerate(matched_candidates):
            for right in matched_candidates[index + 1 :]:
                if left["task_type"] == right["task_type"]:
                    continue

                shared_keywords = sorted(set(left["matched_keywords"]).intersection(right["matched_keywords"]))
                shared_paths = sorted(set(left["matched_paths"]).intersection(right["matched_paths"]))
                shared_signal_types = 0
                if shared_keywords:
                    shared_signal_types += 1
                if shared_paths:
                    shared_signal_types += 1

                pair_key = (
                    left["run_id"],
                    right["run_id"],
                    "|".join(shared_keywords),
                    "|".join(shared_paths),
                )
                if pair_key in seen_keys:
                    continue
                seen_keys.add(pair_key)

                if shared_signal_types >= 2:
                    severity = "strong"
                    summary = "不同任务类型的长期 memory 共享了多类当前任务线索，需要警惕经验污染。"
                elif shared_signal_types == 1:
                    severity = "weak"
                    summary = "不同任务类型的长期 memory 只共享了单一线索，当前先记为弱提醒。"
                else:
                    continue

                conflicts.append(
                    {
                        "kind": "task_type_mismatch",
                        "severity": severity,
                        "summary": summary,
                        "run_ids": [left["run_id"], right["run_id"]],
                        "task_types": [left["task_type"], right["task_type"]],
                        "tasks": [left["task"], right["task"]],
                        "shared_keywords": shared_keywords,
                        "shared_file_paths": shared_paths,
                        "shared_signal_types": shared_signal_types,
                    }
                )

        return conflicts

    def _build_suppressed_long_term_entries(
        self,
        current_task_type: str,
        conflict_evidence: list[dict[str, Any]],
        scored_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """只压下与当前任务类型不一致且落入强冲突的长期 memory，保留同任务类型经验继续注入。"""
        suppressed_run_ids: set[str] = set()
        for item in conflict_evidence:
            if item.get("severity") != "strong":
                continue
            run_ids = [str(run_id).strip() for run_id in item.get("run_ids", [])]
            task_types = [str(task_type).strip().lower() for task_type in item.get("task_types", [])]
            for run_id, entry_task_type in zip(run_ids, task_types):
                if run_id and entry_task_type and entry_task_type != current_task_type:
                    suppressed_run_ids.add(run_id)

        suppressed_entries: list[dict[str, Any]] = []
        for item in scored_entries:
            entry = item["entry"]
            run_id = str(entry.evidence.get("run_id", "")).strip()
            if run_id not in suppressed_run_ids:
                continue
            suppressed_entries.append(
                {
                    "run_id": run_id,
                    "task": entry.evidence.get("task", ""),
                    "task_type": entry.evidence.get("task_type", ""),
                    "title": entry.title,
                    "reason": "strong_conflict_with_current_task",
                }
            )
        return suppressed_entries

    def _build_weak_conflict_penalties(
        self,
        current_task_type: str,
        conflict_evidence: list[dict[str, Any]],
    ) -> dict[str, int]:
        """让弱提醒不仅停留在标签层，而是真的把异类长期 memory 往后排。"""
        penalty_by_run_id: dict[str, int] = {}
        for item in conflict_evidence:
            if item.get("severity") != "weak":
                continue
            run_ids = [str(run_id).strip() for run_id in item.get("run_ids", [])]
            task_types = [str(task_type).strip().lower() for task_type in item.get("task_types", [])]
            for run_id, entry_task_type in zip(run_ids, task_types):
                if not run_id or not entry_task_type or entry_task_type == current_task_type:
                    continue
                penalty_by_run_id[run_id] = penalty_by_run_id.get(run_id, 0) + self.weak_conflict_penalty
        return penalty_by_run_id

    def _build_diagnostic_labels(
        self,
        conflict_evidence: list[dict[str, Any]],
        suppressed_long_term_entries: list[dict[str, Any]],
    ) -> list[str]:
        """根据冲突证据强弱生成当前最小诊断标签。"""
        if not conflict_evidence:
            return ["memory_injection_suppressed"] if suppressed_long_term_entries else []
        has_strong_conflict = any(item.get("severity") == "strong" for item in conflict_evidence)
        has_weak_conflict = any(item.get("severity") == "weak" for item in conflict_evidence)
        if has_strong_conflict:
            labels = ["memory_conflict", "memory_pollution"]
            if suppressed_long_term_entries:
                labels.append("memory_injection_suppressed")
            return labels
        if has_weak_conflict:
            labels = ["memory_conflict_warning"]
            if suppressed_long_term_entries:
                labels.append("memory_injection_suppressed")
            return labels
        return []


class LongTermMemoryStore:
    """负责把验证通过的 run 写入长期 memory 文件。"""

    def __init__(self, repo_root: str) -> None:
        """绑定仓库根目录，并准备长期 memory 文件路径。"""
        self.repo_root = Path(repo_root).resolve()
        self.store_dir = self.repo_root / ".agent_memory"
        self.store_path = self.store_dir / "long_term_memory.jsonl"

    def append_entry(self, entry: LongTermMemoryEntry) -> Path:
        """把一条长期 memory 记录追加写入 JSONL 文件。"""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self.store_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False))
            handle.write("\n")
        return self.store_path

    def read_entries(self) -> list[dict[str, Any]]:
        """读取当前仓库里已存在的长期 memory 条目。"""
        if not self.store_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        for raw_line in self.store_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries
