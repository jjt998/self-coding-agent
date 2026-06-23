from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_trace_view import build_live_trace_snapshot


def test_live_trace_snapshot_fills_model_decision_last_rational_from_context_snapshot() -> None:
    snapshot = build_live_trace_snapshot(
        run_id="run-demo",
        config_snapshot={"task": "修复 README", "task_type": "bug_fix"},
        trace_events=[
            {
                "event_type": "context_snapshot_prepared",
                "timestamp": "2026-06-24T10:00:00",
                "payload": {
                    "iteration": 2,
                    "working_memory": {
                        "confirmed_facts": ["README 已读取"],
                        "invalidated_beliefs": [],
                        "completed_actions": ["已读取 README.md"],
                        "next_risks": [],
                        "last_rational": "上一轮先读取 README，再决定是否修改。",
                    },
                },
            },
            {
                "event_type": "model_decision",
                "timestamp": "2026-06-24T10:00:01",
                "payload": {
                    "iteration": 2,
                    "summary": "继续处理 README。",
                    "rationale": "已经看到上一轮 rationale。",
                    "planned_actions": [],
                    "working_memory": {
                        "confirmed_facts": ["README 已读取"],
                        "invalidated_beliefs": [],
                        "completed_actions": ["已读取 README.md"],
                        "next_risks": [],
                    },
                    "tool_calls": [],
                },
            },
        ],
        report_text="",
        final_diff_text="",
        trace_path="trace.jsonl",
        report_path="report.md",
        diff_path="final_diff.patch",
        snapshot_json_path="live_trace_snapshot.json",
        snapshot_js_path="live_trace_snapshot.js",
    )

    working_memory = snapshot["iterations"][0]["model_decision"]["working_memory"]
    assert working_memory["last_rational"] == "上一轮先读取 README，再决定是否修改。"
