from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile

from config import RunSettings
from loop import LoopOrchestrator, RuntimeState, StopReason, StopReasonCode
from memory import LongTermMemoryEntry, LongTermMemoryStore, _extract_keywords, _normalize_file_paths
from trace import TraceEvent, TraceWriter


@dataclass(slots=True)
class MemoryWriteResult:
    """记录这次 run 是否写入了长期 memory。"""

    written: bool
    store_path: str
    reason: str


@dataclass(slots=True)
class SandboxCleanupResult:
    """记录本次 run 结束后 sandbox 是保留还是清理。"""

    attempted: bool
    kept: bool
    sandbox_dir: str
    retention_policy: str
    reason: str


@dataclass(slots=True)
class SetupCommandResult:
    """记录任务 setup 命令执行结果，供 setup_failed stop reason 复用。"""

    index: int
    command: list[str]
    cwd: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def execute_initial_run(settings: RunSettings, config_data: dict) -> Path:
    """初始化单次 run，并执行最小 stub 状态机流程。"""
    # 这里继续沿用 Phase 1 的 run 初始化逻辑，再把 Phase 2 的最小 loop 接在后面。
    run_dir = Path(settings.output_root) / settings.run_id
    _prepare_execution_workspace(settings=settings, run_dir=run_dir)
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
                "source_repo_root": settings.source_repo_root,
                "workspace_mode": settings.workspace_mode,
            },
        )
    )
    trace_writer.write_event(
        TraceEvent(
            event_type="workspace_prepared",
            payload={
                "workspace_mode": settings.workspace_mode,
                "source_repo_root": settings.source_repo_root,
                "execution_repo_root": settings.repo_root,
                "sandbox_dir": settings.sandbox_dir,
            },
        )
    )
    setup_results = _run_task_setup_commands(settings=settings, trace_writer=trace_writer)
    if any(not result.ok for result in setup_results):
        runtime_state = _build_setup_failed_runtime_state(
            settings=settings,
            setup_results=setup_results,
            trace_writer=trace_writer,
        )
    else:
        runtime_state = LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=config_data)
    memory_entry_written_payload = None
    if runtime_state.verification_result and runtime_state.verification_result.passed:
        memory_entry_written_payload = _build_memory_entry_written_payload(
            settings=settings,
            runtime_state=runtime_state,
        )
    memory_write_result = _write_long_term_memory_if_needed(settings=settings, runtime_state=runtime_state)
    if memory_entry_written_payload:
        trace_writer.write_event(
            TraceEvent(
                event_type="memory_entry_written",
                payload=memory_entry_written_payload,
            )
        )
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
    sandbox_cleanup_result = _cleanup_sandbox_if_needed(
        settings=settings,
        runtime_state=runtime_state,
        trace_writer=trace_writer,
    )
    trace_writer.write_report(
        _build_phase_4_report(
            settings=settings,
            runtime_state=runtime_state,
            memory_write_result=memory_write_result,
            sandbox_cleanup_result=sandbox_cleanup_result,
        )
    )

    return run_dir


def _prepare_execution_workspace(settings: RunSettings, run_dir: Path) -> None:
    """按运行模式准备真正执行任务的工作目录。"""
    source_repo_root = Path(settings.source_repo_root or settings.repo_root).resolve()
    settings.source_repo_root = str(source_repo_root)
    settings.repo_root = str(source_repo_root)
    settings.sandbox_dir = ""

    if settings.workspace_mode != "per_task_sandbox":
        return

    sandbox_root = Path(tempfile.mkdtemp(prefix=f"{settings.run_id}-self-coding-agent-"))
    sandbox_repo_root = sandbox_root / "repo"
    shutil.copytree(
        source_repo_root,
        sandbox_repo_root,
        ignore=_build_sandbox_ignore(
            source_repo_root=source_repo_root,
            output_root=Path(settings.output_root).resolve(),
        ),
    )
    settings.repo_root = str(sandbox_repo_root.resolve())
    settings.sandbox_dir = str(sandbox_root.resolve())


def _build_sandbox_ignore(source_repo_root: Path, output_root: Path):
    """生成 sandbox 复制时的忽略规则，避免把运行产物和缓存目录再卷进去。"""
    ignored_names = {
        ".git",
        ".agent_sandboxes",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
    }
    try:
        relative_output_root = output_root.relative_to(source_repo_root)
    except ValueError:
        relative_output_root = None
    if relative_output_root and relative_output_root.parts:
        # 这里忽略 output_root 在仓库内的顶层目录名，避免复制 sandbox 时把 runs 再递归带进去。
        ignored_names.add(relative_output_root.parts[0])

    def _ignore(_current_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored_names}

    return _ignore


def _run_task_setup_commands(settings: RunSettings, trace_writer: TraceWriter) -> list[SetupCommandResult]:
    """在真正进入 loop 前先执行任务自带的准备命令，让 sandbox 输入态可复现。"""
    setup_results: list[SetupCommandResult] = []
    for index, command in enumerate(settings.setup_commands, start=1):
        trace_writer.write_event(
            TraceEvent(
                event_type="task_setup_started",
                payload={
                    "index": index,
                    "command": list(command),
                    "cwd": settings.repo_root,
                },
            )
        )
        completed = subprocess.run(
            command,
            cwd=settings.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        setup_result = SetupCommandResult(
            index=index,
            command=list(command),
            cwd=settings.repo_root,
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        setup_results.append(setup_result)
        trace_writer.write_event(
            TraceEvent(
                event_type="task_setup_result",
                payload=asdict(setup_result),
            )
        )
    return setup_results


def _build_setup_failed_runtime_state(
    settings: RunSettings,
    setup_results: list[SetupCommandResult],
    trace_writer: TraceWriter,
) -> RuntimeState:
    """在 setup 失败时构造最小 runtime_state，并写入结构化 run_finished。"""
    runtime_state = RuntimeState(task=settings.task, task_type=settings.task_type)
    failed_setups = [result for result in setup_results if not result.ok]
    runtime_state.stop_reason = StopReason(
        code=StopReasonCode.SETUP_FAILED,
        message="任务准备失败，run 已停止。",
        details={
            "setup_command_count": len(setup_results),
            "failed_setup_commands": [asdict(result) for result in failed_setups],
            "setup_results": [asdict(result) for result in setup_results],
        },
    )
    trace_writer.write_event(
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


def _cleanup_sandbox_if_needed(
    settings: RunSettings,
    runtime_state: RuntimeState,
    trace_writer: TraceWriter,
) -> SandboxCleanupResult:
    """按保留策略决定是否删除本次 run 的 sandbox，并把结果写进 trace。"""
    if settings.workspace_mode != "per_task_sandbox" or not settings.sandbox_dir:
        result = SandboxCleanupResult(
            attempted=False,
            kept=False,
            sandbox_dir=settings.sandbox_dir,
            retention_policy=settings.sandbox_retention,
            reason="当前运行未使用 per-task sandbox，无需清理。",
        )
        trace_writer.write_event(TraceEvent(event_type="sandbox_cleanup_result", payload=asdict(result)))
        return result

    verification_passed = bool(runtime_state.verification_result and runtime_state.verification_result.passed)
    should_keep, reason = _decide_sandbox_retention(
        retention_policy=settings.sandbox_retention,
        verification_passed=verification_passed,
    )
    if should_keep:
        result = SandboxCleanupResult(
            attempted=False,
            kept=True,
            sandbox_dir=settings.sandbox_dir,
            retention_policy=settings.sandbox_retention,
            reason=reason,
        )
        trace_writer.write_event(TraceEvent(event_type="sandbox_cleanup_result", payload=asdict(result)))
        return result

    sandbox_path = Path(settings.sandbox_dir)
    shutil.rmtree(sandbox_path, ignore_errors=False)
    result = SandboxCleanupResult(
        attempted=True,
        kept=False,
        sandbox_dir=settings.sandbox_dir,
        retention_policy=settings.sandbox_retention,
        reason=reason,
    )
    trace_writer.write_event(TraceEvent(event_type="sandbox_cleanup_result", payload=asdict(result)))
    return result


def _decide_sandbox_retention(retention_policy: str, verification_passed: bool) -> tuple[bool, str]:
    """根据保留策略和验证结果判断 sandbox 应保留还是删除。"""
    if retention_policy == "always_keep":
        return True, "当前策略要求始终保留 sandbox。"
    if retention_policy == "always_delete":
        return False, "当前策略要求始终删除 sandbox。"
    if verification_passed:
        return False, "当前策略为 delete_on_success，且本次验证通过。"
    return True, "当前策略为 delete_on_success，且本次验证未通过。"


def _build_phase_4_report(
    settings: RunSettings,
    runtime_state: RuntimeState,
    memory_write_result: MemoryWriteResult,
    sandbox_cleanup_result: SandboxCleanupResult,
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
    progress_status = "是" if runtime_state.progress_made else "否"
    observation_summary = runtime_state.observation_summary or "尚未生成进展观察结果。"
    changed_file_lines = [
        f"- `{path}`"
        for path in runtime_state.changed_files
    ]
    changed_files_summary = "\n".join(changed_file_lines) if changed_file_lines else "- 暂无变更文件。"

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
    sandbox_status = "已保留" if sandbox_cleanup_result.kept else "已删除"

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
        context_lines.append(
            f"- memory 明细：运行时规则 "
            f"`{len(context_snapshot.memory_context.runtime_rule_entries)}` 条，"
            f"长期 memory "
            f"`{len(context_snapshot.memory_context.long_term_entries)}` 条，"
            f"被抑制的长期 memory "
            f"`{len(context_snapshot.memory_context.suppressed_long_term_entries)}` 条，"
            f"conflict evidence "
            f"`{len(context_snapshot.memory_context.conflict_evidence)}` 条"
        )
        diagnostic_labels = context_snapshot.memory_context.diagnostic_labels
        context_lines.append(
            f"- memory 诊断标签：`{', '.join(diagnostic_labels) if diagnostic_labels else '无'}`"
        )
        if context_snapshot.memory_context.conflict_evidence:
            for item in context_snapshot.memory_context.conflict_evidence:
                severity_text = "强冲突" if item.get("severity") == "strong" else "弱提醒"
                context_lines.append(
                    f"- memory 冲突：[{severity_text}] {item['summary']}。"
                    f"任务类型：`{', '.join(item.get('task_types', [])) or '未知'}`。"
                    f"共享关键词：`{', '.join(item.get('shared_keywords', [])) or '无'}`。"
                    f"共享文件：`{', '.join(item.get('shared_file_paths', [])) or '无'}`"
                )
        if context_snapshot.memory_context.suppressed_long_term_entries:
            for item in context_snapshot.memory_context.suppressed_long_term_entries:
                context_lines.append(
                    f"- memory 注入抑制：`{item.get('title', '未命名长期 memory')}`。"
                    f"任务类型：`{item.get('task_type', '未知')}`。"
                    f"原因：`{item.get('reason', '未知')}`"
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
        f"- 最大求解轮数：`{runtime_state.max_steps}`\n"
        f"- 实际求解轮数：`{runtime_state.iteration_count}`\n"
        f"- reflect：{reflect_status}\n"
        f"- reflect 次数：`{runtime_state.reflect_count}`\n"
        f"- stop reason：`{stop_reason_code}`\n"
        f"- stop reason 说明：{stop_reason_text}\n"
        f"\n## 进展观察\n\n"
        f"- 是否观察到进展：{progress_status}\n"
        f"- 变更文件数：`{len(runtime_state.changed_files)}`\n"
        f"- 失败工具数：`{runtime_state.failed_tool_count}`\n"
        f"- 观察摘要：{observation_summary}\n"
        f"{changed_files_summary}\n"
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
        f"\n## Sandbox 清理\n\n"
        f"- 工作区模式：`{settings.workspace_mode}`\n"
        f"- 保留策略：`{settings.sandbox_retention}`\n"
        f"- 清理结果：{sandbox_status}\n"
        f"- 说明：{sandbox_cleanup_result.reason}\n"
        f"- sandbox 目录：`{sandbox_cleanup_result.sandbox_dir or '无'}`\n"
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
    normalized_selected_paths = _normalize_file_paths(selected_paths)
    task_keywords = _extract_keywords(settings.task)
    summary_keywords = _extract_keywords(verification_result.summary)

    entry = LongTermMemoryEntry(
        run_id=settings.run_id,
        task=settings.task,
        task_type=settings.task_type,
        summary=verification_result.summary,
        tags=[settings.task_type, "verified", "mvp"],
        evidence={
            "stop_reason": runtime_state.stop_reason.to_dict() if runtime_state.stop_reason else {},
            # 这里把后续检索更稳定的证据一起写下来，减少只靠自然语言摘要做匹配的歧义。
            "selected_context_files": normalized_selected_paths,
            "task_keywords": task_keywords,
            "summary_keywords": summary_keywords,
            "task_summary_excerpt": verification_result.summary[:120],
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


def _build_memory_entry_written_payload(settings: RunSettings, runtime_state: RuntimeState) -> dict:
    """整理长期 memory 写入事件明细，方便单独检查写入证据而不依赖最终 store 文件。"""
    verification_result = runtime_state.verification_result
    if not verification_result:
        return {}

    context_snapshot = runtime_state.context_snapshot
    selected_paths: list[str] = []
    if context_snapshot:
        selected_paths = [file_context.path for file_context in context_snapshot.repo_context.selected_files]

    return LongTermMemoryEntry(
        run_id=settings.run_id,
        task=settings.task,
        task_type=settings.task_type,
        summary=verification_result.summary,
        tags=[settings.task_type, "verified", "mvp"],
        evidence={
            "stop_reason": runtime_state.stop_reason.to_dict() if runtime_state.stop_reason else {},
            "selected_context_files": _normalize_file_paths(selected_paths),
            "task_keywords": _extract_keywords(settings.task),
            "summary_keywords": _extract_keywords(verification_result.summary),
            "task_summary_excerpt": verification_result.summary[:120],
            "tool_count": len(runtime_state.tool_executions),
            "verification_checks": [check.to_dict() for check in verification_result.checks],
        },
    ).to_dict()
