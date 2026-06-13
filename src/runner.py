from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import RunSettings
from loop import LoopOrchestrator, RuntimeState
from memory import LongTermMemoryEntry, LongTermMemoryStore
from trace import TraceEvent, TraceWriter


@dataclass(slots=True)
class MemoryWriteResult:
    """记录这次 run 是否写入了长期 memory。"""

    written: bool
    store_path: str
    reason: str


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
    memory_write_result = _write_long_term_memory_if_needed(settings=settings, runtime_state=runtime_state)
    trace_writer.write_event(
        TraceEvent(
            event_type="memory_write_result",
            payload={
                "written": memory_write_result.written,
                "store_path": memory_write_result.store_path,
                "reason": memory_write_result.reason,
            },
        )
    )
    trace_writer.write_report(
        _build_phase_4_report(
            settings=settings,
            runtime_state=runtime_state,
            memory_write_result=memory_write_result,
        )
    )

    return run_dir


def _build_phase_4_report(
    settings: RunSettings,
    runtime_state: RuntimeState,
    memory_write_result: MemoryWriteResult,
) -> str:
    """把状态流、工具摘要和验证结果整理成当前阶段可读报告。"""
    stop_reason = runtime_state.stop_reason
    stop_reason_text = stop_reason.message if stop_reason else "未设置"
    stop_reason_code = stop_reason.code.value if stop_reason else "unknown"
    completed_states = " -> ".join(runtime_state.completed_states)
    reflect_status = "已触发" if runtime_state.reflect_triggered else "未触发"
    verification_result = runtime_state.verification_result
    verification_status = "通过" if verification_result and verification_result.passed else "未通过"
    verification_summary = verification_result.summary if verification_result else "尚未生成验证结果。"
    context_snapshot = runtime_state.context_snapshot

    tool_lines = []
    for execution in runtime_state.tool_executions:
        tool_ok = execution.tool_output.get("ok")
        tool_status = "成功" if tool_ok is True else "已记录"
        tool_lines.append(f"- `{execution.tool_name}`：{tool_status}")
    tool_summary = "\n".join(tool_lines) if tool_lines else "- 本次 run 未执行工具。"

    verification_lines = []
    if verification_result:
        for check in verification_result.checks:
            check_status = "通过" if check.passed else "未通过"
            verification_lines.append(f"- {check.name}：{check_status}。{check.detail}")
    verification_details = "\n".join(verification_lines) if verification_lines else "- 暂无验证检查项。"
    memory_write_status = "已写入" if memory_write_result.written else "未写入"

    context_lines = []
    if context_snapshot:
        context_lines.append(f"- 任务关键词：`{', '.join(context_snapshot.task_context.keywords)}`")
        context_lines.append(f"- 召回倾向：{context_snapshot.repo_context.recall_strategy}")
        context_lines.append(
            f"- 扫描到的文本文件数：`{context_snapshot.repo_context.candidate_file_count}`"
        )
        context_lines.append(
            f"- 选中文件数：`{context_snapshot.repo_context.selected_file_count}`，"
            f"保留总行数：`{context_snapshot.repo_context.total_selected_lines}`，"
            f"原始总行数：`{context_snapshot.repo_context.total_original_lines}`，"
            f"发生裁剪的文件数：`{context_snapshot.repo_context.clipped_file_count}`"
        )
        if context_snapshot.repo_context.selected_files:
            for file_context in context_snapshot.repo_context.selected_files:
                clip_text = "是" if file_context.was_clipped else "否"
                context_lines.append(
                    f"- `{file_context.path}`：以 `{file_context.injection_mode}` 方式放入上下文，"
                    f"保留 `{file_context.included_line_count}` 行，总行数 `{file_context.total_line_count}`，"
                    f"是否裁剪：{clip_text}。原因：{file_context.reason}"
                )
        else:
            context_lines.append("- 本次没有选中文件进入上下文。")
        memory_status = "已启用" if context_snapshot.memory_context.enabled else "未启用"
        context_lines.append(
            f"- memory：{memory_status}。来源：`{context_snapshot.memory_context.source}`。"
            f"查询词：`{context_snapshot.memory_context.query or '无'}`。"
            f"命中条数：`{len(context_snapshot.memory_context.matched_entries)}`"
        )
    context_summary = "\n".join(context_lines) if context_lines else "- 尚未生成上下文快照。"

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
        f"\n## 上下文摘要\n\n"
        f"{context_summary}\n"
        f"\n## 工具调用摘要\n\n"
        f"{tool_summary}\n"
        f"\n## 验证结果\n\n"
        f"- 验证状态：{verification_status}\n"
        f"- 验证说明：{verification_summary}\n"
        f"\n{verification_details}\n"
        f"\n## Memory 写入\n\n"
        f"- 写入状态：{memory_write_status}\n"
        f"- 说明：{memory_write_result.reason}\n"
        f"- 存储位置：`{memory_write_result.store_path}`\n"
    )


def _write_long_term_memory_if_needed(settings: RunSettings, runtime_state: RuntimeState) -> MemoryWriteResult:
    """只有验证通过时才写入长期 memory，先把最小写入口固定下来。"""
    verification_result = runtime_state.verification_result
    store = LongTermMemoryStore(repo_root=settings.repo_root)
    if not verification_result or not verification_result.passed:
        return MemoryWriteResult(
            written=False,
            store_path=str(store.store_path),
            reason="本次 run 未通过验证，按当前规则不写入长期 memory。",
        )

    context_snapshot = runtime_state.context_snapshot
    selected_paths = []
    if context_snapshot:
        selected_paths = [file_context.path for file_context in context_snapshot.repo_context.selected_files]

    entry = LongTermMemoryEntry(
        run_id=settings.run_id,
        task=settings.task,
        task_type=settings.task_type,
        summary=verification_result.summary,
        tags=[settings.task_type, "verified", "mvp"],
        evidence={
            "stop_reason": runtime_state.stop_reason.to_dict() if runtime_state.stop_reason else {},
            "selected_context_files": selected_paths,
            "tool_count": len(runtime_state.tool_executions),
            "verification_checks": [check.to_dict() for check in verification_result.checks],
        },
    )
    store_path = store.append_entry(entry)
    return MemoryWriteResult(
        written=True,
        store_path=str(store_path),
        reason="本次 run 已验证通过，已追加写入长期 memory。",
    )
