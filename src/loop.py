from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from context import ContextBuilder, ContextSnapshot
from config import RunSettings
from memory import RuntimeMemoryManager
from model import ModelDecision, ModelError, build_model_adapter
from trace import TraceEvent, TraceWriter
from tools import CoreToolRunner, ToolExecution
from verify import VerificationResult, build_phase_4_verification


class AgentState(str, Enum):
    """定义最小状态机里会经过的核心阶段，方便 trace 和控制流共享同一套名字。"""

    INGEST = "ingest"
    ANALYZE = "analyze"
    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    REFLECT = "reflect"
    VERIFY = "verify"
    FINALIZE = "finalize"


class StopReasonCode(str, Enum):
    """定义 run 结束时可记录的结构化停止原因。"""

    COMPLETED = "completed"
    MAX_STEPS_REACHED = "max_steps_reached"
    INTERNAL_ERROR = "internal_error"
    MODEL_ERROR = "model_error"


@dataclass(slots=True)
class StopReason:
    """保存一次 run 为什么结束，以及补充说明细节。"""

    code: StopReasonCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把停止原因转成普通字典，方便写进 trace。"""
        data = asdict(self)
        data["code"] = self.code.value
        return data


@dataclass(slots=True)
class RuntimeState:
    """保存状态机运行过程中的进度、上下文、工具结果和最终验证结果。"""

    task: str
    task_type: str
    current_state: str = "bootstrap"
    completed_states: list[str] = field(default_factory=list)
    step_count: int = 0
    no_progress_count: int = 0
    reflect_triggered: bool = False
    reflect_trigger_reason: str = ""
    context_snapshot: ContextSnapshot | None = None
    model_decision: ModelDecision | None = None
    tool_executions: list[ToolExecution] = field(default_factory=list)
    verification_result: VerificationResult | None = None
    stop_reason: StopReason | None = None

    def mark_completed(self, state: AgentState) -> None:
        """记录某个状态已经执行完，并推进总步数。"""
        self.completed_states.append(state.value)
        self.current_state = state.value
        self.step_count += 1


class LoopOrchestrator:
    """按固定顺序驱动最小状态机，让一次 run 能留下完整可检查的过程证据。"""

    def __init__(self, trace_writer: TraceWriter) -> None:
        """接收 trace writer，保证 loop 每个关键节点都能落进 trace。"""
        self.trace_writer = trace_writer

    def run(self, settings: RunSettings, config_data: dict[str, Any]) -> RuntimeState:
        """执行一条最小 stub 状态链路，并返回最终运行态。"""
        runtime_state = RuntimeState(task=settings.task, task_type=settings.task_type)
        reflect_strategy = self._get_reflect_strategy(config_data=config_data)
        context_builder = ContextBuilder(
            repo_root=settings.repo_root,
            strategy_config=config_data.get("context", {}),
        )
        memory_manager = RuntimeMemoryManager(
            repo_root=settings.repo_root,
            strategy_config=config_data.get("memory", {}),
        )
        tool_runner = CoreToolRunner(repo_root=settings.repo_root)
        planned_states = [
            AgentState.INGEST,
            AgentState.ANALYZE,
            AgentState.PLAN,
            AgentState.ACT,
            AgentState.OBSERVE,
            AgentState.VERIFY,
            AgentState.FINALIZE,
        ]

        index = 0
        while index < len(planned_states):
            state = planned_states[index]
            self._transition(runtime_state, to_state=state, reason="baseline_loop")
            try:
                state_payload = self._run_stub_state(
                    state=state,
                    settings=settings,
                    runtime_state=runtime_state,
                    config_data=config_data,
                    context_builder=context_builder,
                    memory_manager=memory_manager,
                    tool_runner=tool_runner,
                )
            except ModelError as error:
                if state is not AgentState.PLAN:
                    raise
                self._finish_with_model_error(runtime_state=runtime_state, error=error)
                return runtime_state
            runtime_state.mark_completed(state)

            self.trace_writer.write_event(
                TraceEvent(
                    event_type="state_result",
                    payload={
                        "state": state.value,
                        "step_count": runtime_state.step_count,
                        "result": state_payload,
                    },
                )
            )

            # 每次状态完成后都检查一次是否需要补插 reflect，这样不同策略只改这里一处就够了。
            self._maybe_schedule_reflect(
                state=state,
                runtime_state=runtime_state,
                planned_states=planned_states,
                insert_at=index + 1,
                reflect_strategy=reflect_strategy,
            )

            index += 1

        runtime_state.stop_reason = StopReason(
            code=StopReasonCode.COMPLETED,
            message="最小状态机链路已完整跑通。",
            details={
                "completed_states": runtime_state.completed_states,
                "reflect_triggered": runtime_state.reflect_triggered,
                "reflect_trigger_reason": runtime_state.reflect_trigger_reason,
                "verification_passed": runtime_state.verification_result.passed if runtime_state.verification_result else False,
            },
        )
        self.trace_writer.write_event(
            TraceEvent(
                event_type="run_finished",
                payload={
                    "final_state": runtime_state.current_state,
                    "step_count": runtime_state.step_count,
                    "stop_reason": runtime_state.stop_reason.to_dict(),
                },
            )
        )
        return runtime_state

    def _finish_with_model_error(self, runtime_state: RuntimeState, error: ModelError) -> None:
        """把模型决策失败收口成稳定 stop reason，并立即结束 run。"""
        payload = {
            "provider": error.provider,
            "model_name": error.model_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        self.trace_writer.write_event(TraceEvent(event_type="model_decision_failed", payload=payload))
        runtime_state.stop_reason = StopReason(
            code=StopReasonCode.MODEL_ERROR,
            message="模型决策失败，run 已停止。",
            details=payload,
        )
        self.trace_writer.write_event(
            TraceEvent(
                event_type="run_finished",
                payload={
                    "final_state": runtime_state.current_state,
                    "step_count": runtime_state.step_count,
                    "stop_reason": runtime_state.stop_reason.to_dict(),
                },
            )
        )

    def _get_reflect_strategy(self, config_data: dict[str, Any]) -> str:
        """从配置里读取当前 reflect 策略，缺省时回落到现有默认行为。"""
        reflect_config = config_data.get("reflect", {})
        if not isinstance(reflect_config, dict):
            return "low_progress_plus_verify_reflect"
        strategy = str(reflect_config.get("strategy", "low_progress_plus_verify_reflect")).strip()
        return strategy or "low_progress_plus_verify_reflect"

    def _maybe_schedule_reflect(
        self,
        state: AgentState,
        runtime_state: RuntimeState,
        planned_states: list[AgentState],
        insert_at: int,
        reflect_strategy: str,
    ) -> None:
        """根据当前 reflect 策略决定是否在后续流程中插入一次 reflect。"""
        if runtime_state.reflect_triggered:
            return

        if state is AgentState.OBSERVE and reflect_strategy == "low_progress_plus_verify_reflect":
            # 这里保留当前默认基线：当 observe 没看到真实进展时，先触发一次 reflect。
            runtime_state.no_progress_count += 1
            runtime_state.reflect_triggered = True
            runtime_state.reflect_trigger_reason = "no_progress_after_observe"
            planned_states.insert(insert_at, AgentState.REFLECT)
            return

        if (
            state is AgentState.VERIFY
            and runtime_state.verification_result
            and not runtime_state.verification_result.passed
            and reflect_strategy in {"verify_failure_only_reflect", "low_progress_plus_verify_reflect"}
        ):
            # 这里把“验证失败后补反思”单独收口，便于比较不同 reflect 策略的代价和收益。
            runtime_state.reflect_triggered = True
            runtime_state.reflect_trigger_reason = "verification_failed"
            planned_states.insert(insert_at, AgentState.REFLECT)

    def _transition(self, runtime_state: RuntimeState, to_state: AgentState, reason: str) -> None:
        """写入状态迁移事件，并同步更新当前状态指针。"""
        self.trace_writer.write_event(
            TraceEvent(
                event_type="state_transitioned",
                payload={
                    "from_state": runtime_state.current_state,
                    "to_state": to_state.value,
                    "reason": reason,
                },
            )
        )
        runtime_state.current_state = to_state.value

    def _run_stub_state(
        self,
        state: AgentState,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
        context_builder: ContextBuilder,
        memory_manager: RuntimeMemoryManager,
        tool_runner: CoreToolRunner,
    ) -> dict[str, Any]:
        """执行当前阶段的最小占位逻辑，重点是把过程证据写完整。"""
        # 这里故意把每个阶段都写成结构化返回值，后面替换成真实 agent 行为时不必重做 trace 结构。
        if state is AgentState.INGEST:
            return {
                "summary": "已接收任务输入。",
                "task": runtime_state.task,
            }
        if state is AgentState.ANALYZE:
            memory_query = memory_manager.build_query(
                task=runtime_state.task,
                task_type=runtime_state.task_type,
            )
            memory_search_result = memory_manager.search(
                task=runtime_state.task,
                task_type=runtime_state.task_type,
            )
            runtime_rule_entries = [
                entry.to_dict() for entry in memory_search_result.runtime_rule_entries
            ]
            long_term_entries = [
                entry.to_dict() for entry in memory_search_result.long_term_entries
            ]
            suppressed_long_term_entries = list(memory_search_result.suppressed_long_term_entries)
            matched_memory_entries = [
                entry.to_dict() for entry in memory_search_result.all_entries()
            ]
            # 这里把 memory 检索结果单独记成事件，后续做诊断时不必再从 context_snapshot 里反推。
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="memory_search_result",
                    payload={
                        "query": memory_query,
                        "runtime_rule_count": len(runtime_rule_entries),
                        "long_term_count": len(long_term_entries),
                        "suppressed_long_term_count": len(suppressed_long_term_entries),
                        "matched_count": len(matched_memory_entries),
                        "diagnostic_labels": list(memory_search_result.diagnostic_labels),
                        "runtime_rule_entries": runtime_rule_entries,
                        "long_term_entries": long_term_entries,
                        "suppressed_long_term_entries": suppressed_long_term_entries,
                    },
                )
            )
            if memory_search_result.conflict_evidence:
                self.trace_writer.write_event(
                    TraceEvent(
                        event_type="memory_conflict_detected",
                        payload={
                            "query": memory_query,
                            "conflict_count": len(memory_search_result.conflict_evidence),
                            "diagnostic_labels": list(memory_search_result.diagnostic_labels),
                            "conflicts": list(memory_search_result.conflict_evidence),
                        },
                    )
                )

            runtime_state.context_snapshot = context_builder.build_context_snapshot(
                task=runtime_state.task,
                task_type=runtime_state.task_type,
                current_state=runtime_state.current_state,
                completed_states=runtime_state.completed_states,
                step_count=runtime_state.step_count,
                memory_query=memory_query,
                matched_memory_entries=matched_memory_entries,
                runtime_rule_entries=runtime_rule_entries,
                long_term_memory_entries=long_term_entries,
                suppressed_long_term_entries=suppressed_long_term_entries,
                memory_conflict_evidence=memory_search_result.conflict_evidence,
                memory_diagnostic_labels=memory_search_result.diagnostic_labels,
            )
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="context_snapshot",
                    payload=runtime_state.context_snapshot.to_dict(),
                )
            )
            return {
                "summary": "已完成任务初步分析。",
                "task_type": runtime_state.task_type,
                "selected_context_files": [
                    file_context.to_dict()
                    for file_context in runtime_state.context_snapshot.repo_context.selected_files
                ],
            }
        if state is AgentState.PLAN:
            model_adapter = build_model_adapter(config_data=config_data)
            runtime_state.model_decision = model_adapter.decide(
                task=runtime_state.task,
                task_type=runtime_state.task_type,
                context_snapshot=runtime_state.context_snapshot,
                config_data=config_data,
            )
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="model_decision",
                    payload=runtime_state.model_decision.to_dict(),
                )
            )
            return {
                "summary": runtime_state.model_decision.summary,
                "planned_actions": list(runtime_state.model_decision.planned_actions),
                "rationale": runtime_state.model_decision.rationale,
                "provider": runtime_state.model_decision.provider,
                "model_name": runtime_state.model_decision.model_name,
            }
        if state is AgentState.ACT:
            tool_calls = self._run_planned_tools(
                tool_runner=tool_runner,
                model_decision=runtime_state.model_decision,
            )
            runtime_state.tool_executions = tool_calls
            return {
                "summary": "已执行一次由任务级决策层生成的工具计划。",
                "tool_calls": [tool_call.to_trace_payload() for tool_call in tool_calls],
            }
        if state is AgentState.OBSERVE:
            return {
                "summary": "未观察到真实代码变更进展。",
                "progress_made": False,
            }
        if state is AgentState.REFLECT:
            return {
                "summary": "已按策略插入一次 reflect。",
                "trigger": runtime_state.reflect_trigger_reason or "unknown",
            }
        if state is AgentState.VERIFY:
            verification_result = build_phase_4_verification(
                settings=settings,
                tool_executions=runtime_state.tool_executions,
            )
            runtime_state.verification_result = verification_result
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="verification_result",
                    payload=verification_result.to_dict(),
                )
            )
            return {
                "summary": verification_result.summary,
                "verification_passed": verification_result.passed,
                "checks": [check.to_dict() for check in verification_result.checks],
                "config_keys": sorted(config_data.keys()),
            }
        return {
            "summary": "run 即将收尾。",
            "final_status": "success",
        }

    def _run_planned_tools(
        self,
        tool_runner: CoreToolRunner,
        model_decision: ModelDecision,
    ) -> list[ToolExecution]:
        """执行决策层产出的工具计划；工具计划必须来自模型决策。"""
        executions: list[ToolExecution] = []
        planned_tool_calls = [(item.tool_name, item.tool_input) for item in model_decision.tool_calls]

        for tool_name, tool_input in planned_tool_calls:
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="tool_called",
                    payload={
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    },
                )
            )
            execution = getattr(tool_runner, tool_name)(**tool_input)
            executions.append(execution)
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="tool_result",
                    payload=execution.to_trace_payload(),
                )
            )
        return executions
