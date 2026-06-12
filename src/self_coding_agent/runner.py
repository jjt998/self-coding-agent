from __future__ import annotations

from pathlib import Path

from .config import RunSettings
from .trace import TraceEvent, TraceWriter


def execute_initial_run(settings: RunSettings, config_data: dict) -> Path:
    # Phase 1 先只负责把一次 run 的基础目录和元数据初始化出来，不在这里引入真实 agent loop。
    run_dir = Path(settings.output_root) / settings.run_id
    trace_writer = TraceWriter(run_dir=run_dir)

    snapshot = settings.to_dict()
    snapshot["config"] = config_data
    trace_writer.initialize(snapshot)

    trace_writer.write_event(
        TraceEvent(
            event_type="run_initialized",
            payload={
                "run_id": settings.run_id,
                "task_type": settings.task_type,
                "repo_root": settings.repo_root,
            },
        )
    )
    # 这里立刻补一条状态迁移事件，是为了让后续 Phase 2 接状态机时不用再改 trace 事件习惯。
    trace_writer.write_event(
        TraceEvent(
            event_type="state_transition",
            payload={
                "from_state": "bootstrap",
                "to_state": "initialized",
                "reason": "phase_1_scaffold",
            },
        )
    )

    return run_dir
