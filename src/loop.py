from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from config import RunSettings
from trace import TraceEvent, TraceWriter
from tools import CoreToolRunner, ToolExecution, build_phase_3_tool_sequence


class AgentState(str, Enum):
    """定义基线状态机里会经过的核心状态。"""

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


@dataclass(slots=True)
class StopReason:
    """保存一次 run 结束原因及补充说明。"""

    code: StopReasonCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把停止原因转换成便于写入 trace 的字典。"""
        data = asdict(self)
        data["code"] = self.code.value
        return data


@dataclass(slots=True)
class RuntimeState:
    """保存状态机运行中的阶段、步数和停止信息。"""

    task: str
    task_type: str
    current_state: str = "bootstrap"
    completed_states: list[str] = field(default_factory=list)
    step_count: int = 0
    no_progress_count: int = 0
    reflect_triggered: bool = False
    stop_reason: StopReason | None = None

    def mark_completed(self, state: AgentState) -> None:
        """记录某个状态已经完成，并推进步数。"""
        self.completed_states.append(state.value)
        self.current_state = state.value
        self.step_count += 1


class LoopOrchestrator:
    """按固定顺序驱动最小状态机 loop 的执行。"""

    def __init__(self, trace_writer: TraceWriter) -> None:
        """接收 trace writer，供 loop 过程持续记证。"""
        self.trace_writer = trace_writer

    def run(self, settings: RunSettings, config_data: dict[str, Any]) -> RuntimeState:
        """执行一条最小 stub 状态链路并返回最终运行态。"""
        runtime_state = RuntimeState(task=settings.task, task_type=settings.task_type)
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
            state_payload = self._run_stub_state(
                state=state,
                runtime_state=runtime_state,
                config_data=config_data,
                tool_runner=tool_runner,
            )
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

            if state is AgentState.OBSERVE and not runtime_state.reflect_triggered:
                # Phase 2 先用“observe 没看到真实进展”来触发一次 reflect，占住条件反思的控制面。
                runtime_state.no_progress_count += 1
                runtime_state.reflect_triggered = True
                planned_states.insert(index + 1, AgentState.REFLECT)

            index += 1

        runtime_state.stop_reason = StopReason(
            code=StopReasonCode.COMPLETED,
            message="最小状态机链路已完整跑通。",
            details={
                "completed_states": runtime_state.completed_states,
                "reflect_triggered": runtime_state.reflect_triggered,
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

    def _transition(self, runtime_state: RuntimeState, to_state: AgentState, reason: str) -> None:
        """写入状态迁移事件，并更新当前状态指针。"""
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
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
        tool_runner: CoreToolRunner,
    ) -> dict[str, Any]:
        """为当前阶段生成占位结果，先把控制面和 trace 结构跑通。"""
        # 这里故意把每个状态的产出写成结构化占位结果，后面接模型和工具时可以渐进替换。
        if state is AgentState.INGEST:
            return {
                "summary": "已接收任务输入。",
                "task": runtime_state.task,
            }
        if state is AgentState.ANALYZE:
            return {
                "summary": "已完成任务初步分析。",
                "task_type": runtime_state.task_type,
            }
        if state is AgentState.PLAN:
            return {
                "summary": "已生成最小执行计划。",
                "planned_actions": ["stub_act_once", "stub_verify_once"],
            }
        if state is AgentState.ACT:
            tool_calls = self._run_phase_3_tools(tool_runner=tool_runner, task=runtime_state.task)
            return {
                "summary": "已执行一次最小核心工具闭环。",
                "tool_calls": [tool_call.to_trace_payload() for tool_call in tool_calls],
            }
        if state is AgentState.OBSERVE:
            return {
                "summary": "未观察到真实代码变更进展。",
                "progress_made": False,
            }
        if state is AgentState.REFLECT:
            return {
                "summary": "因无进展触发一次占位 reflect。",
                "trigger": "no_progress_after_observe",
            }
        if state is AgentState.VERIFY:
            return {
                "summary": "stub 链路验证通过。",
                "verification_passed": True,
                "config_keys": sorted(config_data.keys()),
            }
        return {
            "summary": "run 即将收尾。",
            "final_status": "success",
        }

    def _run_phase_3_tools(self, tool_runner: CoreToolRunner, task: str) -> list[ToolExecution]:
        """执行 Phase 3 的受控工具序列，并把调用前后都写入 trace。"""
        executions: list[ToolExecution] = []
        for tool_name, tool_input in build_phase_3_tool_sequence(task=task):
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
