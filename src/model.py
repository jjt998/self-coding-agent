from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from context import ContextSnapshot
from tools import build_phase_3_tool_sequence


@dataclass(slots=True)
class PlannedToolCall:
    """描述决策层规划出来的一次工具调用，后面 `act` 阶段会按顺序执行。"""

    tool_name: str
    tool_input: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，方便直接写入 trace。"""
        return asdict(self)


@dataclass(slots=True)
class ModelDecision:
    """保存一次任务级决策结果，包括计划说明和准备执行的工具步骤。"""

    provider: str
    model_name: str
    task_type: str
    summary: str
    rationale: str
    planned_actions: list[str] = field(default_factory=list)
    tool_calls: list[PlannedToolCall] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，便于 trace 和报告复用。"""
        data = asdict(self)
        data["tool_calls"] = [tool_call.to_dict() for tool_call in self.tool_calls]
        return data


class ModelAdapter:
    """抽象一次任务级决策接口，后续可替换成真实模型调用而不改 loop 骨架。"""

    def decide(
        self,
        task: str,
        task_type: str,
        context_snapshot: ContextSnapshot | None,
        config_data: dict[str, Any],
    ) -> ModelDecision:
        """根据任务、上下文和配置，产出一次结构化决策结果。"""
        raise NotImplementedError


class RuleBasedModelAdapter(ModelAdapter):
    """先用规则驱动方式承接决策层接口，逐步替代 plan/act 里的硬编码 stub。"""

    def __init__(self, provider: str, model_name: str) -> None:
        """记录当前决策层使用的 provider 和 model 名称，方便 trace 对比。"""
        self.provider = provider
        self.model_name = model_name

    def decide(
        self,
        task: str,
        task_type: str,
        context_snapshot: ContextSnapshot | None,
        config_data: dict[str, Any],
    ) -> ModelDecision:
        """基于任务类型和上下文文件，给出一版最小但结构稳定的执行计划。"""
        selected_files = []
        if context_snapshot:
            selected_files = [file_context.path for file_context in context_snapshot.repo_context.selected_files]

        task_type_plan_map = {
            "bug_fix": ["定位相关文件", "记录修复路径", "执行任务级验证"],
            "code_understanding": ["阅读关键文件", "整理理解结论", "执行任务级验证"],
            "test_generation": ["定位测试文件", "补充测试说明", "执行任务级验证"],
            "refactor": ["定位目标文件", "记录重构意图", "执行任务级验证"],
        }
        planned_actions = task_type_plan_map.get(task_type, ["定位相关文件", "记录任务处理结果", "执行任务级验证"])

        # 这里先复用现有 Phase 3 工具序列，目的是先把“决策从 loop 中抽出来”，
        # 再逐步把真正的读代码/改代码动作塞进来。
        tool_calls = [
            PlannedToolCall(tool_name=tool_name, tool_input=tool_input)
            for tool_name, tool_input in build_phase_3_tool_sequence(task=task)
        ]
        if selected_files:
            rationale = f"当前优先参考上下文文件：{', '.join(selected_files[:3])}。"
        else:
            rationale = "当前未选出明确上下文文件，先走最小受控工具链保留过程证据。"

        return ModelDecision(
            provider=self.provider,
            model_name=self.model_name,
            task_type=task_type,
            summary="已生成任务级结构化决策结果。",
            rationale=rationale,
            planned_actions=planned_actions,
            tool_calls=tool_calls,
        )


def build_model_adapter(config_data: dict[str, Any]) -> ModelAdapter:
    """根据配置构建决策层适配器，先把 provider/name 两层接口稳定下来。"""
    model_config = config_data.get("model", {})
    if not isinstance(model_config, dict):
        model_config = {}

    provider = str(model_config.get("provider", "rule_based")).strip() or "rule_based"
    model_name = str(model_config.get("name", "phase9-rule-based-planner")).strip() or "phase9-rule-based-planner"
    return RuleBasedModelAdapter(provider=provider, model_name=model_name)
