from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


class RuntimeMemoryManager:
    """提供当前阶段最小可用的 runtime memory 查询接口。"""

    def build_query(self, task: str, task_type: str) -> str:
        """把任务描述和任务类型整理成统一查询词。"""
        normalized_task = task.strip()
        normalized_task_type = task_type.strip() or "ad_hoc"
        return f"{normalized_task_type}:{normalized_task}"

    def search(self, task: str, task_type: str) -> list[MemoryEntry]:
        """根据当前任务返回最小 memory 提示，先把调用接口稳定下来。"""
        normalized_task_type = task_type.strip().lower() or "ad_hoc"
        entries: list[MemoryEntry] = []

        # 第一版先返回规则生成的运行时提示，让 context builder 不再依赖手动传空列表。
        entries.append(
            MemoryEntry(
                title="MVP 开发节奏提示",
                summary="当前阶段优先保证控制面、trace 和测试稳定，不要过早引入复杂智能策略。",
                source="runtime_rule",
                tags=["mvp", "process", normalized_task_type],
                evidence={"task_type": normalized_task_type},
            )
        )

        if normalized_task_type == "bug_fix":
            entries.append(
                MemoryEntry(
                    title="Bug 修复检查顺序",
                    summary="先看失败相关测试，再看触发错误的代码文件，最后确认修复后的 diff 和验证结果。",
                    source="runtime_rule",
                    tags=["bug_fix", "tests", "verify"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "code_understanding":
            entries.append(
                MemoryEntry(
                    title="代码理解阅读顺序",
                    summary="先看 README 和说明文档，再看核心代码文件，最后结合 trace 理解运行流程。",
                    source="runtime_rule",
                    tags=["code_understanding", "docs", "trace"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "test_generation":
            entries.append(
                MemoryEntry(
                    title="补测试时的关注点",
                    summary="优先定位目标代码文件和现有测试模式，生成测试后要确认断言是否覆盖关键行为。",
                    source="runtime_rule",
                    tags=["test_generation", "tests", "coverage"],
                    evidence={"task": task},
                )
            )
        elif normalized_task_type == "refactor":
            entries.append(
                MemoryEntry(
                    title="重构时的保守原则",
                    summary="先理解公共辅助函数和调用方，再做小步修改，并保留验证与 diff 证据。",
                    source="runtime_rule",
                    tags=["refactor", "safety", "diff"],
                    evidence={"task": task},
                )
            )

        return entries
