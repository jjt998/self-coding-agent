from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from context import ContextBuilder, ContextSnapshot
from config import RunSettings
from memory import RuntimeMemoryManager
from model import ModelDecision, ModelError, ModelResponseError, TOOL_SCHEMAS, build_model_adapter
from trace import TraceEvent, TraceWriter
from tools import FULL_READ_FILE_MAX_CHARS, FULL_READ_FILE_MAX_LINES, CoreToolRunner, ToolExecution
from verify import VerificationResult, build_phase_4_verification


class AgentState(str, Enum):
    """定义最小状态机里会经过的核心阶段，方便 trace 和控制流共享同一套名字。"""

    INGEST = "ingest"
    ANALYZE = "analyze"
    PLAN = "plan"
    ACT = "act"
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
    reflect_triggered: bool = False
    reflect_trigger_reason: str = ""
    reflect_count: int = 0
    reflect_trigger_reasons: list[str] = field(default_factory=list)
    reflect_feedback: dict[str, Any] = field(default_factory=dict)
    reflect_feedback_history: list[dict[str, Any]] = field(default_factory=list)
    current_iteration: int = 0
    iteration_count: int = 0
    max_steps: int = 4
    context_snapshot: ContextSnapshot | None = None
    model_decision: ModelDecision | None = None
    model_decisions: list[ModelDecision] = field(default_factory=list)
    cross_round_plan: list[str] = field(default_factory=list)
    cross_round_plan_history: list[list[str]] = field(default_factory=list)
    tool_executions: list[ToolExecution] = field(default_factory=list)
    recent_tool_executions: list[ToolExecution] = field(default_factory=list)
    file_context_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    failed_tool_count: int = 0
    observation_summary: str = ""
    token_usage: dict[str, Any] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
            "complete": True,
            "missing_usage_count": 0,
        }
    )
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

            for state in [AgentState.PLAN, AgentState.ACT]:
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
                    if state not in {AgentState.PLAN, AgentState.ACT}:
                        raise
                    self._finish_with_model_error(runtime_state=runtime_state, error=error)
                    return runtime_state

            self._record_reflect_trigger(runtime_state=runtime_state, reason="after_act")
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
            "changed_files": runtime_state.changed_files,
            "failed_tool_count": runtime_state.failed_tool_count,
            "reflect_feedback": dict(runtime_state.reflect_feedback),
            "cross_round_plan": list(runtime_state.cross_round_plan),
            "token_usage": dict(runtime_state.token_usage),
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

    def _record_reflect_trigger(self, runtime_state: RuntimeState, reason: str) -> None:
        """记录一次固定 reflect，同时保留旧的单值字段兼容 eval。"""
        runtime_state.reflect_triggered = True
        runtime_state.reflect_trigger_reason = reason
        runtime_state.reflect_trigger_reasons.append(reason)
        runtime_state.reflect_count += 1

    def _finish_with_model_error(self, runtime_state: RuntimeState, error: ModelError) -> None:
        """把模型决策失败收口成稳定 stop reason，并立即结束 run。"""
        payload = {
            "provider": error.provider,
            "model_name": error.model_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "token_usage": dict(runtime_state.token_usage),
            **error.details,
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
        """给下一轮 plan 提供事实型反馈，不暴露轮数预算。"""
        if runtime_state.current_iteration <= 1 and not runtime_state.verification_result:
            return {}
        verification_payload = (
            runtime_state.verification_result.to_dict()
            if runtime_state.verification_result
            else {}
        )
        return {
            "previous_reflect": self._build_previous_reflect(runtime_state=runtime_state),
            "previous_verification": verification_payload,
            "previous_cross_round_plan": list(runtime_state.cross_round_plan),
        }

    def _build_previous_reflect(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """返回上一轮 reflect 事实，并把最新验证事实合并进去。"""
        if not runtime_state.reflect_feedback:
            return {}
        feedback = deepcopy(runtime_state.reflect_feedback)
        feedback.pop("iteration", None)
        observation = feedback.get("observation")
        if isinstance(observation, dict):
            sanitized_observation = dict(observation)
            sanitized_observation.pop("iteration", None)
            feedback["observation"] = sanitized_observation
        feedback["verification"] = (
            runtime_state.verification_result.to_dict()
            if runtime_state.verification_result
            else {}
        )
        return feedback

    def _summarize_reflect_feedback_for_trace(self, runtime_feedback: dict[str, Any]) -> dict[str, Any]:
        """让 model_decision trace 保持精简，同时暴露上一轮事实反馈。"""
        reflect_feedback = runtime_feedback.get("previous_reflect", {})
        if not isinstance(reflect_feedback, dict) or not reflect_feedback:
            return {}
        verification = reflect_feedback.get("verification", {})
        failing_checks: list[str] = []
        if isinstance(verification, dict):
            failing_checks = [
                str(check.get("name", "")).strip()
                for check in verification.get("checks", [])
                if isinstance(check, dict) and not bool(check.get("passed")) and str(check.get("name", "")).strip()
            ]
        return {
            "trigger": reflect_feedback.get("trigger", ""),
            "signals": list(reflect_feedback.get("signals", [])),
            "changed_files": list((reflect_feedback.get("observation") or {}).get("changed_files", [])),
            "failed_tool_count": (reflect_feedback.get("observation") or {}).get("failed_tool_count", 0),
            "failed_check_names": failing_checks,
        }

    def _summarize_tool_execution(
        self,
        execution: ToolExecution,
        recent_executions: list[ToolExecution] | None = None,
    ) -> dict[str, Any]:
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
        if execution.tool_name in {"read_file", "read_file_range", "apply_patch", "replace_lines"}:
            path = execution.tool_input.get("path")
            if path:
                summary["path"] = path
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
            for field_name in ["content_mode", "read_coverage", "content_truncated", "structure_summary"]:
                if field_name in output:
                    summary[field_name] = output[field_name]
            summary.update(
                self._build_read_file_excerpt_summary(
                    execution=execution,
                    recent_executions=recent_executions or [],
                )
            )
        if execution.tool_name == "read_file_range":
            for field_name in [
                "line_count",
                "content_mode",
                "content_excerpt",
                "read_coverage",
                "excerpt_line_start",
                "excerpt_line_end",
                "content_truncated",
            ]:
                if field_name in output:
                    summary[field_name] = output[field_name]
        if execution.tool_name == "apply_patch" and output.get("error") == "old_text_not_found":
            summary["failed_old_text_excerpt"] = self._truncate_model_feedback_text(
                execution.tool_input.get("old_text"),
                limit=1200,
            )
            summary["new_text_excerpt"] = self._truncate_model_feedback_text(
                execution.tool_input.get("new_text"),
                limit=1200,
            )
        if execution.tool_name == "replace_lines":
            for field_name in [
                "action",
                "start_line",
                "end_line",
                "line_count_before",
                "line_count_after",
                "bytes_written",
            ]:
                if field_name in output:
                    summary[field_name] = output[field_name]
        return summary

    def _build_read_file_excerpt_summary(
        self,
        execution: ToolExecution,
        recent_executions: list[ToolExecution],
    ) -> dict[str, Any]:
        """为 read_file 生成短源码片段，优先覆盖 old_text_not_found 的目标位置。"""
        content_mode = execution.tool_output.get("content_mode", "")
        if content_mode == "structure_summary" and "content" not in execution.tool_output:
            return {
                "content_excerpt": "",
                "excerpt_line_start": 0,
                "excerpt_line_end": 0,
                "excerpt_reason": "large_file_structure_summary",
                "content_mode": "structure_summary",
                "content_truncated": True,
                "line_count": execution.tool_output.get("line_count", 0),
                "structure_summary": execution.tool_output.get("structure_summary", []),
            }

        content = str(execution.tool_output.get("content", ""))
        lines = content.splitlines()
        if not lines:
            return {
                "content_excerpt": "",
                "excerpt_line_start": 0,
                "excerpt_line_end": 0,
                "excerpt_reason": "empty_file",
                "read_coverage": "0-0",
                "content_mode": "full",
                "content_truncated": False,
            }

        related_patch = self._find_related_old_text_failure(
            read_execution=execution,
            recent_executions=recent_executions,
        )
        if related_patch:
            old_text = str(related_patch.tool_input.get("old_text") or "")
            best_index = self._find_best_excerpt_line_index(lines=lines, needle=old_text)
            start_index = max(best_index - 5, 0)
            excerpt_reason = "old_text_not_found_candidate"
        elif len(lines) <= FULL_READ_FILE_MAX_LINES or len(content) <= FULL_READ_FILE_MAX_CHARS:
            return {
                "content_excerpt": content,
                "excerpt_line_start": 1,
                "excerpt_line_end": len(lines),
                "excerpt_reason": "full_file",
                "read_coverage": f"1-{len(lines)}",
                "content_mode": "full",
                "content_truncated": False,
            }
        else:
            start_index = 0
            excerpt_reason = "leading_excerpt"

        excerpt_lines = lines[start_index : start_index + 20]
        excerpt_text = "\n".join(excerpt_lines)
        while len(excerpt_text) > 4000 and len(excerpt_lines) > 1:
            excerpt_lines = excerpt_lines[:-1]
            excerpt_text = "\n".join(excerpt_lines)
        if len(excerpt_text) > 4000:
            excerpt_text = excerpt_text[:4000] + "...[truncated]"
        end_index = start_index + len(excerpt_lines)
        return {
            "content_excerpt": excerpt_text,
            "excerpt_line_start": start_index + 1,
            "excerpt_line_end": end_index,
            "excerpt_reason": excerpt_reason,
        }

    def _find_related_old_text_failure(
        self,
        read_execution: ToolExecution,
        recent_executions: list[ToolExecution],
    ) -> ToolExecution | None:
        """寻找同一文件上的 old_text_not_found，作为 read_file 片段选择依据。"""
        read_path = read_execution.tool_input.get("path")
        if not read_path:
            return None
        for execution in reversed(recent_executions):
            if execution.tool_name != "apply_patch":
                continue
            if execution.tool_output.get("error") != "old_text_not_found":
                continue
            if execution.tool_input.get("path") == read_path:
                return execution
        return None

    def _find_best_excerpt_line_index(self, lines: list[str], needle: str) -> int:
        """用简单 token 重叠找到最可能对应失败 old_text 的源码行。"""
        needle_tokens = self._tokenize_feedback_text(needle)
        if not needle_tokens:
            return 0
        best_index = 0
        best_score = -1
        for index, line in enumerate(lines):
            line_tokens = self._tokenize_feedback_text(line)
            score = len(needle_tokens & line_tokens)
            if score > best_score:
                best_index = index
                best_score = score
        return best_index

    def _tokenize_feedback_text(self, text: str) -> set[str]:
        """把失败文本压成粗粒度 token，用于选择候选源码片段。"""
        return {
            token.lower()
            for token in re.split(r"[^A-Za-z0-9_\u4e00-\u9fff]+", text)
            if token.strip()
        }

    def _truncate_model_feedback_text(self, value: Any, limit: int) -> str:
        """截断进入模型反馈的长文本，避免 trace 和 prompt 被大块内容淹没。"""
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "...[truncated]"

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
        """把状态分发到独立处理器，同时保持 trace 载荷兼容。"""
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
        if state is AgentState.REFLECT:
            return self._run_reflect(runtime_state=runtime_state)
        if state is AgentState.VERIFY:
            return self._run_verify(
                settings=settings,
                runtime_state=runtime_state,
                config_data=config_data,
                tool_runner=tool_runner,
            )
        if state is AgentState.FINALIZE:
            return self._run_finalize(runtime_state=runtime_state)
        raise ValueError(f"Unsupported agent state: {state}")

    def _run_ingest(
        self,
        settings: RunSettings,
        runtime_state: RuntimeState,
        config_data: dict[str, Any],
    ) -> dict[str, Any]:
        """在分析开始前记录本次运行的真实输入。"""
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
        """为模型规划构建 memory 和上下文证据。"""
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
        """请求模型生成下一步工具计划，并记录上一轮事实反馈摘要。"""
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
        self._accumulate_token_usage(runtime_state=runtime_state, model_decision=runtime_state.model_decision)
        self.trace_writer.write_event(
            TraceEvent(
                event_type="model_raw_response",
                payload={
                    "provider": runtime_state.model_decision.provider,
                    "model_name": runtime_state.model_decision.model_name,
                    "iteration": runtime_state.current_iteration,
                    "content": runtime_state.model_decision.raw_response_content,
                    "content_length": len(runtime_state.model_decision.raw_response_content),
                    "parsed_ok": True,
                    "token_usage": runtime_state.model_decision.token_usage.to_dict(),
                },
            )
        )
        if runtime_state.model_decision.normalization_notes:
            self.trace_writer.write_event(
                TraceEvent(
                    event_type="model_response_normalized",
                    payload={
                        "provider": runtime_state.model_decision.provider,
                        "model_name": runtime_state.model_decision.model_name,
                        "iteration": runtime_state.current_iteration,
                        "notes": list(runtime_state.model_decision.normalization_notes),
                    },
                )
            )
        runtime_state.cross_round_plan = list(runtime_state.model_decision.cross_round_plan)
        runtime_state.cross_round_plan_history.append(list(runtime_state.model_decision.cross_round_plan))
        runtime_state.model_decisions.append(runtime_state.model_decision)
        self.trace_writer.write_event(
            TraceEvent(
                event_type="model_decision",
                payload={
                    **runtime_state.model_decision.to_dict(),
                    "iteration": runtime_state.current_iteration,
                    "has_reflect_feedback": bool(reflect_feedback_summary),
                    "reflect_feedback_summary": reflect_feedback_summary,
                    "run_token_usage": dict(runtime_state.token_usage),
                },
            )
        )
        return {
            "summary": runtime_state.model_decision.summary,
            "planned_actions": list(runtime_state.model_decision.planned_actions),
            "cross_round_plan": list(runtime_state.model_decision.cross_round_plan),
            "rationale": runtime_state.model_decision.rationale,
            "provider": runtime_state.model_decision.provider,
            "model_name": runtime_state.model_decision.model_name,
            "token_usage": runtime_state.model_decision.token_usage.to_dict(),
            "run_token_usage": dict(runtime_state.token_usage),
        }

    def _run_act(self, runtime_state: RuntimeState, tool_runner: CoreToolRunner) -> dict[str, Any]:
        """执行模型为当前轮规划的工具调用。"""
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

    def _run_reflect(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """为下一轮 plan 生成事实型反馈。"""
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
        tool_runner: CoreToolRunner,
    ) -> dict[str, Any]:
        """进入 verify 时先生成系统 diff 快照，再执行任务验证。"""
        verification_diff_snapshot = tool_runner.git_diff()
        self.trace_writer.write_event(
            TraceEvent(
                event_type="verification_diff_snapshot",
                payload={
                    **verification_diff_snapshot.to_trace_payload(),
                    "iteration": runtime_state.current_iteration,
                },
            )
        )
        verification_result = build_phase_4_verification(
            settings=settings,
            tool_executions=[verification_diff_snapshot],
        )
        verification_result.details["verification_diff_snapshot"] = verification_diff_snapshot.tool_output
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
        """在写入 run_finished 前记录最终运行证据。"""
        verification_passed = bool(runtime_state.verification_result and runtime_state.verification_result.passed)
        payload = {
            "summary": "Final runtime evidence captured before run finish.",
            "final_status": "success" if verification_passed else "incomplete",
            "verification_passed": verification_passed,
            "changed_files": list(runtime_state.changed_files),
            "failed_tool_count": runtime_state.failed_tool_count,
            "reflect_count": runtime_state.reflect_count,
            "reflect_trigger_reasons": list(runtime_state.reflect_trigger_reasons),
            "iteration_count": runtime_state.iteration_count,
            "max_steps": runtime_state.max_steps,
            "tool_execution_count": len(runtime_state.tool_executions),
            "model_decision_count": len(runtime_state.model_decisions),
            "cross_round_plan": list(runtime_state.cross_round_plan),
            "completed_states_before_finalize": list(runtime_state.completed_states),
            "token_usage": dict(runtime_state.token_usage),
        }
        self.trace_writer.write_event(TraceEvent(event_type="finalize_summary", payload=payload))
        return payload

    def _accumulate_token_usage(self, runtime_state: RuntimeState, model_decision: ModelDecision) -> None:
        """把单次模型 usage 聚合到整次 run。"""
        runtime_state.token_usage["request_count"] += 1
        if not model_decision.token_usage.available:
            runtime_state.token_usage["complete"] = False
            runtime_state.token_usage["missing_usage_count"] += 1
            return

        runtime_state.token_usage["prompt_tokens"] += model_decision.token_usage.prompt_tokens
        runtime_state.token_usage["completion_tokens"] += model_decision.token_usage.completion_tokens
        runtime_state.token_usage["total_tokens"] += model_decision.token_usage.total_tokens

    def _run_planned_tools(
        self,
        tool_runner: CoreToolRunner,
        model_decision: ModelDecision,
    ) -> list[ToolExecution]:
        """执行决策层产出的工具计划；工具计划必须来自模型决策。"""
        executions: list[ToolExecution] = []
        planned_tool_calls = [
            (item.tool_name, self._normalize_tool_input(tool_name=item.tool_name, tool_input=item.tool_input))
            for item in model_decision.tool_calls
        ]

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

    def _normalize_tool_input(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """兼容常见参数别名，并拒绝结构化工具 schema 未声明的字段。"""
        if tool_name not in TOOL_SCHEMAS:
            raise ModelResponseError(f"未知工具：{tool_name}")
        normalized = dict(tool_input)
        aliases = TOOL_SCHEMAS[tool_name].get("accepted_aliases", {})
        if isinstance(aliases, dict):
            for alias, canonical in aliases.items():
                if alias in normalized and canonical not in normalized:
                    normalized[canonical] = normalized.pop(alias)
        allowed_fields = set(TOOL_SCHEMAS[tool_name].get("required", [])) | set(
            TOOL_SCHEMAS[tool_name].get("optional", [])
        )
        extra_fields = sorted(field for field in normalized if field not in allowed_fields)
        if extra_fields:
            raise ModelResponseError(
                f"模型工具计划给 {tool_name} 传入了未声明字段：{', '.join(extra_fields)}。"
            )
        missing_fields = [
            field_name
            for field_name in TOOL_SCHEMAS[tool_name].get("required", [])
            if field_name not in normalized
        ]
        if missing_fields:
            raise ModelResponseError(
                f"模型工具计划给 {tool_name} 缺少必填字段：{', '.join(missing_fields)}。"
            )
        self._validate_tool_input_types(tool_name=tool_name, tool_input=normalized)
        return normalized

    def _validate_tool_input_types(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """在 act 前兜底校验工具入参类型，避免非法值打到工具层。"""
        properties = TOOL_SCHEMAS[tool_name].get("properties", {})
        if not isinstance(properties, dict):
            return
        for field_name, value in tool_input.items():
            property_schema = properties.get(field_name, {})
            if not isinstance(property_schema, dict):
                continue
            expected_type = property_schema.get("type")
            if self._matches_tool_schema_type(
                value=value,
                expected_type=expected_type,
                property_schema=property_schema,
            ):
                continue
            raise ModelResponseError(
                (
                    f"模型工具计划给 {tool_name}.{field_name} 传入了错误类型："
                    f"expected={self._format_expected_type(expected_type)} actual={type(value).__name__}。"
                ),
                details={
                    "field_path": f"tool_input.{field_name}",
                    "tool_name": tool_name,
                    "expected_type": self._format_expected_type(expected_type),
                    "actual_type": type(value).__name__,
                },
            )

    def _matches_tool_schema_type(self, value: Any, expected_type: Any, property_schema: dict[str, Any]) -> bool:
        """支持当前工具 schema 需要的最小 JSON 类型集合。"""
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        for item_type in expected_types:
            if item_type == "string" and isinstance(value, str):
                return True
            if item_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
                return True
            if item_type == "null" and value is None:
                return True
            if item_type == "array" and isinstance(value, list):
                item_schema = property_schema.get("items", {})
                if not isinstance(item_schema, dict) or "type" not in item_schema:
                    return True
                return all(
                    self._matches_tool_schema_type(
                        value=array_item,
                        expected_type=item_schema.get("type"),
                        property_schema=item_schema,
                    )
                    for array_item in value
                )
        return False

    def _format_expected_type(self, expected_type: Any) -> str:
        """把 schema 类型整理成稳定错误摘要。"""
        if isinstance(expected_type, list):
            return "|".join(str(item) for item in expected_type)
        return str(expected_type)

    def _current_tool_iteration(self) -> int:
        """返回当前工具调用所属轮次；工具 runner 本身不持有 runtime_state。"""
        return getattr(self, "_active_iteration", 0)

    def _build_tool_fact_observation(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """把本轮工具结果压缩成事实观察，不替模型判断是否有效。"""
        changed_files: list[str] = []
        successful_tools: list[str] = []
        failed_tools: list[dict[str, Any]] = []
        failed_execution_ids: set[int] = set()
        edit_attempted = False
        latest_git_diff_changed_file_count: int | None = None

        for index, execution in enumerate(runtime_state.recent_tool_executions):
            tool_output = execution.tool_output
            ok = tool_output.get("ok")

            if ok is True:
                successful_tools.append(execution.tool_name)

            if execution.tool_name in {"apply_patch", "replace_lines"}:
                edit_attempted = True

            if execution.tool_name == "git_diff":
                changed_file_count = int(tool_output.get("changed_file_count") or 0)
                latest_git_diff_changed_file_count = changed_file_count
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
        failed_tool_count = len(failed_execution_ids)
        signals = self._build_reflect_signals(
            edit_attempted=edit_attempted,
            latest_git_diff_changed_file_count=latest_git_diff_changed_file_count,
            failed_tool_count=failed_tool_count,
        )
        observation_summary = self._build_observation_summary(
            changed_files=changed_files,
            failed_tool_count=failed_tool_count,
            successful_tools=successful_tools,
            signals=signals,
        )

        runtime_state.changed_files = changed_files
        runtime_state.failed_tool_count = failed_tool_count
        runtime_state.observation_summary = observation_summary

        return {
            "summary": observation_summary,
            "iteration": runtime_state.current_iteration,
            "changed_files": changed_files,
            "successful_tools": successful_tools,
            "failed_tools": failed_tools,
            "failed_tool_count": failed_tool_count,
            "edit_attempted": edit_attempted,
            "latest_git_diff_changed_file_count": latest_git_diff_changed_file_count,
            "signals": signals,
        }

    def _build_reflect_signals(
        self,
        edit_attempted: bool,
        latest_git_diff_changed_file_count: int | None,
        failed_tool_count: int,
    ) -> list[str]:
        """生成轻量信号，只描述事实形态，不做进展好坏判断。"""
        signals: list[str] = []
        if edit_attempted and latest_git_diff_changed_file_count == 0:
            signals.append("no_diff_after_edit_attempt")
        if failed_tool_count > 0:
            signals.append("failed_tool_observed")
        return signals

    def _build_observation_summary(
        self,
        changed_files: list[str],
        failed_tool_count: int,
        successful_tools: list[str],
        signals: list[str],
    ) -> str:
        """生成报告和 state_result 共用的事实观察摘要。"""
        signal_text = "、".join(signals) if signals else "无"
        return (
            f"本轮工具事实：变更文件 {len(changed_files)} 个，"
            f"成功工具 {len(successful_tools)} 个，失败工具 {failed_tool_count} 个，"
            f"signals={signal_text}。"
        )

    def _build_verification_failure_details(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """从最近一次失败验证结果中提取稳定细节。"""
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
        """按稳定规则族分类失败的验证检查，用于 stop reason 细节。"""
        rule_types: list[str] = []
        for check in failing_checks:
            name = str(check.get("name", "")).strip()
            if name.startswith("verify_command_"):
                continue
            if not name:
                continue
            # 当前 check 尚未保存规则类型，先保留稳定的通用分类。
            rule_types.append("verify_rule")
        return rule_types

    def _build_reflect_feedback(self, runtime_state: RuntimeState) -> dict[str, Any]:
        """为下一轮 plan 生成事实型 reflect 反馈。"""
        self._update_file_context_cache(runtime_state=runtime_state)
        observation = self._build_tool_fact_observation(runtime_state=runtime_state)
        failed_tool_summaries = [
            self._summarize_tool_execution(
                execution=execution,
                recent_executions=runtime_state.recent_tool_executions,
            )
            for execution in runtime_state.recent_tool_executions
            if execution.tool_output.get("ok") is False
            or (execution.tool_name == "run_command" and execution.tool_output.get("returncode", 0) != 0)
        ]
        recent_tool_results = [
            self._summarize_tool_execution(
                execution=execution,
                recent_executions=runtime_state.recent_tool_executions,
            )
            for execution in runtime_state.recent_tool_executions
        ]

        return {
            "summary": "已生成事实型 reflect 反馈。",
            "iteration": runtime_state.current_iteration,
            "trigger": runtime_state.reflect_trigger_reason or "unknown",
            "observation": observation,
            "signals": list(observation.get("signals", [])),
            "failed_tools": failed_tool_summaries,
            "recent_tool_results": recent_tool_results,
            "file_context_cache": runtime_state.file_context_cache,
            "verification": {},
        }

    def _update_file_context_cache(self, runtime_state: RuntimeState) -> None:
        """累计同一文件最近五次读取片段，供下一轮模型做跨轮定位。"""
        for execution in runtime_state.recent_tool_executions:
            snippet = self._build_file_context_snippet(execution=execution)
            if not snippet:
                continue
            path = snippet["path"]
            cache_entry = runtime_state.file_context_cache.setdefault(
                path,
                {
                    "path": path,
                    "line_count": snippet.get("line_count", 0),
                    "snippets": [],
                },
            )
            if snippet.get("line_count"):
                cache_entry["line_count"] = snippet["line_count"]
            snippets = list(cache_entry.get("snippets", []))
            snippets.append({key: value for key, value in snippet.items() if key != "path"})
            cache_entry["snippets"] = snippets[-5:]
            cache_entry["covered_ranges"] = [
                item.get("read_coverage", "")
                for item in cache_entry["snippets"]
                if item.get("read_coverage")
            ]

    def _build_file_context_snippet(self, execution: ToolExecution) -> dict[str, Any]:
        """把读取类工具结果转成可累计的文件片段。"""
        if execution.tool_name not in {"read_file", "read_file_range"}:
            return {}
        if execution.tool_output.get("ok") is not True:
            return {}
        path = execution.tool_input.get("path")
        if not path:
            return {}
        output = execution.tool_output
        content = output.get("content") if execution.tool_name == "read_file" else output.get("content_excerpt")
        if content is None:
            content = output.get("content_excerpt", "")
        snippet: dict[str, Any] = {
            "path": path,
            "tool_name": execution.tool_name,
            "content_mode": output.get("content_mode", ""),
            "read_coverage": output.get("read_coverage", ""),
            "excerpt_line_start": output.get("excerpt_line_start", 0),
            "excerpt_line_end": output.get("excerpt_line_end", 0),
            "line_count": output.get("line_count", 0),
            "content_excerpt": self._truncate_model_feedback_text(content, limit=4000),
        }
        if output.get("content_mode") == "structure_summary" and "content" not in output:
            snippet["content_excerpt"] = ""
            snippet["read_coverage"] = ""
            snippet["excerpt_line_start"] = 0
            snippet["excerpt_line_end"] = 0
        if output.get("content_truncated") is not None:
            snippet["content_truncated"] = output.get("content_truncated")
        if output.get("structure_summary"):
            snippet["structure_summary"] = output.get("structure_summary")
        return snippet

    def _has_old_text_not_found_failure(self, failed_tool_summaries: list[dict[str, Any]]) -> bool:
        """判断失败工具摘要里是否存在 old_text_not_found。"""
        return any(
            summary.get("tool_name") == "apply_patch"
            and summary.get("error") == "old_text_not_found"
            for summary in failed_tool_summaries
        )
