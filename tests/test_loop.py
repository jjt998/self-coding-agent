from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import loop as loop_module
from config import build_settings
from model import ModelDecision, ModelResponseError, PlannedToolCall
from trace import TraceWriter
from verify import VerificationCheck, VerificationResult


def _model_config() -> dict:
    return {"model": {"provider": "openai_compatible", "name": "demo-model"}}


def test_src_no_longer_contains_phase3_stub_loop_markers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "src").glob("*.py"))
    )

    assert "build_phase_3_tool_sequence" not in src_text
    assert "_run_stub_state" not in src_text
    assert "Phase 3 工具闭环" not in src_text


def _fake_model_response(tool_calls: list[dict] | None = None) -> str:
    decision = {
        "summary": "已生成真实模型决策。",
        "rationale": "按模型返回的工具计划执行。",
        "planned_actions": ["执行模型工具计划"],
        "tool_calls": tool_calls
        or [
            {"tool_name": "search_text", "tool_input": {"query": "Run Evidence", "limit": 5}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "path": "run_evidence.md",
                    "old_text": None,
                    "new_text": "# Run Evidence\n\n- 任务：创建脚手架\n- 当前情况：已记录到 真实 loop 运行证据。\n",
                },
            },
            {"tool_name": "read_file", "tool_input": {"path": "run_evidence.md"}},
            {
                "tool_name": "run_command",
                "tool_input": {
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; print(Path('run_evidence.md').read_text(encoding='utf-8').splitlines()[0])",
                    ]
                },
            },
            {"tool_name": "git_diff", "tool_input": {"paths": ["run_evidence.md"]}},
        ],
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )


def _constraint_aware_rationale(runtime_feedback: dict | None, *, repeat_reason: bool = True) -> str:
    """为测试 fake 模型生成可通过 reflect 硬约束校验的说明文本。"""
    reflect_feedback = (runtime_feedback or {}).get("previous_reflect_feedback", {})
    constraints = reflect_feedback.get("replan_constraints", {}) if isinstance(reflect_feedback, dict) else {}
    if not constraints:
        return "首轮执行常规计划。"
    parts = [
        str(constraints.get("failure_reason", "")),
        " ".join(str(item) for item in constraints.get("failed_check_names", [])),
        " ".join(str(item) for item in constraints.get("must_address", [])),
    ]
    suffix = "，再次重复相同工具序列是因为测试需要保持同一工具计划。" if repeat_reason else ""
    return "回应 reflect 约束：" + " ".join(item for item in parts if item).strip() + suffix


def test_verify_failure_only_reflect_triggers_after_failed_verification(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-verify-reflect-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            rationale = _constraint_aware_rationale(runtime_feedback)
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale=rationale,
                planned_actions=[rationale],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ],
            )

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=False,
            summary="验证失败：至少有一项关键检查未通过。",
            checks=[VerificationCheck(name="说明文件可读", passed=False, detail="未读回预期内容。")],
            details={},
        )

    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

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
    assert runtime_state.reflect_count == 1
    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.VERIFICATION_FAILED
    assert runtime_state.stop_reason.details["verification_failure"]["failing_check_names"] == ["说明文件可读"]
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "verify",
        "reflect",
        "plan",
        "act",
        "observe",
        "verify",
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
        "plan",
        "act",
        "observe",
        "verify",
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
        verify_rules=[
            {"type": "file_exists", "name": "run evidence exists", "path": "run_evidence.md"},
        ],
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
    assert runtime_state.progress_made is True
    assert runtime_state.changed_files == ["run_evidence.md"]
    assert runtime_state.failed_tool_count == 0
    assert runtime_state.reflect_triggered is False
    assert runtime_state.iteration_count == 1
    assert runtime_state.max_steps == 2
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "verify",
        "finalize",
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
    assert model_decision_payload["iteration"] == 1
    raw_response_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_raw_response")
    assert raw_response_payload["provider"] == "openai_compatible"
    assert raw_response_payload["model_name"] == "demo-model"
    assert raw_response_payload["iteration"] == 1
    assert raw_response_payload["parsed_ok"] is True
    assert raw_response_payload["content_length"] == len(raw_response_payload["content"])
    assert json.loads(raw_response_payload["content"])["planned_actions"] == ["执行模型工具计划"]
    progress_payload = next(event["payload"] for event in trace_events if event["event_type"] == "progress_observed")
    assert progress_payload["progress_made"] is True
    assert progress_payload["changed_files"] == ["run_evidence.md"]
    assert progress_payload["failed_tool_count"] == 0
    ingest_payload = next(event["payload"] for event in trace_events if event["event_type"] == "task_ingested")
    assert ingest_payload["task"] == settings.task
    assert ingest_payload["task_type"] == settings.task_type
    assert ingest_payload["repo_root"] == settings.repo_root
    assert ingest_payload["source_repo_root"] == settings.source_repo_root
    assert ingest_payload["workspace_mode"] == settings.workspace_mode
    assert ingest_payload["setup_command_count"] == 0
    assert ingest_payload["verify_command_count"] == 0
    assert ingest_payload["verify_rule_count"] == 1
    assert ingest_payload["max_steps"] == 2
    assert ingest_payload["config_name"] == "default"
    assert ingest_payload["config_keys"] == ["model"]
    assert ingest_payload["model_provider"] == "openai_compatible"
    assert ingest_payload["model_name"] == "demo-model"
    finalize_payload = next(event["payload"] for event in trace_events if event["event_type"] == "finalize_summary")
    assert finalize_payload["verification_passed"] is True
    assert finalize_payload["progress_made"] is True
    assert finalize_payload["changed_files"] == ["run_evidence.md"]
    assert finalize_payload["failed_tool_count"] == 0
    assert finalize_payload["reflect_count"] == 0
    assert finalize_payload["iteration_count"] == 1
    assert finalize_payload["max_steps"] == 2
    assert finalize_payload["tool_execution_count"] == 5
    state_results = [event["payload"] for event in trace_events if event["event_type"] == "state_result"]
    ingest_state_result = next(event for event in state_results if event["state"] == "ingest")
    finalize_state_result = next(event for event in state_results if event["state"] == "finalize")
    assert ingest_state_result["result"]["verify_rule_count"] == 1
    assert finalize_state_result["result"]["tool_execution_count"] == 5
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
        "finalize",
    ]


def test_default_reflect_triggers_when_observe_finds_no_progress(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-no-progress-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            rationale = _constraint_aware_rationale(runtime_feedback, repeat_reason=True)
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale=rationale,
                planned_actions=[rationale],
                tool_calls=[
                    PlannedToolCall(tool_name="read_file", tool_input={"path": "README.md"}),
                    PlannedToolCall(tool_name="search_text", tool_input={"query": "Demo", "limit": 5}),
                ],
            )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

    settings = build_settings(
        task="只读取文件不修改",
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

    assert runtime_state.progress_made is False
    assert runtime_state.changed_files == []
    assert runtime_state.failed_tool_count == 0
    assert runtime_state.reflect_triggered is True
    assert runtime_state.reflect_trigger_reason == "no_progress_after_observe"
    assert runtime_state.reflect_count == 2
    assert runtime_state.reflect_trigger_reasons == ["no_progress_after_observe", "no_progress_after_observe"]
    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.VERIFICATION_FAILED
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "reflect",
        "verify",
        "plan",
        "act",
        "observe",
        "reflect",
        "verify",
        "finalize",
    ]
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    progress_payloads = [event["payload"] for event in trace_events if event["event_type"] == "progress_observed"]
    progress_payload = progress_payloads[0]
    assert len(progress_payloads) == 2
    assert progress_payload["progress_made"] is False
    assert progress_payload["changed_files"] == []
    assert progress_payload["failed_tool_count"] == 0
    reflect_payloads = [event["payload"] for event in trace_events if event["event_type"] == "reflect_feedback"]
    assert reflect_payloads[0]["trigger"] == "no_progress_after_observe"
    assert reflect_payloads[0]["replan_constraints"]["failure_reason"] == "no_progress_after_observe"
    assert "produce_observable_file_change" in reflect_payloads[0]["replan_constraints"]["must_address"]
    assert reflect_payloads[0]["replan_constraints"]["failed_check_names"] == []
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
        "plan",
        "act",
        "observe",
        "reflect",
        "verify",
        "finalize",
    ]


def test_loop_normalizes_common_tool_input_aliases(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-alias-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale="使用真实模型常见 file_path 别名读取文件。",
                planned_actions=["读取 README.md"],
                tool_calls=[
                    PlannedToolCall(tool_name="read_file", tool_input={"file_path": "README.md"}),
                ],
            )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

    settings = build_settings(
        task="读取 README",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[{"type": "file_exists", "name": "README exists", "path": "README.md"}],
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    runtime_state = loop_module.LoopOrchestrator(trace_writer=trace_writer).run(
        settings=settings,
        config_data=_model_config(),
    )

    assert runtime_state.tool_executions[0].tool_name == "read_file"
    assert runtime_state.tool_executions[0].tool_input == {"path": "README.md"}


def test_loop_accepts_string_run_command_from_model(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-string-command-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale="使用真实模型常见字符串命令读取文件。",
                planned_actions=["运行 type README.md"],
                tool_calls=[
                    PlannedToolCall(tool_name="run_command", tool_input={"command": "type README.md"}),
                ],
            )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

    settings = build_settings(
        task="运行字符串命令",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[{"type": "file_exists", "name": "README exists", "path": "README.md"}],
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    runtime_state = loop_module.LoopOrchestrator(trace_writer=trace_writer).run(
        settings=settings,
        config_data=_model_config(),
    )

    assert runtime_state.tool_executions[0].tool_name == "run_command"
    assert runtime_state.tool_executions[0].tool_input == {"command": "type README.md"}
    assert runtime_state.tool_executions[0].tool_output["ok"] is True
    assert "# Demo" in runtime_state.tool_executions[0].tool_output["stdout"]


def test_loop_replans_after_failed_verification_and_then_passes(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-replan-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect_feedback"))
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale=(
                    "回应 verification_failed、fake_verify 和 fix_failing_verification_checks 后重规划，"
                    "再次重复相同工具序列是因为需要覆盖同一文件并重新生成 diff。"
                    if has_reflect_feedback
                    else "首轮执行常规计划。"
                ),
                planned_actions=[
                    (
                        "修复 verification_failed / fake_verify / fix_failing_verification_checks 后重新验证"
                        if has_reflect_feedback
                        else "执行首轮工具计划"
                    )
                ],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = verification_calls["count"] == 2
        return VerificationResult(
            passed=passed,
            summary="验证通过" if passed else "验证失败",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="按轮次模拟验证结果。")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="验证失败后重试",
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
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert runtime_state.iteration_count == 2
    assert runtime_state.reflect_count == 1
    assert runtime_state.reflect_trigger_reasons == ["verification_failed"]
    assert verification_calls["count"] == 2

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
        "plan",
        "act",
        "observe",
        "verify",
        "finalize",
    ]
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["details"]["iteration_count"] == 2
    assert run_finished_payload["stop_reason"]["details"]["reflect_count"] == 1


def test_second_plan_receives_runtime_feedback(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-feedback-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect_feedback"))
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale=(
                    "回应 verification_failed、fake_verify 和 fix_failing_verification_checks，"
                    "再次使用相同工具序列是因为需要覆盖同一文件并重新生成 diff。"
                    if has_reflect_feedback
                    else "test feedback"
                ),
                planned_actions=[
                    (
                        "处理 verification_failed / fake_verify / fix_failing_verification_checks 后执行反馈测试工具计划"
                        if has_reflect_feedback
                        else "执行反馈测试工具计划"
                    )
                ],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = verification_calls["count"] == 2
        return VerificationResult(
            passed=passed,
            summary="验证通过" if passed else "验证失败",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="按轮次模拟验证结果。")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="检查反馈",
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
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert len(feedbacks) == 2
    assert feedbacks[0] == {}
    assert feedbacks[1]["iteration"] == 2
    assert feedbacks[1]["previous_observation"]["progress_made"] is True
    assert feedbacks[1]["previous_verification"]["passed"] is False
    assert feedbacks[1]["previous_reflect_feedback"]["trigger"] == "verification_failed"
    assert feedbacks[1]["previous_reflect_feedback"]["verification_failure"]["failing_check_names"] == ["fake_verify"]
    assert feedbacks[1]["previous_reflect_feedback"]["replan_constraints"]["failure_reason"] == "verification_failed"
    assert feedbacks[1]["previous_reflect_feedback"]["replan_constraints"]["failed_check_names"] == ["fake_verify"]
    assert feedbacks[1]["previous_reflect_feedback"]["replan_constraints"]["avoid_exact_tool_sequence"] == [
        "apply_patch",
        "git_diff",
    ]
    assert "fix_failing_verification_checks" in feedbacks[1]["previous_reflect_feedback"]["replan_constraints"]["must_address"]
    assert feedbacks[1]["recent_tool_results"][0]["tool_name"] == "apply_patch"

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reflect_payload = next(event["payload"] for event in trace_events if event["event_type"] == "reflect_feedback")
    assert reflect_payload["trigger"] == "verification_failed"
    assert reflect_payload["verification_failure"]["failing_check_names"] == ["fake_verify"]
    assert reflect_payload["replan_constraints"]["failure_reason"] == "verification_failed"
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[0]["has_reflect_feedback"] is False
    assert model_decision_payloads[1]["has_reflect_feedback"] is True
    assert model_decision_payloads[1]["reflect_feedback_summary"]["failure_reason"] == "verification_failed"
    assert model_decision_payloads[1]["reflect_feedback_summary"]["failed_check_names"] == ["fake_verify"]
    raw_response_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_raw_response"]
    assert [payload["iteration"] for payload in raw_response_payloads] == [1, 2]
    assert all(payload["parsed_ok"] is True for payload in raw_response_payloads)


def _run_reflect_constraint_case(
    tmp_path: Path,
    monkeypatch,
    *,
    second_rationale: str,
    second_planned_actions: list[str],
    repeat_tool_sequence: bool,
) -> tuple[loop_module.RuntimeState, list[dict]]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-reflect-constraint-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect_feedback"))
            if has_reflect_feedback:
                tool_calls = [
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ]
                if not repeat_tool_sequence:
                    tool_calls = [
                        PlannedToolCall(tool_name="read_file", tool_input={"path": "README.md"}),
                        *tool_calls,
                    ]
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second decision",
                    rationale=second_rationale,
                    planned_actions=second_planned_actions,
                    tool_calls=tool_calls,
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="first decision",
                rationale="首轮执行常规计划。",
                planned_actions=["执行首轮工具计划"],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = verification_calls["count"] == 2
        return VerificationResult(
            passed=passed,
            summary="验证通过" if passed else "验证失败",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="按轮次模拟验证结果。")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="检查 reflect 约束",
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
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return runtime_state, trace_events


def test_second_plan_continues_when_reflect_constraints_are_only_partially_acknowledged(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_reflect_constraint_case(
        tmp_path,
        monkeypatch,
        second_rationale="忽略上一轮失败，直接继续。",
        second_planned_actions=["执行新计划"],
        repeat_tool_sequence=False,
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[1]["has_reflect_feedback"] is True
    assert model_decision_payloads[1]["reflect_constraints_acknowledged"] is True


def test_second_plan_allows_repeated_failed_tool_sequence_within_budget(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_reflect_constraint_case(
        tmp_path,
        monkeypatch,
        second_rationale="回应 verification_failed、fake_verify 和 fix_failing_verification_checks。",
        second_planned_actions=["修复 verification_failed / fake_verify / fix_failing_verification_checks"],
        repeat_tool_sequence=True,
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    repeated_payload = next(event["payload"] for event in trace_events if event["event_type"] == "repeated_failed_tool_sequence")
    assert repeated_payload["repeat_count"] == 1
    assert repeated_payload["allowed_repeat_count"] == 3


def test_repeated_failed_tool_sequence_blocks_after_three_retries(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize({})
    orchestrator = loop_module.LoopOrchestrator(trace_writer=trace_writer)
    runtime_state = loop_module.RuntimeState(task="repeat", task_type="general")
    runtime_state.repeated_failed_tool_sequence_count = 3
    model_decision = ModelDecision(
        provider="openai_compatible",
        model_name="fake-repeat-model",
        task_type="general",
        summary="repeat",
        rationale="没有解释",
        planned_actions=["repeat"],
        tool_calls=[
            PlannedToolCall(tool_name="read_file", tool_input={"path": "README.md"}),
        ],
    )
    runtime_feedback = {
        "previous_reflect_feedback": {
            "replan_constraints": {
                "avoid_exact_tool_sequence": ["read_file"],
            }
        }
    }

    try:
        orchestrator._validate_reflect_constraints_acknowledged(
            model_decision=model_decision,
            runtime_feedback=runtime_feedback,
            runtime_state=runtime_state,
        )
    except ModelResponseError as error:
        assert "重复了上一轮失败工具序列" in str(error)
    else:
        raise AssertionError("fourth repeated failed tool sequence should fail")


def test_second_plan_can_repeat_failed_tool_sequence_with_explanation(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_reflect_constraint_case(
        tmp_path,
        monkeypatch,
        second_rationale=(
            "回应 verification_failed、fake_verify 和 fix_failing_verification_checks，"
            "再次重复相同工具序列是因为需要覆盖同一文件后重新生成 diff。"
        ),
        second_planned_actions=["修复 verification_failed / fake_verify / fix_failing_verification_checks"],
        repeat_tool_sequence=True,
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[1]["has_reflect_feedback"] is True
    assert model_decision_payloads[1]["reflect_constraints_acknowledged"] is True


def test_loop_stops_with_model_error_when_model_config_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

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
    assert failure_payload["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "test-key" not in json.dumps(failure_payload, ensure_ascii=False)
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["code"] == "model_error"
    assert run_finished_payload["stop_reason"]["details"]["api_key_env"] == "DEEPSEEK_API_KEY"


def test_loop_records_model_response_normalized_for_planned_actions(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    monkeypatch.setenv(
        "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
        json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "读取 README",
                                    "rationale": "planned_actions 缺失时仍应执行安全的工具计划。",
                                    "tool_calls": [
                                        {
                                            "tool_name": "read_file",
                                            "tool_input": {"path": "README.md"},
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    settings = build_settings(
        task="触发 planned_actions 归一化",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[{"type": "file_exists", "name": "README exists", "path": "README.md"}],
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
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert runtime_state.model_decision is not None
    assert runtime_state.model_decision.planned_actions == ["执行工具：read_file"]
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    normalized_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_response_normalized")
    assert normalized_payload["provider"] == "openai_compatible"
    assert normalized_payload["model_name"] == "demo-model"
    assert normalized_payload["iteration"] == 1
    assert normalized_payload["notes"][0]["field_path"] == "planned_actions"
    assert normalized_payload["notes"][0]["reason"] == "missing_or_unusable_fallback_to_tool_calls"
    model_decision_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision")
    assert model_decision_payload["planned_actions"] == ["执行工具：read_file"]


def test_loop_model_error_includes_safe_raw_response_excerpt_for_invalid_tool_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    monkeypatch.setenv(
        "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
        json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "非法工具计划",
                                    "rationale": "tool_input 非对象必须失败。",
                                    "planned_actions": "读取文件",
                                    "tool_calls": [{"tool_name": "read_file", "tool_input": "README.md"}],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    settings = build_settings(
        task="触发工具计划错误",
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
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failure_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision_failed")
    assert failure_payload["error_type"] == "ModelResponseError"
    assert failure_payload["field_path"] == "tool_calls[1].tool_input"
    assert "response_excerpt" in failure_payload
    assert "非法工具计划" in failure_payload["response_excerpt"]
    assert "secret-test-key" not in json.dumps(failure_payload, ensure_ascii=False)
