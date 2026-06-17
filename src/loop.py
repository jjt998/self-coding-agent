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
    SETUP_FAILED = "setup_failed"
    VERIFICATION_FAILED = "verification_failed"
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
    reflect_count: int = 0
    reflect_trigger_reasons: list[str] = field(default_factory=list)
    reflect_feedback: dict[str, Any] = field(default_factory=dict)
    reflect_feedback_history: list[dict[str, Any]] = field(default_factory=list)
    current_iteration: int = 0
    iteration_count: int = 0
    max_steps: int = 1
    context_snapshot: ContextSnapshot | None = None
    model_decision: ModelDecision | None = None
    model_decisions: list[ModelDecision] = field(default_factory=list)
    tool_executions: list[ToolExecution] = field(default_factory=list)
    recent_tool_executions: list[ToolExecution] = field(default_factory=list)
    progress_made: bool = False
    changed_files: list[str] = field(default_factory=list)
    failed_tool_count: int = 0
    observation_summary: str = ""
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
        self._active_iteration = 0

    def run(self, settings: RunSettings, config_data: dict[str, Any]) -> RuntimeState:
        """执行最小多轮求解 loop，并返回最终运行态。"""
        runtime_state = RuntimeState(task=settings.task, task_type=settings.task_type)
        runtime_state.max_steps = self._get_max_steps(config_data=config_data)
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

        for state in [AgentState.INGEST, AgentState.ANALYZE]:
            self._execute_state(
                state=state,
                settings=settings,
                runtime_state=runtime_state,
                config_data=config_data,
                context_builder=context_builder,
                memory_manager=memory_manager,
                tool_runner=tool_runner,
            )

        stop_code = StopReasonCode.MAX_STEPS_REACHED
        stop_message = "已达到最大求解轮数，run 已停止。"
        for iteration in range(1, runtime_state.max_steps + 1):
            runtime_state.current_iteration = iteration
            runtime_state.iteration_count = iteration
            reflected_this_iteration = False

            for state in [AgentState.PLAN, AgentState.ACT, AgentState.OBSERVE]:
                try:
                    self._execute_state(
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

            if self._should_reflect_after_observe(
                runtime_state=runtime_state,
                reflect_strategy=reflect_strategy,
            ):
                self._record_reflect_trigger(runtime_state=runtime_state, reason="no_progress_after_observe")
                self._execute_state(
                    state=AgentState.REFLECT,
                    settings=settings,
                    runtime_state=runtime_state,
                    config_data=config_data,
                    context_builder=context_builder,
                    memory_manager=memory_manager,
                    tool_runner=tool_runner,
                )
                reflected_this_iteration = True

            self._execute_state(
                state=AgentState.VERIFY,
                settings=settings,
                runtime_state=runtime_state,
                config_data=config_data,
                context_builder=context_builder,
                memory_manager=memory_manager,
                tool_runner=tool_runner,
            )
            if runtime_state.verification_result and runtime_state.verification_result.passed:
                stop_code = StopReasonCode.COMPLETED
                stop_message = "最小多轮求解链路已验证通过。"
                break
            if runtime_state.verification_result and not runtime_state.verification_result.passed:
                stop_code = StopReasonCode.VERIFICATION_FAILED
                stop_message = "验证失败，run 已停止。"

            has_next_iteration = iteration < runtime_state.max_steps
            if has_next_iteration and not reflected_this_iteration and self._should_reflect_after_verify(
                runtime_state=runtime_state,
                reflect_strategy=reflect_strategy,
            ):
                self._record_reflect_trigger(runtime_state=runtime_state, reason="verification_failed")
                self._execute_state(
                    state=AgentState.REFLECT,
                    settings=settings,
                    runtime_state=runtime_state,
                    config_data=config_data,
                    context_builder=context_builder,
                    memory_manager=memory_manager,
                    tool_runner=tool_runner,
                )

        self._execute_state(
            state=AgentState.FINALIZE,
            settings=settings,
            runtime_state=runtime_state,
            config_data=config_data,
            context_builder=context_builder,
            memory_manager=memory_manager,
            tool_runner=tool_runner,
        )
        self._finish_run(runtime_state=runtime_state, code=stop_code, message=stop_message)
        return runtime_state

    def _execute_state(
        self,
        state: AgentState,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
        context_builder: ContextBuilder,
        memory_manager: RuntimeMemoryManager,
        tool_runner: CoreToolRunner,
    ) -> dict[str, Any]:
        """执行一个状态并统一写入迁移与状态结果事件。"""
        self._transition(runtime_state, to_state=state, reason="baseline_loop")
        state_payload = self._run_state(
            state=state,
            settings=settings,
            runtime_state=runtime_state,
            config_data=config_data,
            context_builder=context_builder,
            memory_manager=memory_manager,
            tool_runner=tool_runner,
        )
        runtime_state.mark_completed(state)
        self.trace_writer.write_event(
            TraceEvent(
                event_type="state_result",
                payload={
                    "state": state.value,
                    "iteration": runtime_state.current_iteration,
                    "step_count": runtime_state.step_count,
                    "result": state_payload,
                },
            )
        )
        return state_payload

    def _finish_run(self, runtime_state: RuntimeState, code: StopReasonCode, message: str) -> None:
        """写入统一 run_finished 事件。"""
        runtime_state.stop_reason = StopReason(
            code=code,
            message=message,
            details=self._build_stop_reason_details(runtime_state=runtime_state),
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

    def _build_stop_reason_details(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """整理 run 结束时需要保留的兼容字段和多轮信息。"""
        verification_passed = bool(runtime_state.verification_result and runtime_state.verification_result.passed)
        return {
            "completed_states": runtime_state.completed_states,
            "max_steps": runtime_state.max_steps,
            "iteration_count": runtime_state.iteration_count,
            "reflect_triggered": runtime_state.reflect_triggered,
            "reflect_trigger_reason": runtime_state.reflect_trigger_reason,
            "reflect_count": runtime_state.reflect_count,
            "reflect_trigger_reasons": list(runtime_state.reflect_trigger_reasons),
            "verification_passed": verification_passed,
            "verification_failure": self._build_verification_failure_details(runtime_state=runtime_state),
            "progress_made": runtime_state.progress_made,
            "changed_files": runtime_state.changed_files,
            "failed_tool_count": runtime_state.failed_tool_count,
            "reflect_feedback": dict(runtime_state.reflect_feedback),
        }

    def _get_max_steps(self, config_data: dict[str, Any]) -> int:
        """读取最大求解轮数；本轮把 max_steps 解释为最大 plan/act/verify 轮数。"""
        runtime_config = config_data.get("runtime", {})
        if not isinstance(runtime_config, dict):
            return 2
        raw_value = runtime_config.get("max_steps", 2)
        if isinstance(raw_value, int):
            return max(1, raw_value)
        if isinstance(raw_value, str) and raw_value.strip():
            try:
                return max(1, int(raw_value.strip()))
            except ValueError:
                return 2
        return 2

    def _should_reflect_after_observe(self, runtime_state: RuntimeState, reflect_strategy: str) -> bool:
        """判断 observe 后是否需要因为无进展触发 reflect。"""
        return (
            reflect_strategy == "low_progress_plus_verify_reflect"
            and runtime_state.progress_made is False
        )

    def _should_reflect_after_verify(self, runtime_state: RuntimeState, reflect_strategy: str) -> bool:
        """判断 verify 失败后是否需要触发 reflect。"""
        return (
            runtime_state.verification_result is not None
            and not runtime_state.verification_result.passed
            and reflect_strategy in {"verify_failure_only_reflect", "low_progress_plus_verify_reflect"}
        )

    def _record_reflect_trigger(self, runtime_state: RuntimeState, reason: str) -> None:
        """记录一次 reflect 触发，同时保留旧的单值字段兼容 eval。"""
        runtime_state.reflect_triggered = True
        runtime_state.reflect_trigger_reason = reason
        runtime_state.reflect_trigger_reasons.append(reason)
        runtime_state.reflect_count += 1
        if reason == "no_progress_after_observe":
            runtime_state.no_progress_count += 1

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

    def _build_runtime_feedback(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """给下一轮 plan 提供上一轮执行反馈，避免模型盲目重复同一计划。"""
        if runtime_state.current_iteration <= 1 and not runtime_state.verification_result:
            return {}
        verification_payload = (
            runtime_state.verification_result.to_dict()
            if runtime_state.verification_result
            else {}
        )
        return {
            "iteration": runtime_state.current_iteration,
            "remaining_iterations": max(runtime_state.max_steps - runtime_state.current_iteration + 1, 0),
            "previous_observation": {
                "progress_made": runtime_state.progress_made,
                "changed_files": list(runtime_state.changed_files),
                "failed_tool_count": runtime_state.failed_tool_count,
                "summary": runtime_state.observation_summary,
            },
            "previous_verification": verification_payload,
            "previous_reflect_feedback": self._build_previous_reflect_feedback(runtime_state=runtime_state),
            "recent_tool_results": [
                self._summarize_tool_execution(execution)
                for execution in runtime_state.recent_tool_executions
            ],
        }

    def _build_previous_reflect_feedback(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Return the latest reflect feedback with direct constraints for the next plan."""
        if not runtime_state.reflect_feedback:
            return {}
        feedback = dict(runtime_state.reflect_feedback)
        feedback["replan_constraints"] = self._build_replan_constraints(runtime_state=runtime_state)
        return feedback

    def _build_replan_constraints(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Convert recent failure evidence into compact model-consumable replan constraints."""
        verification_failure = self._build_verification_failure_details(runtime_state=runtime_state)
        failed_check_names = list(verification_failure.get("failing_check_names", []))
        failed_tools = [
            self._summarize_tool_execution(execution)
            for execution in runtime_state.recent_tool_executions
            if execution.tool_output.get("ok") is False
            or (execution.tool_name == "run_command" and execution.tool_output.get("returncode", 0) != 0)
        ]
        previous_tool_sequence = [execution.tool_name for execution in runtime_state.recent_tool_executions]
        suggested_tools: list[str] = []
        if not runtime_state.progress_made:
            suggested_tools.extend(["apply_patch", "git_diff"])
        if failed_check_names:
            suggested_tools.extend(["read_file", "apply_patch", "run_command", "git_diff"])
        if failed_tools:
            suggested_tools.append("run_command")

        trigger = runtime_state.reflect_trigger_reason or "unknown"
        if trigger == "no_progress_after_observe":
            failure_reason = "no_progress_after_observe"
        elif failed_check_names:
            failure_reason = "verification_failed"
        elif failed_tools:
            failure_reason = "tool_failed"
        else:
            failure_reason = trigger

        return {
            "failure_reason": failure_reason,
            "must_address": self._build_suggested_focus(
                runtime_state=runtime_state,
                verification_failure=verification_failure,
                failed_tool_summaries=failed_tools,
            ),
            "avoid_exact_tool_sequence": previous_tool_sequence,
            "failed_check_names": failed_check_names,
            "failed_tools": failed_tools,
            "suggested_focus_files": list(runtime_state.changed_files),
            "suggested_tools": list(dict.fromkeys(suggested_tools)),
        }

    def _summarize_reflect_feedback_for_trace(self, runtime_feedback: dict[str, Any]) -> dict[str, Any]:
        """Keep model_decision trace compact while exposing replan evidence."""
        reflect_feedback = runtime_feedback.get("previous_reflect_feedback", {})
        if not isinstance(reflect_feedback, dict) or not reflect_feedback:
            return {}
        constraints = reflect_feedback.get("replan_constraints", {})
        if not isinstance(constraints, dict):
            constraints = {}
        return {
            "trigger": reflect_feedback.get("trigger", ""),
            "failure_reason": constraints.get("failure_reason", ""),
            "failed_check_names": list(constraints.get("failed_check_names", [])),
            "must_address": list(constraints.get("must_address", [])),
            "avoid_exact_tool_sequence": list(constraints.get("avoid_exact_tool_sequence", [])),
        }

    def _summarize_tool_execution(self, execution: ToolExecution) -> dict[str, Any]:
        """压缩工具结果，避免把大段 stdout、文件内容或 diff 原样塞回模型。"""
        output = execution.tool_output
        summary: dict[str, Any] = {
            "tool_name": execution.tool_name,
            "ok": output.get("ok"),
        }
        if "error" in output:
            summary["error"] = output.get("error")
        if "returncode" in output:
            summary["returncode"] = output.get("returncode")
        if execution.tool_name == "git_diff":
            summary["changed_file_count"] = output.get("changed_file_count", 0)
            summary["changed_files"] = [
                item.get("path")
                for item in output.get("diffs", [])
                if isinstance(item, dict) and item.get("path")
            ]
        if execution.tool_name == "search_text":
            summary["match_count"] = output.get("match_count", 0)
        if execution.tool_name == "read_file":
            summary["line_count"] = output.get("line_count", 0)
        return summary

    def _run_state(
        self,
        state: AgentState,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
        context_builder: ContextBuilder,
        memory_manager: RuntimeMemoryManager,
        tool_runner: CoreToolRunner,
    ) -> dict[str, Any]:
        """Route each state to a dedicated handler while preserving trace payloads."""
        if state is AgentState.INGEST:
            return self._run_ingest(settings=settings, runtime_state=runtime_state, config_data=config_data)
        if state is AgentState.ANALYZE:
            return self._run_analyze(
                runtime_state=runtime_state,
                context_builder=context_builder,
                memory_manager=memory_manager,
            )
        if state is AgentState.PLAN:
            return self._run_plan(runtime_state=runtime_state, config_data=config_data)
        if state is AgentState.ACT:
            return self._run_act(runtime_state=runtime_state, tool_runner=tool_runner)
        if state is AgentState.OBSERVE:
            return self._run_observe(runtime_state=runtime_state)
        if state is AgentState.REFLECT:
            return self._run_reflect(runtime_state=runtime_state)
        if state is AgentState.VERIFY:
            return self._run_verify(settings=settings, runtime_state=runtime_state, config_data=config_data)
        if state is AgentState.FINALIZE:
            return self._run_finalize(runtime_state=runtime_state)
        raise ValueError(f"Unsupported agent state: {state}")

    def _run_ingest(
        self,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Capture concrete run inputs before analysis starts."""
        model_config = config_data.get("model", {})
        if not isinstance(model_config, dict):
            model_config = {}
        reflect_config = config_data.get("reflect", {})
        if not isinstance(reflect_config, dict):
            reflect_config = {}
        payload = {
            "summary": "Task input and run constraints captured.",
            "task": runtime_state.task,
            "task_type": runtime_state.task_type,
            "repo_root": settings.repo_root,
            "source_repo_root": settings.source_repo_root,
            "workspace_mode": settings.workspace_mode,
            "sandbox_dir": settings.sandbox_dir,
            "setup_command_count": len(settings.setup_commands),
            "verify_command_count": len(settings.verify_commands),
            "verify_rule_count": len(settings.verify_rules),
            "max_steps": runtime_state.max_steps,
            "config_name": settings.config_name,
            "config_keys": sorted(config_data.keys()),
            "model_provider": model_config.get("provider", ""),
            "model_name": model_config.get("name", ""),
            "reflect_strategy": reflect_config.get("strategy", self._get_reflect_strategy(config_data=config_data)),
        }
        self.trace_writer.write_event(TraceEvent(event_type="task_ingested", payload=payload))
        return payload

    def _run_analyze(
        self,
        runtime_state: RuntimeState,
        context_builder: ContextBuilder,
        memory_manager: RuntimeMemoryManager,
    ) -> dict[str, Any]:
        """Build memory and context evidence for model planning."""
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
            "summary": "Initial task analysis completed.",
            "task_type": runtime_state.task_type,
            "selected_context_files": [
                file_context.to_dict()
                for file_context in runtime_state.context_snapshot.repo_context.selected_files
            ],
        }

    def _run_plan(self, runtime_state: RuntimeState, config_data: dict[str, Any]) -> dict[str, Any]:
        """Ask the configured model adapter for the next tool plan."""
        model_adapter = build_model_adapter(config_data=config_data)
        runtime_feedback = self._build_runtime_feedback(runtime_state=runtime_state)
        reflect_feedback_summary = self._summarize_reflect_feedback_for_trace(runtime_feedback=runtime_feedback)
        runtime_state.model_decision = model_adapter.decide(
            task=runtime_state.task,
            task_type=runtime_state.task_type,
            context_snapshot=runtime_state.context_snapshot,
            config_data=config_data,
            runtime_feedback=runtime_feedback,
        )
        runtime_state.model_decisions.append(runtime_state.model_decision)
        self.trace_writer.write_event(
            TraceEvent(
                event_type="model_decision",
                payload={
                    **runtime_state.model_decision.to_dict(),
                    "iteration": runtime_state.current_iteration,
                    "has_reflect_feedback": bool(reflect_feedback_summary),
                    "reflect_feedback_summary": reflect_feedback_summary,
                },
            )
        )
        return {
            "summary": runtime_state.model_decision.summary,
            "planned_actions": list(runtime_state.model_decision.planned_actions),
            "rationale": runtime_state.model_decision.rationale,
            "provider": runtime_state.model_decision.provider,
            "model_name": runtime_state.model_decision.model_name,
        }

    def _run_act(self, runtime_state: RuntimeState, tool_runner: CoreToolRunner) -> dict[str, Any]:
        """Execute the model-planned tool calls for the current iteration."""
        self._active_iteration = runtime_state.current_iteration
        tool_calls = self._run_planned_tools(
            tool_runner=tool_runner,
            model_decision=runtime_state.model_decision,
        )
        runtime_state.recent_tool_executions = tool_calls
        runtime_state.tool_executions.extend(tool_calls)
        return {
            "summary": "Executed the model-planned tool sequence.",
            "tool_calls": [tool_call.to_trace_payload() for tool_call in tool_calls],
        }

    def _run_observe(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Interpret recent tool results as progress evidence."""
        return self._observe_progress(runtime_state=runtime_state)

    def _run_reflect(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Produce structured feedback for the next planning round."""
        reflect_feedback = self._build_reflect_feedback(runtime_state=runtime_state)
        runtime_state.reflect_feedback = reflect_feedback
        runtime_state.reflect_feedback_history.append(reflect_feedback)
        self.trace_writer.write_event(TraceEvent(event_type="reflect_feedback", payload=reflect_feedback))
        return reflect_feedback

    def _run_verify(
        self,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Run task verification against the latest iteration's tool results."""
        verification_result = build_phase_4_verification(
            settings=settings,
            tool_executions=runtime_state.recent_tool_executions,
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

    def _run_finalize(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Capture final runtime evidence before run_finished is emitted."""
        verification_passed = bool(runtime_state.verification_result and runtime_state.verification_result.passed)
        payload = {
            "summary": "Final runtime evidence captured before run finish.",
            "final_status": "success" if verification_passed else "incomplete",
            "verification_passed": verification_passed,
            "progress_made": runtime_state.progress_made,
            "changed_files": list(runtime_state.changed_files),
            "failed_tool_count": runtime_state.failed_tool_count,
            "reflect_count": runtime_state.reflect_count,
            "reflect_trigger_reasons": list(runtime_state.reflect_trigger_reasons),
            "iteration_count": runtime_state.iteration_count,
            "max_steps": runtime_state.max_steps,
            "tool_execution_count": len(runtime_state.tool_executions),
            "model_decision_count": len(runtime_state.model_decisions),
            "completed_states_before_finalize": list(runtime_state.completed_states),
        }
        self.trace_writer.write_event(TraceEvent(event_type="finalize_summary", payload=payload))
        return payload

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
                        "iteration": self._current_tool_iteration(),
                    },
                )
            )
            execution = getattr(tool_runner, tool_name)(**tool_input)
            executions.append(execution)
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="tool_result",
                    payload={
                        **execution.to_trace_payload(),
                        "iteration": self._current_tool_iteration(),
                    },
                )
            )
        return executions

    def _current_tool_iteration(self) -> int:
        """返回当前工具调用所属轮次；工具 runner 本身不持有 runtime_state。"""
        return getattr(self, "_active_iteration", 0)

    def _observe_progress(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """根据工具执行结果判断本轮是否已经产生真实进展。"""
        changed_files: list[str] = []
        successful_tools: list[str] = []
        failed_tools: list[dict[str, Any]] = []
        failed_execution_ids: set[int] = set()
        apply_patch_succeeded = False

        for index, execution in enumerate(runtime_state.recent_tool_executions):
            tool_output = execution.tool_output
            ok = tool_output.get("ok")

            if ok is True:
                successful_tools.append(execution.tool_name)
                if execution.tool_name == "apply_patch":
                    apply_patch_succeeded = True

            if execution.tool_name == "git_diff":
                changed_file_count = int(tool_output.get("changed_file_count") or 0)
                if changed_file_count > 0:
                    successful_tools.append(execution.tool_name)
                for diff in tool_output.get("diffs", []):
                    if isinstance(diff, dict) and isinstance(diff.get("path"), str):
                        changed_files.append(diff["path"])

            if ok is False:
                failed_execution_ids.add(index)
                failed_tools.append(
                    {
                        "tool_name": execution.tool_name,
                        "error": tool_output.get("error", ""),
                        "returncode": tool_output.get("returncode"),
                    }
                )

            if execution.tool_name == "run_command" and tool_output.get("returncode", 0) != 0:
                if index not in failed_execution_ids:
                    failed_execution_ids.add(index)
                    failed_tools.append(
                        {
                            "tool_name": execution.tool_name,
                            "error": tool_output.get("stderr", ""),
                            "returncode": tool_output.get("returncode"),
                        }
                    )

        changed_files = list(dict.fromkeys(changed_files))
        successful_tools = list(dict.fromkeys(successful_tools))
        progress_made = bool(changed_files) or apply_patch_succeeded
        failed_tool_count = len(failed_execution_ids)
        observation_summary = self._build_observation_summary(
            progress_made=progress_made,
            changed_files=changed_files,
            failed_tool_count=failed_tool_count,
            successful_tools=successful_tools,
        )

        runtime_state.progress_made = progress_made
        runtime_state.changed_files = changed_files
        runtime_state.failed_tool_count = failed_tool_count
        runtime_state.observation_summary = observation_summary

        payload = {
            "summary": observation_summary,
            "iteration": runtime_state.current_iteration,
            "progress_made": progress_made,
            "changed_files": changed_files,
            "successful_tools": successful_tools,
            "failed_tools": failed_tools,
            "failed_tool_count": failed_tool_count,
        }
        # 感觉这里和上游的state_result事件有点重复，但又不好合并，因为这个事件里有一些专门针对 observe 的字段，先保持分开，后续如果觉得冗余再调整。
        self.trace_writer.write_event(TraceEvent(event_type="progress_observed", payload=payload))
        return payload

    def _build_observation_summary(
        self,
        progress_made: bool,
        changed_files: list[str],
        failed_tool_count: int,
        successful_tools: list[str],
    ) -> str:
        """生成报告和 state_result 共用的进展观察摘要。"""
        if progress_made:
            return (
                f"已观察到真实进展：变更文件 {len(changed_files)} 个，"
                f"成功工具 {len(successful_tools)} 个，失败工具 {failed_tool_count} 个。"
            )
        return (
            f"未观察到文件变更或成功编辑进展；"
            f"成功工具 {len(successful_tools)} 个，失败工具 {failed_tool_count} 个。"
        )

    def _build_verification_failure_details(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Extract stable details from the latest failed verification result."""
        verification_result = runtime_state.verification_result
        if not verification_result or verification_result.passed:
            return {}

        checks = [check.to_dict() for check in verification_result.checks]
        failing_checks = [check for check in checks if not bool(check.get("passed"))]
        verify_command_results = verification_result.details.get("verify_command_results", [])
        failed_commands = [
            item
            for item in verify_command_results
            if isinstance(item, dict) and not bool(item.get("ok"))
        ]
        failed_rule_types = self._extract_failed_verify_rule_types(
            failing_checks=failing_checks,
            verify_command_count=int(verification_result.details.get("verify_command_count", 0) or 0),
        )
        return {
            "summary": verification_result.summary,
            "failing_checks": failing_checks,
            "failing_check_names": [
                str(check.get("name", "")).strip()
                for check in failing_checks
                if str(check.get("name", "")).strip()
            ],
            "failed_commands": failed_commands,
            "failed_rule_types": failed_rule_types,
            "verification_mode": verification_result.details.get("verification_mode", ""),
            "verify_command_count": verification_result.details.get("verify_command_count", 0),
            "verify_rule_count": verification_result.details.get("verify_rule_count", 0),
        }

    def _extract_failed_verify_rule_types(
        self,
        failing_checks: list[dict[str, Any]],
        verify_command_count: int,
    ) -> list[str]:
        """Classify failed verify checks by stable rule family for stop reason details."""
        rule_types: list[str] = []
        for check in failing_checks:
            name = str(check.get("name", "")).strip()
            if name.startswith("verify_command_"):
                continue
            if not name:
                continue
            # The rule type is not stored on checks yet; preserve a stable generic class.
            rule_types.append("verify_rule")
        return rule_types

    def _build_reflect_feedback(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """Build structured reflect feedback for the next planning round."""
        verification_failure = self._build_verification_failure_details(runtime_state=runtime_state)
        failed_tool_summaries = [
            self._summarize_tool_execution(execution)
            for execution in runtime_state.recent_tool_executions
            if execution.tool_output.get("ok") is False
            or (execution.tool_name == "run_command" and execution.tool_output.get("returncode", 0) != 0)
        ]
        suggested_focus: list[str] = []
        if not runtime_state.progress_made:
            suggested_focus.append("需要产生可观察的文件变更或成功编辑。")
        if verification_failure.get("failing_check_names"):
            suggested_focus.append("需要优先修复未通过的验证检查。")
        if failed_tool_summaries:
            suggested_focus.append("需要修复失败工具调用或命令返回码。")
        if not suggested_focus:
            suggested_focus.append("根据上一轮证据调整工具计划。")

        return {
            "summary": "已生成结构化 reflect 反馈。",
            "iteration": runtime_state.current_iteration,
            "trigger": runtime_state.reflect_trigger_reason or "unknown",
            "observation": {
                "progress_made": runtime_state.progress_made,
                "changed_files": list(runtime_state.changed_files),
                "failed_tool_count": runtime_state.failed_tool_count,
                "summary": runtime_state.observation_summary,
            },
            "verification_failure": verification_failure,
            "failed_tools": failed_tool_summaries,
            "suggested_focus": suggested_focus,
            "replan_constraints": self._build_replan_constraints(runtime_state=runtime_state),
        }

    def _build_suggested_focus(
        self,
        runtime_state: RuntimeState,
        verification_failure: dict[str, Any],
        failed_tool_summaries: list[dict[str, Any]],
    ) -> list[str]:
        """Build stable focus tags for model-facing replan constraints."""
        suggested_focus: list[str] = []
        if not runtime_state.progress_made:
            suggested_focus.append("produce_observable_file_change")
        if verification_failure.get("failing_check_names"):
            suggested_focus.append("fix_failing_verification_checks")
        if failed_tool_summaries:
            suggested_focus.append("fix_failed_tool_or_command")
        if not suggested_focus:
            suggested_focus.append("adjust_next_tool_plan_from_previous_evidence")
        return suggested_focus
