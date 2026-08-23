from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import build_settings
from context import ContextBuilder
from hitl import ToolPermissionEngine
from runner import execute_initial_run, execute_resume_run


def _hitl_config() -> dict:
    """生成测试用 HITL 配置，默认只让编辑工具触发人工审批。"""
    return {
        "model": {"provider": "openai_compatible", "name": "demo-model"},
        "runtime": {"max_steps": 2, "interaction_mode": "headless_hitl"},
        "tool_permissions": {
            "enabled": True,
            "default_action": "allow",
            "rules": [
                {
                    "id": "edit_requires_approval",
                    "tool": "apply_patch",
                    "action": "require_approval",
                },
                {
                    "id": "hard_reset_denied",
                    "tool": "run_command",
                    "action": "deny",
                    "match": {"command_contains_any": ["git reset --hard"]},
                },
            ],
        },
        "report": {"task_outcome_summary": {"enabled": True, "model_polish": False}},
    }


def test_tool_permission_engine_matches_static_rules() -> None:
    """权限引擎应按静态规则表返回 allow、deny 或 require_approval。"""
    engine = ToolPermissionEngine(config_data=_hitl_config(), interaction_mode="headless_hitl")

    edit_decision = engine.check(tool_name="apply_patch", tool_input={"path": "app.py"})
    deny_decision = engine.check(
        tool_name="run_command",
        tool_input={"command": ["git", "reset", "--hard"]},
    )
    read_decision = engine.check(tool_name="read_file", tool_input={"path": "app.py"})

    assert edit_decision.action == "require_approval"
    assert edit_decision.matched_rule_id == "edit_requires_approval"
    assert deny_decision.action == "deny"
    assert deny_decision.matched_rule_id == "hard_reset_denied"
    assert read_decision.action == "allow"


def test_context_snapshot_includes_human_context(tmp_path: Path) -> None:
    """人工响应和策略事件应进入 human_context，而不是混到 recent_facts。"""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runtime_state = type(
        "RuntimeStateStub",
        (),
        {
            "task": "继续实现 HITL",
            "task_type": "feature",
            "current_iteration": 2,
            "initial_guide": None,
            "working_memory": {},
            "model_decision": None,
            "observe_content": {"recent_tool_results": [], "failed_tools": [], "signals": []},
            "file_context_cache": {},
            "recent_tool_executions": [],
            "human_context": {
                "pending_request": None,
                "responses": [{"request_id": "hir_001", "tool_call_id": "toolcall_001", "action": "reject"}],
                "instructions": [{"text": "不要改测试文件"}],
                "policy_events": [{"tool": "apply_patch", "action": "require_approval"}],
            },
        },
    )()

    snapshot = ContextBuilder(repo_root=str(repo_root)).build_context_snapshot(runtime_state=runtime_state)
    payload = snapshot.to_dict()

    assert payload["human_context"]["responses"][0]["action"] == "reject"
    assert payload["human_context"]["instructions"][0]["text"] == "不要改测试文件"
    assert payload["recent_facts"]["recent_tool_results"] == []


def test_headless_hitl_pauses_before_apply_patch(tmp_path: Path) -> None:
    """headless_hitl 命中 require_approval 时应写请求文件并以 need_human_input 停止。"""
    repo_root = tmp_path / "repo"
    output_root = tmp_path / "runs"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n\nRun Evidence\n", encoding="utf-8")
    settings = build_settings(
        task="创建运行证据",
        task_type="feature",
        repo_root=str(repo_root),
        output_root=str(output_root),
        config_name="hitl-test",
        interaction_mode="headless_hitl",
    )

    run_dir = execute_initial_run(settings=settings, config_data=_hitl_config())
    request = json.loads((run_dir / "human_input_request.json").read_text(encoding="utf-8"))
    pending = json.loads((run_dir / "pending_tool_call.json").read_text(encoding="utf-8"))
    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    run_finished = [event["payload"] for event in trace_events if event["event_type"] == "run_finished"][-1]

    assert request["reason"] == "tool_requires_approval"
    assert request["tool"] == "apply_patch"
    assert request["tool_call_id"] == pending["tool_call_id"]
    assert run_finished["stop_reason"]["code"] == "need_human_input"
    assert "## 人工介入记录" in report_text
    assert "当前待处理请求" in report_text


def test_headless_hitl_resume_approve_executes_pending_tool(tmp_path: Path) -> None:
    """approve 恢复后应执行原 pending tool，并把恢复事件追加到同一个 trace。"""
    repo_root = tmp_path / "repo"
    output_root = tmp_path / "runs"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n\nRun Evidence\n", encoding="utf-8")
    config_data = _hitl_config()
    config_data["runtime"]["max_steps"] = 1
    settings = build_settings(
        task="创建运行证据",
        task_type="feature",
        repo_root=str(repo_root),
        output_root=str(output_root),
        config_name="hitl-test",
        interaction_mode="headless_hitl",
    )
    run_dir = execute_initial_run(settings=settings, config_data=config_data)
    request = json.loads((run_dir / "human_input_request.json").read_text(encoding="utf-8"))
    response_path = tmp_path / "human_response.json"
    response_path.write_text(
        json.dumps(
            {
                "request_id": request["request_id"],
                "tool_call_id": request["tool_call_id"],
                "action": "approve",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    execute_resume_run(run_dir=run_dir, human_response_path=response_path, config_data=config_data)

    assert (repo_root / "run_evidence.md").exists()
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in trace_events]
    assert "human_input_response_loaded" in event_types
    assert "run_resumed" in event_types
    assert "human_input_approved" in event_types
    assert any(
        event["event_type"] == "tool_result"
        and event["payload"].get("approved_by_human") is True
        and event["payload"]["tool_output"]["ok"] is True
        for event in trace_events
    )
