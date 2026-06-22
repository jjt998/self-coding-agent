from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
import webbrowser

from config import RunSettings
from live_trace_view import build_live_trace_snapshot, build_live_trace_view_html, load_trace_events_from_jsonl
from loop import LoopOrchestrator, RuntimeState, StopReason, StopReasonCode
from memory import LongTermMemoryEntry, LongTermMemoryStore, _extract_keywords, _normalize_file_paths
from runtime_trace import TraceEvent, TraceWriter


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
class FinalDiffArtifactResult:
    """Record whether the run wrote a final diff artifact."""

    written: bool
    path: str
    snapshot_available: bool
    changed_file_count: int
    reason: str


@dataclass(slots=True)
class TraceViewArtifactResult:
    """Record whether the run wrote an HTML trace viewer artifact."""

    written: bool
    path: str
    event_count: int
    reason: str


@dataclass(slots=True)
class LiveTraceViewArtifactResult:
    """记录实时对话 viewer 与其快照是否已经写出。"""

    written: bool
    view_path: str
    snapshot_path: str
    event_count: int
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
    """初始化单次 run，并执行当前真实 loop 状态机流程。"""
    # run 初始化、setup、loop、报告写入都在这里串联，保证 CLI 和 eval 入口复用同一条路径。
    run_dir = Path(settings.output_root) / settings.run_id
    _prepare_execution_workspace(settings=settings, run_dir=run_dir)
    trace_writer = TraceWriter(run_dir=run_dir)

    snapshot = settings.to_dict()
    snapshot["config"] = config_data
    trace_writer.initialize(snapshot)
    trace_writer.enable_live_trace_refresh(
        lambda: _refresh_live_trace_artifacts(run_dir=run_dir, trace_writer=trace_writer)
    )
    trace_writer.refresh_live_trace_artifacts()
    _open_live_trace_view_if_possible(trace_writer=trace_writer)

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
    final_diff_artifact_result = _write_final_diff_artifact(
        run_dir=run_dir,
        runtime_state=runtime_state,
        trace_writer=trace_writer,
    )
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
            final_diff_artifact_result=final_diff_artifact_result,
            sandbox_cleanup_result=sandbox_cleanup_result,
        )
    )
    _write_trace_view_artifact(run_dir=run_dir, trace_writer=trace_writer)

    return run_dir


def _prepare_execution_workspace(settings: RunSettings, run_dir: Path) -> None:
    """按运行模式准备真正执行任务的工作目录。"""
    source_repo_root = Path(settings.source_repo_root or settings.repo_root).resolve()
    settings.source_repo_root = str(source_repo_root)
    settings.repo_root = str(source_repo_root)
    settings.sandbox_dir = ""

    if settings.workspace_mode != "per_task_sandbox":
        return

    sandbox_root = _make_unique_sandbox_root(source_repo_root=source_repo_root, run_id=settings.run_id)
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


def _make_unique_sandbox_root(source_repo_root: Path, run_id: str) -> Path:
    """在目标仓库内部创建本次 run 专属 sandbox 根目录。"""
    sandbox_parent = source_repo_root / ".agent_sandboxes"
    sandbox_parent.mkdir(parents=True, exist_ok=True)
    base_name = run_id
    for index in range(1, 1000):
        suffix = "" if index == 1 else f"-{index}"
        sandbox_root = sandbox_parent / f"{base_name}{suffix}"
        try:
            sandbox_root.mkdir()
        except FileExistsError:
            continue
        return sandbox_root
    raise RuntimeError(f"无法为 run `{run_id}` 创建唯一 sandbox 目录。")


def _build_sandbox_ignore(source_repo_root: Path, output_root: Path):
    """生成 sandbox 复制时的忽略规则，避免把运行产物和缓存目录再卷进去。"""
    ignored_names = {
        ".git",
        ".agent_sandboxes",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".pytest_tmp",
        ".pytest_tmp_refactor_rule",
        ".tmp_smoke_eval",
        "pytest_tmp",
    }
    ignored_prefixes = (
        "codex-repro-",
    )
    try:
        relative_output_root = output_root.relative_to(source_repo_root)
    except ValueError:
        relative_output_root = None
    if relative_output_root and relative_output_root.parts:
        # 这里忽略 output_root 在仓库内的顶层目录名，避免复制 sandbox 时把 runs 再递归带进去。
        ignored_names.add(relative_output_root.parts[0])

    def _ignore(_current_dir: str, names: list[str]) -> set[str]:
        ignored_entries: set[str] = set()
        for name in names:
            # 这里把 pytest、smoke run 和 codex 复现场景生成的临时目录统一排除，
            # 避免复制 sandbox 时把外部占用目录也卷进去，导致 WinError 5。
            if name in ignored_names or any(name.startswith(prefix) for prefix in ignored_prefixes):
                ignored_entries.add(name)
        return ignored_entries

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
    if retention_policy == "keep_on_success":
        if verification_passed:
            return True, "当前策略为 keep_on_success，且本次验证通过。"
        return False, "当前策略为 keep_on_success，且本次验证未通过。"
    if verification_passed:
        return False, "当前策略为 delete_on_success，且本次验证通过。"
    return True, "当前策略为 delete_on_success，且本次验证未通过。"


def _write_final_diff_artifact(
    run_dir: Path,
    runtime_state: RuntimeState,
    trace_writer: TraceWriter,
) -> FinalDiffArtifactResult:
    """Persist the verify-owned diff snapshot as a run artifact."""
    artifact_path = run_dir / "final_diff.patch"
    snapshot = None
    if runtime_state.verification_result and isinstance(runtime_state.verification_result.details, dict):
        snapshot = runtime_state.verification_result.details.get("verification_diff_snapshot")

    raw_diffs: list[dict[str, object]] = []
    changed_file_count = 0
    snapshot_available = isinstance(snapshot, dict)
    if isinstance(snapshot, dict):
        diffs_value = snapshot.get("diffs", [])
        if isinstance(diffs_value, list):
            raw_diffs = [item for item in diffs_value if isinstance(item, dict)]
        changed_file_count = int(snapshot.get("changed_file_count") or len(raw_diffs))

    diff_texts = [item["diff"] for item in raw_diffs if isinstance(item.get("diff"), str) and item.get("diff")]
    artifact_text = "\n\n".join(diff_texts)
    if artifact_text:
        artifact_text += "\n"
    artifact_path.write_text(artifact_text, encoding="utf-8")

    result = FinalDiffArtifactResult(
        written=True,
        path=str(artifact_path),
        snapshot_available=snapshot_available,
        changed_file_count=changed_file_count,
        reason=(
            "Wrote final diff artifact from verification diff snapshot."
            if snapshot_available
            else "Verification diff snapshot unavailable; wrote an empty final diff artifact."
        ),
    )
    trace_writer.write_event(
        TraceEvent(
            event_type="final_diff_artifact_written",
            payload=asdict(result),
        )
    )
    return result


def _refresh_live_trace_artifacts(
    run_dir: Path,
    trace_writer: TraceWriter,
) -> LiveTraceViewArtifactResult:
    """根据当前 trace/report/diff 实时刷新对话 viewer 和快照。"""
    trace_events = load_trace_events_from_jsonl(trace_writer.trace_path)
    report_text = trace_writer.report_path.read_text(encoding="utf-8") if trace_writer.report_path.exists() else ""
    final_diff_text = (run_dir / "final_diff.patch").read_text(encoding="utf-8") if (run_dir / "final_diff.patch").exists() else ""
    config_snapshot = (
        json.loads(trace_writer.config_snapshot_path.read_text(encoding="utf-8"))
        if trace_writer.config_snapshot_path.exists()
        else {}
    )
    snapshot_payload = build_live_trace_snapshot(
        run_id=run_dir.name,
        config_snapshot=config_snapshot,
        trace_events=trace_events,
        report_text=report_text,
        final_diff_text=final_diff_text,
        trace_path=trace_writer.trace_path.name,
        report_path=trace_writer.report_path.name,
        diff_path="final_diff.patch",
        snapshot_json_path=trace_writer.live_trace_snapshot_path.name,
        snapshot_js_path=trace_writer.live_trace_snapshot_js_path.name,
    )
    trace_writer.write_live_trace_snapshot(snapshot_payload)
    trace_writer.write_live_trace_view(
        build_live_trace_view_html(
            run_id=run_dir.name,
            snapshot_js_path=trace_writer.live_trace_snapshot_js_path.name,
        )
    )
    return LiveTraceViewArtifactResult(
        written=True,
        view_path=str(trace_writer.live_trace_view_path),
        snapshot_path=str(trace_writer.live_trace_snapshot_path),
        event_count=len(trace_events),
        reason="Wrote live trace viewer and snapshot artifacts.",
    )


def _open_live_trace_view_if_possible(trace_writer: TraceWriter) -> None:
    """尽力打开实时 viewer；测试环境和无图形环境下静默跳过。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if ".pytest_tmp" in str(trace_writer.run_dir):
        return
    live_trace_view_path = trace_writer.live_trace_view_path.resolve()
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(live_trace_view_path))
            return
        webbrowser.open(live_trace_view_path.as_uri())
    except OSError:
        return


def _write_trace_view_artifact(
    run_dir: Path,
    trace_writer: TraceWriter,
) -> TraceViewArtifactResult:
    """Persist a static HTML viewer for the current run trace."""
    trace_events = _load_trace_events_from_jsonl(trace_writer.trace_path)
    report_text = trace_writer.report_path.read_text(encoding="utf-8") if trace_writer.report_path.exists() else ""
    final_diff_text = (run_dir / "final_diff.patch").read_text(encoding="utf-8") if (run_dir / "final_diff.patch").exists() else ""
    html = _build_trace_view_html(
        run_id=run_dir.name,
        trace_events=trace_events,
        report_text=report_text,
        final_diff_text=final_diff_text,
        trace_path=trace_writer.trace_path.name,
        report_path=trace_writer.report_path.name,
        diff_path="final_diff.patch",
    )
    trace_writer.write_trace_view(html)
    return TraceViewArtifactResult(
        written=True,
        path=str(trace_writer.trace_view_path),
        event_count=len(trace_events),
        reason="Wrote static HTML trace viewer artifact.",
    )


def _load_trace_events_from_jsonl(trace_path: Path) -> list[dict[str, Any]]:
    """Load trace.jsonl into a plain event list for HTML rendering."""
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def _build_trace_view_html(
    *,
    run_id: str,
    trace_events: list[dict[str, Any]],
    report_text: str,
    final_diff_text: str,
    trace_path: str,
    report_path: str,
    diff_path: str,
) -> str:
    """Build a standalone HTML trace viewer for a run."""
    event_type_counts: dict[str, int] = {}
    for event in trace_events:
        event_type = str(event.get("event_type", "unknown"))
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
    event_type_options = sorted(event_type_counts)
    initial_payload = {
        "run_id": run_id,
        "trace_path": trace_path,
        "report_path": report_path,
        "diff_path": diff_path,
        "event_count": len(trace_events),
        "event_type_counts": event_type_counts,
        "events": trace_events,
        "report_text": report_text,
        "final_diff_text": final_diff_text,
    }
    viewer_json = json.dumps(initial_payload, ensure_ascii=False)
    options_html = "".join(f'<option value="{event_type}">{event_type}</option>' for event_type in event_type_options)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trace View - {run_id}</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #1c1b19;
      --muted: #6f6a62;
      --line: #d8d0c4;
      --accent: #0f766e;
      --accent-soft: #dff3f1;
      --add: #e7f6ea;
      --del: #fde7e7;
      --shadow: 0 10px 30px rgba(28, 27, 25, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #f8efe0 0, transparent 26%),
        linear-gradient(180deg, #f7f4ee 0%, var(--bg) 100%);
    }}
    .page {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 24px;
      margin-bottom: 18px;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      font-weight: 700;
      letter-spacing: 0.01em;
    }}
    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .pill {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 13px;
      font-weight: 600;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 18px;
      align-items: start;
    }}
    .sidebar, .content {{
      display: grid;
      gap: 18px;
    }}
    .panel {{
      padding: 18px;
    }}
    .controls {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 600;
    }}
    input, select {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }}
    .stats {{
      display: grid;
      gap: 10px;
    }}
    .stat {{
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f2;
      border: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 14px;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    button {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      color: var(--ink);
      font-weight: 600;
    }}
    button:hover {{ border-color: var(--accent); color: var(--accent); }}
    .events {{
      display: grid;
      gap: 12px;
    }}
    details.event {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      overflow: hidden;
    }}
    summary {{
      list-style: none;
      cursor: pointer;
      padding: 14px 16px;
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      background: #fcfaf6;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    .event-index {{
      min-width: 34px;
      height: 34px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 700;
      font-size: 13px;
    }}
    .event-type {{
      font-weight: 700;
    }}
    .event-meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .event-body {{
      padding: 0 16px 16px;
      display: grid;
      gap: 12px;
    }}
    .event-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }}
    .event-card {{
      padding: 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fffdf9;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.5;
      font-family: "Cascadia Code", Consolas, monospace;
    }}
    .diff {{
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      background: #fff;
    }}
    .diff-line {{
      padding: 0 12px;
      white-space: pre-wrap;
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
    }}
    .diff-line.add {{ background: var(--add); color: #166534; }}
    .diff-line.del {{ background: var(--del); color: #991b1b; }}
    .diff-line.meta {{ background: #f1eee8; color: #6b5f52; }}
    .empty {{
      color: var(--muted);
      font-style: italic;
    }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .page {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Trace View</h1>
      <div>Run <strong>{run_id}</strong></div>
      <div class="meta">
        <span class="pill">trace: {trace_path}</span>
        <span class="pill">report: {report_path}</span>
        <span class="pill">diff: {diff_path}</span>
      </div>
    </section>
    <div class="layout">
      <aside class="sidebar">
        <section class="panel controls">
          <h2>Filters</h2>
          <label>Event Type
            <select id="eventTypeFilter">
              <option value="">All events</option>
              {options_html}
            </select>
          </label>
          <label>Iteration
            <select id="iterationFilter">
              <option value="">All iterations</option>
            </select>
          </label>
          <label>Search
            <input id="searchInput" type="search" placeholder="Search event type, payload, timestamp">
          </label>
        </section>
        <section class="panel">
          <h2>Stats</h2>
          <div class="stats" id="stats"></div>
        </section>
        <section class="panel">
          <h2>Final Diff</h2>
          <div id="diffContainer"></div>
        </section>
      </aside>
      <main class="content">
        <section class="panel">
          <div class="toolbar">
            <button id="expandAll">Expand all</button>
            <button id="collapseAll">Collapse all</button>
          </div>
          <div class="events" id="events"></div>
        </section>
        <section class="panel">
          <h2>Report Snapshot</h2>
          <pre id="reportText"></pre>
        </section>
      </main>
    </div>
  </div>
  <script id="trace-data" type="application/json">{viewer_json}</script>
  <script>
    const data = JSON.parse(document.getElementById("trace-data").textContent);
    const eventTypeFilter = document.getElementById("eventTypeFilter");
    const iterationFilter = document.getElementById("iterationFilter");
    const searchInput = document.getElementById("searchInput");
    const stats = document.getElementById("stats");
    const eventsRoot = document.getElementById("events");
    const reportText = document.getElementById("reportText");
    const diffContainer = document.getElementById("diffContainer");

    function escapeHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function buildIterationOptions() {{
      const iterations = Array.from(new Set(
        data.events
          .map((event) => event && event.payload ? event.payload.iteration : undefined)
          .filter((value) => value !== undefined && value !== null)
      )).sort((a, b) => a - b);
      for (const iteration of iterations) {{
        const option = document.createElement("option");
        option.value = String(iteration);
        option.textContent = `Iteration ${{iteration}}`;
        iterationFilter.appendChild(option);
      }}
    }}

    function renderStats(filteredEvents) {{
      const rows = [];
      rows.push(["visible events", filteredEvents.length]);
      rows.push(["total events", data.event_count]);
      const typeCounts = new Map();
      for (const event of filteredEvents) {{
        const key = event.event_type || "unknown";
        typeCounts.set(key, (typeCounts.get(key) || 0) + 1);
      }}
      for (const [eventType, count] of Array.from(typeCounts.entries()).sort()) {{
        rows.push([eventType, count]);
      }}
      stats.innerHTML = rows.map(([label, value]) =>
        `<div class="stat"><span>${{escapeHtml(label)}}</span><strong>${{escapeHtml(value)}}</strong></div>`
      ).join("");
    }}

    function renderDiff() {{
      if (!data.final_diff_text) {{
        diffContainer.innerHTML = '<div class="empty">No final diff artifact.</div>';
        return;
      }}
      const lines = data.final_diff_text.split(/\\r?\\n/);
      diffContainer.innerHTML = `<div class="diff">${{lines.map((line) => {{
        let className = "";
        if (line.startsWith("+") && !line.startsWith("+++")) className = "add";
        else if (line.startsWith("-") && !line.startsWith("---")) className = "del";
        else if (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) className = "meta";
        return `<div class="diff-line ${{className}}">${{escapeHtml(line || " ")}}</div>`;
      }}).join("")}}</div>`;
    }}

    function filterEvents() {{
      const eventType = eventTypeFilter.value;
      const iteration = iterationFilter.value;
      const needle = searchInput.value.trim().toLowerCase();
      return data.events.filter((event) => {{
        if (eventType && event.event_type !== eventType) return false;
        const eventIteration = event && event.payload ? event.payload.iteration : undefined;
        if (iteration && String(eventIteration) !== iteration) return false;
        if (!needle) return true;
        const haystack = JSON.stringify(event).toLowerCase();
        return haystack.includes(needle);
      }});
    }}

    function renderEvents() {{
      const filteredEvents = filterEvents();
      renderStats(filteredEvents);
      if (!filteredEvents.length) {{
        eventsRoot.innerHTML = '<div class="empty">No matching events.</div>';
        return;
      }}
      eventsRoot.innerHTML = filteredEvents.map((event, index) => {{
        const payload = event.payload || {{}};
        const iteration = payload.iteration ?? payload.current_iteration ?? "";
        const payloadText = JSON.stringify(payload, null, 2);
        const isOpen = index < 3 || event.event_type === "model_decision";
        const keyRows = [
          ["event_type", event.event_type || "unknown"],
          ["timestamp", event.timestamp || ""],
          ["iteration", iteration === "" ? "n/a" : iteration],
        ];
        if (payload.summary) keyRows.push(["summary", payload.summary]);
        return `
          <details class="event"${{isOpen ? " open" : ""}}>
            <summary>
              <span class="event-index">${{index + 1}}</span>
              <span class="event-type">${{escapeHtml(event.event_type || "unknown")}}</span>
              <span class="event-meta">${{escapeHtml(event.timestamp || "")}}</span>
              <span class="event-meta">${{iteration === "" ? "" : `iteration=${{iteration}}`}}</span>
            </summary>
            <div class="event-body">
              <div class="event-grid">
                ${{keyRows.map(([label, value]) => `
                  <div class="event-card">
                    <h3>${{escapeHtml(label)}}</h3>
                    <pre>${{escapeHtml(value)}}</pre>
                  </div>
                `).join("")}}
              </div>
              <div class="event-card">
                <h3>Payload</h3>
                <pre>${{escapeHtml(payloadText)}}</pre>
              </div>
            </div>
          </details>
        `;
      }}).join("");
    }}

    document.getElementById("expandAll").addEventListener("click", () => {{
      document.querySelectorAll("details.event").forEach((item) => item.open = true);
    }});
    document.getElementById("collapseAll").addEventListener("click", () => {{
      document.querySelectorAll("details.event").forEach((item) => item.open = false);
    }});
    eventTypeFilter.addEventListener("change", renderEvents);
    iterationFilter.addEventListener("change", renderEvents);
    searchInput.addEventListener("input", renderEvents);

    reportText.textContent = data.report_text || "";
    buildIterationOptions();
    renderDiff();
    renderEvents();
  </script>
</body>
</html>"""


def _build_phase_4_report(
    settings: RunSettings,
    runtime_state: RuntimeState,
    memory_write_result: MemoryWriteResult,
    final_diff_artifact_result: FinalDiffArtifactResult,
    sandbox_cleanup_result: SandboxCleanupResult,
) -> str:
    """把状态流、工具摘要和验证结果整理成当前阶段可读报告。"""
    stop_reason = runtime_state.stop_reason
    stop_reason_text = stop_reason.message if stop_reason else "未设置"
    stop_reason_code = stop_reason.code.value if stop_reason else "unknown"
    stop_reason_details = stop_reason.details if stop_reason else {}
    failure_diagnostic_lines = [f"- stop reason：`{stop_reason_code}`"]
    if stop_reason_code == "setup_failed":
        failure_diagnostic_lines.append(
            f"- setup 失败命令数：`{len(stop_reason_details.get('failed_setup_commands', []))}`"
        )
    elif stop_reason_code == "model_error":
        failure_diagnostic_lines.append(f"- 模型错误类型：`{stop_reason_details.get('error_type', 'unknown')}`")
        failure_diagnostic_lines.append(f"- provider：`{stop_reason_details.get('provider', '')}`")
        failure_diagnostic_lines.append(f"- model：`{stop_reason_details.get('model_name', '')}`")
        if stop_reason_details.get("base_url"):
            failure_diagnostic_lines.append(f"- base_url：`{stop_reason_details.get('base_url')}`")
        if stop_reason_details.get("status_code"):
            failure_diagnostic_lines.append(f"- HTTP 状态码：`{stop_reason_details.get('status_code')}`")
        if stop_reason_details.get("field_path"):
            failure_diagnostic_lines.append(f"- 响应字段路径：`{stop_reason_details.get('field_path')}`")
        if stop_reason_details.get("request_error_type"):
            failure_diagnostic_lines.append(f"- 请求错误类型：`{stop_reason_details.get('request_error_type')}`")
    elif stop_reason_code in {"verification_failed", "max_steps_reached"}:
        verification_failure = stop_reason_details.get("verification_failure", {})
        if isinstance(verification_failure, dict):
            failure_diagnostic_lines.append(
                f"- 验证模式：`{verification_failure.get('verification_mode', '')}`"
            )
            failure_diagnostic_lines.append(
                f"- 失败检查：`{', '.join(verification_failure.get('failing_check_names', [])) or 'none'}`"
            )
    failure_diagnostic_summary = "\n".join(failure_diagnostic_lines)
    completed_states = " -> ".join(runtime_state.completed_states)
    reflect_status = "已触发" if runtime_state.reflect_triggered else "未触发"
    verification_result = runtime_state.verification_result
    verification_status = "通过" if verification_result and verification_result.passed else "未通过"
    verification_summary = verification_result.summary if verification_result else "尚未生成验证结果。"
    context_snapshot = runtime_state.context_snapshot
    observation_summary = runtime_state.observation_summary or "尚未生成反思事实摘要。"
    changed_file_lines = [
        f"- `{path}`"
        for path in runtime_state.changed_files
    ]
    changed_files_summary = "\n".join(changed_file_lines) if changed_file_lines else "- 暂无变更文件。"

    reflect_feedback = runtime_state.reflect_feedback
    if reflect_feedback:
        observation = reflect_feedback.get("observation", {})
        if not isinstance(observation, dict):
            observation = {}
        signals = reflect_feedback.get("signals", [])
        failed_tools = reflect_feedback.get("failed_tools", [])
        recent_tool_results = reflect_feedback.get("recent_tool_results", [])
        recent_tool_lines: list[str] = []
        if isinstance(recent_tool_results, list):
            for item in recent_tool_results[-5:]:
                if not isinstance(item, dict):
                    continue
                parts = [f"tool={item.get('tool_name', 'unknown')}"]
                for field_name in ["path", "content_mode", "read_coverage", "content_truncated", "error"]:
                    if field_name in item:
                        parts.append(f"{field_name}={item.get(field_name)}")
                recent_tool_lines.append("; ".join(parts))
        reflect_feedback_summary = (
            f"- trigger: `{reflect_feedback.get('trigger', 'unknown')}`\n"
            f"- signals: `{', '.join(str(item) for item in signals) or 'none'}`\n"
            f"- changed files: `{', '.join(str(item) for item in observation.get('changed_files', [])) or 'none'}`\n"
            f"- failed tool count: `{observation.get('failed_tool_count', 0)}`\n"
            f"- failed tools: `{', '.join(str(item.get('tool_name', 'unknown')) for item in failed_tools if isinstance(item, dict)) or 'none'}`\n"
            f"- recent tool results: `{ ' | '.join(recent_tool_lines) if recent_tool_lines else 'none' }`"
        )
    else:
        reflect_feedback_summary = "- 未生成反思反馈。"

    model_decision = runtime_state.model_decision
    if model_decision:
        model_tool_sequence = ", ".join(tool_call.tool_name for tool_call in model_decision.tool_calls) or "none"
        model_actions = "；".join(model_decision.planned_actions) or "无"
        model_donelist = "；".join(model_decision.donelist) or "无"
        model_response_summary = (
            f"- provider：`{model_decision.provider}`\n"
            f"- model：`{model_decision.model_name}`\n"
            f"- summary：{model_decision.summary}\n"
            f"- rationale：{model_decision.rationale}\n"
            f"- planned_actions：{model_actions}\n"
            f"- donelist（累计已完成事项）：{model_donelist}\n"
            f"- tool_calls：`{model_tool_sequence}`\n"
            f"- 原始返回：见 `trace.jsonl` 中的 `model_raw_response` 事件。"
        )
    else:
        model_response_summary = "- 尚未生成模型返回。"

    tool_lines = []
    for execution in runtime_state.tool_executions:
        tool_ok = execution.tool_output.get("ok")
        tool_status = "成功" if tool_ok is True else "已记录"
        tool_lines.append(f"- `{execution.tool_name}`：{tool_status}")
    tool_summary = "\n".join(tool_lines) if tool_lines else "- 本次 run 未执行工具。"

    verification_lines = []
    if verification_result:
        if verification_result.details.get("verification_mode") == "missing_task_verification":
            verification_lines.append(
                "- 任务未配置 `verify_commands` 或 `verify_rules`，当前 run 无法判定任务是否完成。"
            )
        for check in verification_result.checks:
            check_status = "通过" if check.passed else "未通过"
            verification_lines.append(f"- {check.name}：{check_status}。{check.detail}")
    verification_details = "\n".join(verification_lines) if verification_lines else "- 暂无验证检查项。"
    memory_write_status = "已写入" if memory_write_result.written else "未写入"
    sandbox_status = "已保留" if sandbox_cleanup_result.kept else "已删除"
    token_usage = runtime_state.token_usage
    token_usage_status = "完整" if token_usage.get("complete") else "不完整"
    token_usage_summary = (
        f"- usage 完整性：`{token_usage_status}`\n"
        f"- 模型请求数：`{token_usage.get('request_count', 0)}`\n"
        f"- 缺失 usage 请求数：`{token_usage.get('missing_usage_count', 0)}`\n"
        f"- prompt tokens：`{token_usage.get('prompt_tokens', 0)}`\n"
        f"- completion tokens：`{token_usage.get('completion_tokens', 0)}`\n"
        f"- total tokens：`{token_usage.get('total_tokens', 0)}`"
    )

    diff_snapshot_status = "available" if final_diff_artifact_result.snapshot_available else "unavailable"
    code_diff_summary = (
        f"- diff snapshot: `{diff_snapshot_status}`\n"
        f"- changed files: `{final_diff_artifact_result.changed_file_count}`\n"
        f"- artifact: `final_diff.patch`\n"
        f"- detail: {final_diff_artifact_result.reason}"
    )
    trace_view_summary = (
        "- artifact: `trace_view.html`\n"
        "- detail: 原始事件调试视图，适合逐条排查 trace.jsonl。\n"
        "- artifact: `live_trace_view.html`\n"
        "- detail: 实时对话视图，右侧显示 harness 请求，左侧显示结构化 model_decision。\n"
        "- artifact: `live_trace_snapshot.json`\n"
        "- detail: live_trace_view.html 轮询的实时快照数据。"
    )
    token_usage_summary = (
        f"{token_usage_summary}\n\n## Code Diff\n\n{code_diff_summary}\n\n## Trace View\n\n{trace_view_summary}"
    )

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
        f"\n## 失败诊断\n\n"
        f"{failure_diagnostic_summary}\n"
        f"\n## 反思事实摘要\n\n"
        f"- 变更文件数：`{len(runtime_state.changed_files)}`\n"
        f"- 失败工具数：`{runtime_state.failed_tool_count}`\n"
        f"- 事实摘要：{observation_summary}\n"
        f"{changed_files_summary}\n"
        f"\n## 反思反馈\n\n"
        f"{reflect_feedback_summary}\n"
        f"\n## 模型返回摘要\n\n"
        f"{model_response_summary}\n"
        f"\n## Token 消耗\n\n"
        f"{token_usage_summary}\n"
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


_ORIGINAL_BUILD_PHASE_4_REPORT = _build_phase_4_report


def _build_phase_4_report(
    settings: RunSettings,
    runtime_state: RuntimeState,
    memory_write_result: MemoryWriteResult,
    final_diff_artifact_result: FinalDiffArtifactResult,
    sandbox_cleanup_result: SandboxCleanupResult,
) -> str:
    """在原报告基础上补充最终验证与求解收口诊断说明。"""
    base_report = _ORIGINAL_BUILD_PHASE_4_REPORT(
        settings=settings,
        runtime_state=runtime_state,
        memory_write_result=memory_write_result,
        final_diff_artifact_result=final_diff_artifact_result,
        sandbox_cleanup_result=sandbox_cleanup_result,
    )
    stop_reason_details = runtime_state.stop_reason.details if runtime_state.stop_reason else {}
    solve_loop_exit_reason = str(stop_reason_details.get("solve_loop_exit_reason", "")).strip() or "unknown"
    final_verification_passed = bool(stop_reason_details.get("final_verification_passed"))
    appendix = (
        "\n\n## 最终验证语义\n\n"
        f"- 本次 verify 为末尾单次最终验证：`true`\n"
        f"- 求解阶段退出原因：`{solve_loop_exit_reason}`\n"
        f"- 是否命中连续两次空 tool_calls：`{'true' if solve_loop_exit_reason == 'no_planned_tool_calls' else 'false'}`\n"
        f"- 最终验证是否通过：`{'true' if final_verification_passed else 'false'}`\n"
    )
    return base_report + appendix
