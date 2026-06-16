from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import loop as loop_module
from config import build_settings
from trace import TraceWriter
from verify import VerificationCheck, VerificationResult


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
        config_data={"reflect": {"strategy": "verify_failure_only_reflect"}},
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


def test_loop_records_model_decision_and_uses_planned_actions(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

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
        config_data={"model": {"provider": "rule_based", "name": "phase9-rule-based-planner"}},
    )

    assert runtime_state.model_decision is not None
    assert runtime_state.model_decision.provider == "rule_based"
    assert runtime_state.model_decision.model_name == "phase9-rule-based-planner"
    assert runtime_state.model_decision.planned_actions == [
        "定位相关文件",
        "记录任务处理结果",
        "执行任务级验证",
    ]
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
    assert model_decision_payload["provider"] == "rule_based"
    assert model_decision_payload["model_name"] == "phase9-rule-based-planner"
    assert model_decision_payload["planned_actions"] == [
        "定位相关文件",
        "记录任务处理结果",
        "执行任务级验证",
    ]
