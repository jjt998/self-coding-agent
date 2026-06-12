from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run


def test_cli_creates_run_artifacts(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "创建脚手架",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    # 这里显式补 PYTHONPATH，是为了让测试在 src 布局下直接按模块方式启动 CLI。
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    # Phase 1 的验收重点就是：一次 CLI 调用后，run 目录和三类基础产物都要落下来。
    run_dirs = list(output_root.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.md").exists()
    snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["task"] == "创建脚手架"

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    transition_targets = [
        event["payload"]["to_state"]
        for event in trace_events
        if event["event_type"] == "state_transitioned"
    ]
    assert transition_targets == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "reflect",
        "verify",
        "finalize",
    ]

    tool_called_names = [
        event["payload"]["tool_name"]
        for event in trace_events
        if event["event_type"] == "tool_called"
    ]
    assert tool_called_names == [
        "search_text",
        "apply_patch",
        "read_file",
        "run_command",
        "git_diff",
    ]

    tool_results = [event["payload"] for event in trace_events if event["event_type"] == "tool_result"]
    assert len(tool_results) == 5
    assert tool_results[1]["tool_output"]["ok"] is True
    assert tool_results[2]["tool_output"]["content"].startswith("# Agent Notes")
    assert tool_results[3]["tool_output"]["stdout"].strip() == "# Agent Notes"
    assert tool_results[4]["tool_output"]["changed_file_count"] == 1
    assert "agent_notes.md" in tool_results[4]["tool_output"]["diffs"][0]["path"]

    notes_path = repo_root / "agent_notes.md"
    assert notes_path.exists()
    assert "当前情况：已记录到 Phase 3 工具闭环。" in notes_path.read_text(encoding="utf-8")

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "`finalize`" in report_text
    assert "reflect：已触发" in report_text
