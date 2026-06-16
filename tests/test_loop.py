from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import loop as loop_module
from config import build_settings
from trace import TraceWriter
from verify import VerificationCheck, VerificationResult


def _model_config() -> dict:
    return {"model": {"provider": "openai_compatible", "name": "demo-model"}}


def _fake_model_response(tool_calls: list[dict] | None = None) -> str:
    decision = {
        "summary": "已生成真实模型决策。",
        "rationale": "按模型返回的工具计划执行。",
        "planned_actions": ["执行模型工具计划"],
        "tool_calls": tool_calls
        or [
            {"tool_name": "search_text", "tool_input": {"query": "Agent Notes", "limit": 5}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "path": "agent_notes.md",
                    "old_text": None,
                    "new_text": "# Agent Notes\n\n- 任务：创建脚手架\n- 当前情况：已记录到 Phase 3 工具闭环。\n",
                },
            },
            {"tool_name": "read_file", "tool_input": {"path": "agent_notes.md"}},
            {
                "tool_name": "run_command",
                "tool_input": {
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; print(Path('agent_notes.md').read_text(encoding='utf-8').splitlines()[0])",
                    ]
                },
            },
            {"tool_name": "git_diff", "tool_input": {"paths": ["agent_notes.md"]}},
        ],
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )


def test_verify_failure_only_reflect_triggers_after_failed_verification(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=False,
            summary="验证失败：至少有一项关键检查未通过。",
            checks=[VerificationCheck(name="说明文件可读", passed=False, detail="未读回预期内容。")],
            details={},
        )

    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", _fake_model_response())

    settings = build_settings(
        task="触发验证失败后的 reflect",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="verify_failure_only_reflect",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    runtime_state = loop_module.LoopOrchestrator(trace_writer=trace_writer).run(
        settings=settings,
        config_data={**_model_config(), "reflect": {"strategy": "verify_failure_only_reflect"}},
    )

    assert runtime_state.reflect_triggered is True
    assert runtime_state.reflect_trigger_reason == "verification_failed"
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "verify",
        "reflect",
        "finalize",
    ]

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
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
        "verify",
        "reflect",
        "finalize",
    ]


def test_loop_records_model_decision_and_uses_planned_actions(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", _fake_model_response())

    settings = build_settings(
        task="创建脚手架",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    runtime_state = loop_module.LoopOrchestrator(trace_writer=trace_writer).run(
        settings=settings,
        config_data=_model_config(),
    )

    assert runtime_state.model_decision is not None
    assert runtime_state.model_decision.provider == "openai_compatible"
    assert runtime_state.model_decision.model_name == "demo-model"
    assert runtime_state.model_decision.planned_actions == ["执行模型工具计划"]
    assert [execution.tool_name for execution in runtime_state.tool_executions] == [
        "search_text",
        "apply_patch",
        "read_file",
        "run_command",
        "git_diff",
    ]

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model_decision_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision")
    assert model_decision_payload["provider"] == "openai_compatible"
    assert model_decision_payload["model_name"] == "demo-model"
    assert model_decision_payload["planned_actions"] == ["执行模型工具计划"]


def test_loop_stops_with_model_error_when_model_config_fails(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = build_settings(
        task="创建脚手架",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    runtime_state = loop_module.LoopOrchestrator(trace_writer=trace_writer).run(
        settings=settings,
        config_data=_model_config(),
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.MODEL_ERROR
    assert runtime_state.current_state == "plan"
    assert runtime_state.completed_states == ["ingest", "analyze"]
    assert runtime_state.tool_executions == []

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failure_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision_failed")
    assert failure_payload["provider"] == "openai_compatible"
    assert failure_payload["model_name"] == "demo-model"
    assert failure_payload["error_type"] == "ModelConfigError"
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["code"] == "model_error"
