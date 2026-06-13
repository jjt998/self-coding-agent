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
    conflict_evidence: list[dict[str, Any]] = field(default_factory=list)

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


class RuntimeMemoryManager:
    """提供当前阶段最小可用的 runtime memory 查询接口。"""

    def __init__(self, repo_root: str) -> None:
        """绑定仓库根目录，方便同时读取运行时规则和长期 memory。"""
        self.repo_root = Path(repo_root).resolve()
        self.long_term_store = LongTermMemoryStore(repo_root=str(self.repo_root))

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

        long_term_entries, conflict_evidence = self._search_long_term_memory(
            task=task,
            task_type=normalized_task_type,
        )
        return MemorySearchResult(
            runtime_rule_entries=runtime_entries,
            long_term_entries=long_term_entries,
            conflict_evidence=conflict_evidence,
        )

    def _search_long_term_memory(self, task: str, task_type: str) -> tuple[list[MemoryEntry], list[dict[str, Any]]]:
        """按 task type、tags、关键词和路径交集做最小长期 memory 检索。"""
        store_entries = self.long_term_store.read_entries()
        if not store_entries:
            return [], []

        repo_paths = {
            path.relative_to(self.repo_root).as_posix()
            for path in self.repo_root.rglob("*")
            if path.is_file()
        }
        task_keywords = set(_extract_keywords(task))
        scored_entries: list[tuple[int, MemoryEntry]] = []

        for item in store_entries:
            score = 0
            matched_on: dict[str, Any] = {}
            entry_task_type = str(item.get("task_type", "")).strip().lower()
            entry_tags = [str(tag).strip().lower() for tag in item.get("tags", []) if str(tag).strip()]
            entry_task = str(item.get("task", ""))
            entry_summary = str(item.get("summary", ""))
            entry_keywords = set(_extract_keywords(f"{entry_task} {entry_summary}"))
            matched_keywords = sorted(task_keywords.intersection(entry_keywords))
            evidence = item.get("evidence", {}) if isinstance(item.get("evidence", {}), dict) else {}
            selected_paths = [
                str(path).strip().replace("\\", "/")
                for path in evidence.get("selected_context_files", [])
                if str(path).strip()
            ]
            matched_paths = sorted(path for path in selected_paths if path in repo_paths)

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

            scored_entries.append(
                (
                    score,
                    MemoryEntry(
                        title=f"长期经验：{entry_task[:30] or '未命名任务'}",
                        summary=entry_summary or "该长期 memory 未提供摘要。",
                        source="long_term_memory",
                        tags=entry_tags,
                        evidence={
                            "run_id": item.get("run_id", ""),
                            "task": entry_task,
                            "task_type": entry_task_type,
                            "matched_on": matched_on,
                        },
                    ),
                )
            )

        scored_entries.sort(
            key=lambda item: (
                -item[0],
                str(item[1].evidence.get("run_id", "")),
                item[1].title,
            )
        )
        long_term_entries = [entry for _, entry in scored_entries[:3]]
        return long_term_entries, []


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
