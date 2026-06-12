from __future__ import annotations

from pathlib import Path

from config import RunSettings
from loop import LoopOrchestrator, RuntimeState
from trace import TraceEvent, TraceWriter


def execute_initial_run(settings: RunSettings, config_data: dict) -> Path:
    """初始化单次 run，并执行最小 stub 状态机流程。"""
    # 这里继续沿用 Phase 1 的 run 初始化逻辑，再把 Phase 2 的最小 loop 接在后面。
    run_dir = Path(settings.output_root) / settings.run_id
    trace_writer = TraceWriter(run_dir=run_dir)

    snapshot = settings.to_dict()
    snapshot["config"] = config_data
    trace_writer.initialize(snapshot)

    trace_writer.write_event(
        TraceEvent(
            event_type="run_started",
            payload={
                "run_id": settings.run_id,
                "task_type": settings.task_type,
                "repo_root": settings.repo_root,
            },
        )
    )
    runtime_state = LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=config_data)
    trace_writer.write_report(_build_phase_2_report(settings=settings, runtime_state=runtime_state))

    return run_dir


def _build_phase_2_report(settings: RunSettings, runtime_state: RuntimeState) -> str:
    """根据 Phase 2 运行结果生成最小 Markdown 报告。"""
    stop_reason = runtime_state.stop_reason
    stop_reason_text = stop_reason.message if stop_reason else "未设置"
    stop_reason_code = stop_reason.code.value if stop_reason else "unknown"
    completed_states = " -> ".join(runtime_state.completed_states)
    reflect_status = "已触发" if runtime_state.reflect_triggered else "未触发"

    return (
        f"# 运行报告\n\n"
        f"- Run ID：`{settings.run_id}`\n"
        f"- 任务类型：`{settings.task_type}`\n"
        f"- 任务内容：{settings.task}\n\n"
        f"## 当前状态\n\n"
        f"`{runtime_state.current_state}`\n\n"
        f"## 状态流\n\n"
        f"{completed_states}\n\n"
        f"## 运行摘要\n\n"
        f"- 总步数：`{runtime_state.step_count}`\n"
        f"- reflect：{reflect_status}\n"
        f"- stop reason：`{stop_reason_code}`\n"
        f"- stop reason 说明：{stop_reason_text}\n"
    )
