from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import loop as loop_module
from config import build_settings
from model import ModelDecision, ModelTokenUsage, PlannedToolCall
from runtime_trace import TraceWriter
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


def _fake_model_response(tool_calls: list[dict] | None = None, usage: dict | None = None) -> str:
    decision = {
        "summary": "已生成真实模型决策。",
        "rationale": "按模型返回的工具计划执行。",
        "ready_to_finalize": True,
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
        {
            "choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}],
            **({"usage": usage} if usage is not None else {}),
        },
        ensure_ascii=False,
    )


def _constraint_aware_rationale(runtime_feedback: dict | None, *, repeat_reason: bool = True) -> str:
    """为测试 fake 模型生成会读取事实型 reflect 的说明文本。"""
    reflect_feedback = (runtime_feedback or {}).get("previous_reflect", {})
    if not reflect_feedback:
        return "首轮执行常规计划。"
    parts = [
        " ".join(str(item) for item in reflect_feedback.get("signals", [])),
        " ".join(str(item) for item in (runtime_feedback or {}).get("previous_cross_round_plan", [])),
    ]
    suffix = "，再次重复相同工具序列是因为测试需要保持同一工具计划。" if repeat_reason else ""
    return "读取 previous_reflect 事实：" + " ".join(item for item in parts if item).strip() + suffix


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
    assert runtime_state.reflect_trigger_reason == "after_act"
    assert runtime_state.reflect_count == 2
    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.VERIFICATION_FAILED
    assert runtime_state.stop_reason.details["verification_failure"]["failing_check_names"] == ["说明文件可读"]
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "reflect",
        "plan",
        "act",
        "reflect",
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
        "reflect",
        "plan",
        "act",
        "reflect",
        "verify",
        "finalize",
    ]


def test_loop_records_model_decision_and_uses_planned_actions(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(
        "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
        _fake_model_response(usage={"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}),
    )

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
    assert runtime_state.changed_files == ["run_evidence.md"]
    assert runtime_state.failed_tool_count == 0
    assert runtime_state.reflect_triggered is True
    assert runtime_state.iteration_count == 1
    assert runtime_state.max_steps == 2
    assert runtime_state.token_usage == {
        "prompt_tokens": 40,
        "completion_tokens": 10,
        "total_tokens": 50,
        "request_count": 1,
        "complete": True,
        "missing_usage_count": 0,
    }
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "reflect",
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
    assert raw_response_payload["token_usage"]["total_tokens"] == 50
    assert json.loads(raw_response_payload["content"])["planned_actions"] == ["执行模型工具计划"]
    assert not any(event["event_type"] == "progress_observed" for event in trace_events)
    reflect_payload = next(event["payload"] for event in trace_events if event["event_type"] == "reflect_feedback")
    assert reflect_payload["observation"]["changed_files"] == ["run_evidence.md"]
    assert reflect_payload["observation"]["failed_tool_count"] == 0
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
    assert finalize_payload["changed_files"] == ["run_evidence.md"]
    assert finalize_payload["failed_tool_count"] == 0
    assert finalize_payload["reflect_count"] == 1
    assert finalize_payload["iteration_count"] == 1
    assert finalize_payload["max_steps"] == 2
    assert finalize_payload["tool_execution_count"] == 5
    assert finalize_payload["token_usage"]["total_tokens"] == 50
    assert finalize_payload["token_usage"]["complete"] is True
    state_results = [event["payload"] for event in trace_events if event["event_type"] == "state_result"]
    ingest_state_result = next(event for event in state_results if event["state"] == "ingest")
    finalize_state_result = next(event for event in state_results if event["state"] == "finalize")
    assert ingest_state_result["result"]["verify_rule_count"] == 1
    assert finalize_state_result["result"]["tool_execution_count"] == 5
    plan_state_result = next(event for event in state_results if event["state"] == "plan")
    assert plan_state_result["result"]["token_usage"]["total_tokens"] == 50
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["details"]["token_usage"]["total_tokens"] == 50
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
        "reflect",
        "verify",
        "finalize",
    ]


def test_loop_verification_uses_system_diff_snapshot_instead_of_model_git_diff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-system-diff-snapshot-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="apply patch and run an irrelevant git_diff",
                rationale="验证层应自动生成自己的 diff 快照，而不是依赖模型这次 git_diff 的 paths。",
                planned_actions=["修改 run_evidence.md，然后让 verify 自己做 diff 校验"],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["unrelated.md"]}),
                ],
            )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

    settings = build_settings(
        task="verify should use system diff snapshot",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[
            {"type": "file_exists", "name": "run evidence exists", "path": "run_evidence.md"},
            {"type": "diff_contains_file", "name": "system diff includes evidence file", "path": "run_evidence.md"},
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

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert runtime_state.verification_result is not None
    assert runtime_state.verification_result.passed is True
    assert runtime_state.verification_result.details["verification_diff_snapshot"]["changed_file_count"] == 1

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verification_diff_payload = next(
        event["payload"] for event in trace_events if event["event_type"] == "verification_diff_snapshot"
    )
    assert verification_diff_payload["tool_name"] == "git_diff"
    assert verification_diff_payload["tool_output"]["changed_file_count"] == 1
    assert verification_diff_payload["tool_output"]["diffs"][0]["path"] == "run_evidence.md"

    verification_payload = next(event["payload"] for event in trace_events if event["event_type"] == "verification_result")
    diff_check = next(check for check in verification_payload["checks"] if check["name"] == "system diff includes evidence file")
    assert diff_check["passed"] is True


def test_default_reflect_records_read_only_round_without_no_diff_signal(tmp_path: Path, monkeypatch) -> None:
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

    assert runtime_state.changed_files == []
    assert runtime_state.failed_tool_count == 0
    assert runtime_state.reflect_triggered is True
    assert runtime_state.reflect_trigger_reason == "after_act"
    assert runtime_state.reflect_count == 2
    assert runtime_state.reflect_trigger_reasons == ["after_act", "after_act"]
    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.VERIFICATION_FAILED
    assert runtime_state.completed_states == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "reflect",
        "plan",
        "act",
        "reflect",
        "verify",
        "finalize",
    ]
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert not any(event["event_type"] == "progress_observed" for event in trace_events)
    reflect_payloads = [event["payload"] for event in trace_events if event["event_type"] == "reflect_feedback"]
    assert reflect_payloads[0]["trigger"] == "after_act"
    assert reflect_payloads[0]["signals"] == []
    assert reflect_payloads[0]["observation"]["changed_files"] == []
    assert reflect_payloads[0]["observation"]["failed_tool_count"] == 0
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
        "reflect",
        "plan",
        "act",
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


def test_loop_stops_with_model_error_when_tool_input_has_extra_field(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-invalid-tool-schema-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale="错误地给 read_file 传入 limit。",
                planned_actions=["读取 README.md"],
                tool_calls=[
                    PlannedToolCall(tool_name="read_file", tool_input={"path": "README.md", "limit": 20}),
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

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.MODEL_ERROR
    assert runtime_state.tool_executions == []
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failed_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision_failed")
    assert failed_payload["error_type"] == "ModelResponseError"
    assert "read_file" in failed_payload["error_message"]
    assert "limit" in failed_payload["error_message"]


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
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect"))
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
        passed = True
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
    assert runtime_state.reflect_count == 2
    assert runtime_state.reflect_trigger_reasons == ["after_act", "after_act"]
    assert verification_calls["count"] == 1

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
        "reflect",
        "plan",
        "act",
        "reflect",
        "verify",
        "finalize",
    ]
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["details"]["iteration_count"] == 2
    assert run_finished_payload["stop_reason"]["details"]["reflect_count"] == 2


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
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect"))
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
        passed = True
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
    assert "iteration" not in feedbacks[1]
    assert "remaining_iterations" not in feedbacks[1]
    assert "max_steps" not in feedbacks[1]
    assert "iteration" not in feedbacks[1]["previous_reflect"]
    assert "iteration" not in feedbacks[1]["previous_reflect"]["observation"]
    assert feedbacks[1]["previous_reflect"]["trigger"] == "after_act"
    assert "verification" not in feedbacks[1]["previous_reflect"]
    assert feedbacks[1]["previous_reflect"]["recent_tool_results"][0]["tool_name"] == "apply_patch"

    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reflect_payload = next(event["payload"] for event in trace_events if event["event_type"] == "reflect_feedback")
    assert reflect_payload["trigger"] == "after_act"
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[0]["has_reflect_feedback"] is False
    assert model_decision_payloads[1]["has_reflect_feedback"] is True
    assert model_decision_payloads[1]["reflect_feedback_summary"]["failed_tool_count"] == 0
    raw_response_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_raw_response"]
    assert [payload["iteration"] for payload in raw_response_payloads] == [1, 2]
    assert all(payload["parsed_ok"] is True for payload in raw_response_payloads)


def test_runtime_feedback_includes_read_file_excerpt_after_old_text_not_found(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "todo_app.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def format_task(task):",
                "    title = task.get('title', '')",
                '    status = "todo" if task.get("done") else "done"',
                "    return f\"{status}: {title}\"",
                "",
                "def main():",
                "    print(format_task({'title': 'demo', 'done': False}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-old-text-feedback-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            has_feedback = bool(runtime_feedback)
            if has_feedback:
                rationale = (
                    "回应 verification_failed、fake_verify、fix_failing_verification_checks、"
                    "fix_failed_tool_or_command、use_exact_old_text_from_read_file，"
                    "根据 read_file 片段复制真实 old_text 后重试。"
                )
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="使用 read_file 证据修复 old_text。",
                    rationale=rationale,
                    planned_actions=[rationale],
                    tool_calls=[
                        PlannedToolCall(
                            tool_name="apply_patch",
                            tool_input={
                                "path": "todo_app.py",
                                "old_text": '    status = "todo" if task.get("done") else "done"',
                                "new_text": '    status = "done" if task.get("done") else "todo"',
                            },
                        ),
                        PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["todo_app.py"]}),
                    ],
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="首轮尝试修复状态显示。",
                rationale="先读取文件，再尝试 patch。",
                planned_actions=["读取 todo_app.py 并修复状态显示"],
                tool_calls=[
                    PlannedToolCall(tool_name="read_file", tool_input={"path": "todo_app.py"}),
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={
                            "path": "todo_app.py",
                            "old_text": '    status = "[done]" if task["done"] else "[todo]"',
                            "new_text": '    status = "done" if task.get("done") else "todo"',
                        },
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["todo_app.py"]}),
                ],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="验证通过" if passed else "验证失败",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="按轮次模拟验证结果。")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="修复 todo 状态显示",
        task_type="bug_fix",
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
    second_feedback = feedbacks[1]
    previous_reflect = second_feedback["previous_reflect"]
    read_summary = next(
        item for item in previous_reflect["recent_tool_results"] if item["tool_name"] == "read_file"
    )
    assert read_summary["path"] == "todo_app.py"
    assert read_summary["line_count"] == 9
    assert read_summary["excerpt_reason"] == "old_text_not_found_candidate"
    assert read_summary["excerpt_line_start"] >= 1
    assert read_summary["excerpt_line_end"] <= 9
    assert 'status = "todo" if task.get("done") else "done"' in read_summary["content_excerpt"]

    patch_summary = next(
        item for item in previous_reflect["recent_tool_results"] if item["tool_name"] == "apply_patch"
    )
    assert patch_summary["path"] == "todo_app.py"
    assert patch_summary["error"] == "old_text_not_found"
    assert 'status = "[done]" if task["done"] else "[todo]"' in patch_summary["failed_old_text_excerpt"]
    assert 'status = "done" if task.get("done") else "todo"' in patch_summary["new_text_excerpt"]

    assert "previous_reflect_feedback" not in second_feedback
    assert "replan_constraints" not in previous_reflect
    failed_tool = previous_reflect["failed_tools"][0]
    assert failed_tool["error"] == "old_text_not_found"
    assert failed_tool["failed_old_text_excerpt"] == patch_summary["failed_old_text_excerpt"]


def test_runtime_feedback_includes_full_small_read_file_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "small.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-small-read-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            if runtime_feedback:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second",
                    rationale="已经看到完整小文件内容。",
                    planned_actions=["查看 diff"],
                    tool_calls=[PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["small.py"]})],
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="first",
                rationale="读取小文件。",
                planned_actions=["读取 small.py"],
                tool_calls=[PlannedToolCall(tool_name="read_file", tool_input={"path": "small.py"})],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="ok" if passed else "retry",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="读取小文件",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    loop_module.LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=_model_config())

    read_summary = feedbacks[1]["previous_reflect"]["recent_tool_results"][0]
    assert read_summary["tool_name"] == "read_file"
    assert read_summary["content_mode"] == "full"
    assert read_summary["content_truncated"] is False
    assert read_summary["read_coverage"] == "1-2"
    assert read_summary["content_excerpt"] == "def main():\n    return 'ok'\n"
    assert read_summary["excerpt_reason"] == "full_file"


def test_runtime_feedback_includes_large_read_file_structure_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    lines = ["class LargeService:", "    pass", ""]
    lines.extend(f"def handler_{index}():  # {'x' * 80}" for index in range(1, 230))
    (repo_root / "large.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-large-read-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            if runtime_feedback:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second",
                    rationale="已经看到大文件结构摘要。",
                    planned_actions=["按范围读取"],
                    tool_calls=[
                        PlannedToolCall(
                            tool_name="read_file_range",
                            tool_input={"path": "large.py", "start_line": 1, "end_line": 5},
                        )
                    ],
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="first",
                rationale="读取大文件。",
                planned_actions=["读取 large.py"],
                tool_calls=[PlannedToolCall(tool_name="read_file", tool_input={"path": "large.py"})],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="ok" if passed else "retry",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="读取大文件",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    loop_module.LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=_model_config())

    read_summary = feedbacks[1]["previous_reflect"]["recent_tool_results"][0]
    assert read_summary["tool_name"] == "read_file"
    assert read_summary["content_mode"] == "structure_summary"
    assert read_summary["content_truncated"] is True
    assert "read_coverage" not in read_summary
    assert read_summary["excerpt_reason"] == "large_file_structure_summary"
    assert read_summary["structure_summary"][0]["kind"] == "class"
    assert read_summary["structure_summary"][0]["name"] == "LargeService"
    assert read_summary["content_excerpt"] == ""


def test_runtime_feedback_includes_explicit_structure_summary_tool_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text(
        "\n".join(
            [
                "class Service:",
                "    pass",
                "",
                "def handle_task(task_id):",
                "    return task_id",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-explicit-structure-summary-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            if runtime_feedback:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second",
                    rationale="已经看到显式结构摘要。",
                    planned_actions=["结束"],
                    tool_calls=[],
                    ready_to_finalize=True,
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="first",
                rationale="先看结构摘要。",
                planned_actions=["读取结构摘要"],
                tool_calls=[PlannedToolCall(tool_name="read_file_structure_summary", tool_input={"path": "app.py"})],
            )

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=True,
            summary="ok",
            checks=[VerificationCheck(name="fake_verify", passed=True, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="读取显式结构摘要",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    loop_module.LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=_model_config())

    read_summary = feedbacks[1]["previous_reflect"]["recent_tool_results"][0]
    assert read_summary["tool_name"] == "read_file_structure_summary"
    assert read_summary["content_mode"] == "structure_summary"
    assert read_summary["excerpt_reason"] == "explicit_structure_summary"
    assert read_summary["content_excerpt"] == ""
    assert any(item["name"] == "handle_task" and item["line_number"] == 4 for item in read_summary["structure_summary"])


def test_runtime_feedback_includes_range_and_replace_lines_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-range-edit-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            if runtime_feedback:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second",
                    rationale="已经收到 range 与 replace_lines 结果。",
                    planned_actions=["查看 diff"],
                    tool_calls=[PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["app.py"]})],
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="first",
                rationale="先读取范围，再按行替换。",
                planned_actions=["读取范围并替换行"],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="read_file_range",
                        tool_input={"path": "app.py", "start_line": 1, "end_line": 2},
                    ),
                    PlannedToolCall(
                        tool_name="replace_lines",
                        tool_input={"path": "app.py", "start_line": 2, "end_line": 2, "new_text": "TWO"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["app.py"]}),
                ],
            )

    verification_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verification_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="ok" if passed else "retry",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="按行替换",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
    )
    run_dir = Path(settings.output_root) / settings.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(run_dir=run_dir)
    trace_writer.initialize(settings.to_dict())

    loop_module.LoopOrchestrator(trace_writer=trace_writer).run(settings=settings, config_data=_model_config())

    recent_tool_results = feedbacks[1]["previous_reflect"]["recent_tool_results"]
    range_summary = next(item for item in recent_tool_results if item["tool_name"] == "read_file_range")
    replace_summary = next(item for item in recent_tool_results if item["tool_name"] == "replace_lines")
    assert range_summary["content_mode"] == "range"
    assert range_summary["content_excerpt"] == "one\ntwo"
    assert range_summary["read_coverage"] == "1-2"
    assert replace_summary["action"] == "replace_lines"
    assert replace_summary["start_line"] == 2
    assert replace_summary["end_line"] == 2
    assert replace_summary["line_count_before"] == 3
    assert replace_summary["line_count_after"] == 3


def test_runtime_feedback_keeps_last_five_file_context_snippets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("\n".join(f"line {index}" for index in range(1, 80)) + "\n", encoding="utf-8")
    feedbacks: list[dict] = []
    read_ranges = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 30)]

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-file-context-cache-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            call_index = len(feedbacks) - 1
            start_line, end_line = read_ranges[min(call_index, len(read_ranges) - 1)]
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="读取下一段",
                rationale="累计同文件读取片段。",
                planned_actions=["读取 app.py 的一个范围"],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="read_file_range",
                        tool_input={"path": "app.py", "start_line": start_line, "end_line": end_line},
                    )
                ],
            )

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=False,
            summary="继续读取",
            checks=[VerificationCheck(name="fake_verify", passed=False, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="累计读取上下文",
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
        config_data={"runtime": {"max_steps": 6}, **_model_config()},
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.VERIFICATION_FAILED
    assert len(feedbacks) == 6
    final_cache = runtime_state.reflect_feedback["file_context_cache"]["app.py"]
    assert final_cache["covered_ranges"] == ["6-10", "11-15", "16-20", "21-25", "26-30"]
    assert len(final_cache["snippets"]) == 5
    assert final_cache["snippets"][0]["content_excerpt"].startswith("line 6")
    assert final_cache["snippets"][-1]["content_excerpt"].startswith("line 26")
    previous_cache = feedbacks[-1]["previous_reflect"]["file_context_cache"]["app.py"]
    assert previous_cache["covered_ranges"] == ["1-5", "6-10", "11-15", "16-20", "21-25"]


def test_runtime_feedback_marks_file_context_cache_stale_after_edit_and_refreshes_after_reread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-stale-cache-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            round_index = len(feedbacks)
            if round_index == 1:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="first",
                    rationale="先读取原文件。",
                    planned_actions=["读取 app.py"],
                    tool_calls=[PlannedToolCall(tool_name="read_file", tool_input={"path": "app.py"})],
                )
            if round_index == 2:
                return ModelDecision(
                    provider=self.provider,
                    model_name=self.model_name,
                    task_type=task_type,
                    summary="second",
                    rationale="编辑文件，让旧缓存失效。",
                    planned_actions=["修改 app.py"],
                    tool_calls=[
                        PlannedToolCall(
                            tool_name="replace_lines",
                            tool_input={"path": "app.py", "start_line": 2, "end_line": 2, "new_text": "TWO"},
                        )
                    ],
                )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="third",
                rationale="重读文件，刷新缓存。",
                planned_actions=["重新读取 app.py"],
                tool_calls=[PlannedToolCall(tool_name="read_file", tool_input={"path": "app.py"})],
                ready_to_finalize=True,
            )

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=True,
            summary="ok",
            checks=[VerificationCheck(name="fake_verify", passed=True, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="验证文件缓存失效与刷新",
        task_type="bug_fix",
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
        config_data={"runtime": {"max_steps": 3}, **_model_config()},
    )

    stale_cache = feedbacks[2]["previous_reflect"]["file_context_cache"]["app.py"]
    assert stale_cache["cache_status"] == "stale"
    assert stale_cache["stale_reason"] == "edited_by_replace_lines"
    assert stale_cache["snippets"] == []
    assert stale_cache["stale_snippet_count"] == 1
    assert stale_cache["stale_covered_ranges"] == ["1-3"]
    assert feedbacks[2]["previous_reflect"]["stale_file_paths"] == ["app.py"]
    assert feedbacks[2]["previous_reflect"]["recent_file_context_invalidations"][0]["path"] == "app.py"

    fresh_cache = runtime_state.reflect_feedback["file_context_cache"]["app.py"]
    assert fresh_cache["cache_status"] == "fresh"
    assert fresh_cache["stale_reason"] == ""
    assert fresh_cache["covered_ranges"] == ["1-3"]
    assert fresh_cache["snippets"][0]["content_excerpt"] == "one\nTWO\nthree\n"
    assert runtime_state.reflect_feedback["stale_file_paths"] == []


def _run_factual_reflect_feedback_case(
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
            has_reflect_feedback = bool((runtime_feedback or {}).get("previous_reflect"))
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
        passed = True
        return VerificationResult(
            passed=passed,
            summary="验证通过" if passed else "验证失败",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="按轮次模拟验证结果。")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    settings = build_settings(
        task="检查 reflect 事实反馈",
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


def test_second_plan_continues_with_factual_reflect_feedback(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_factual_reflect_feedback_case(
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
    assert "reflect_constraints_acknowledged" not in model_decision_payloads[1]


def test_second_plan_does_not_emit_repeated_sequence_constraint_event(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_factual_reflect_feedback_case(
        tmp_path,
        monkeypatch,
        second_rationale="回应 verification_failed、fake_verify 和 fix_failing_verification_checks。",
        second_planned_actions=["修复 verification_failed / fake_verify / fix_failing_verification_checks"],
        repeat_tool_sequence=True,
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert not any(event["event_type"] == "repeated_failed_tool_sequence" for event in trace_events)


def test_second_plan_can_repeat_tool_sequence_without_harness_hard_constraint(tmp_path: Path, monkeypatch) -> None:
    runtime_state, trace_events = _run_factual_reflect_feedback_case(
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
    assert "reflect_constraints_acknowledged" not in model_decision_payloads[1]


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


def test_loop_aggregates_token_usage_across_iterations_and_marks_missing_usage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    decide_call = {"count": 0}

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-token-usage-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            decide_call["count"] += 1
            token_usage = (
                ModelTokenUsage(prompt_tokens=30, completion_tokens=12, total_tokens=42, available=True)
                if decide_call["count"] == 1
                else ModelTokenUsage()
            )
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale="first round has usage, second round misses usage",
                planned_actions=["执行工具：read_file"],
                tool_calls=[PlannedToolCall(tool_name="read_file", tool_input={"path": "README.md"})],
                token_usage=token_usage,
            )

    verify_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verify_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="ok" if passed else "fail",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="fake")],
            details={"verification_mode": "fake"},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)

    settings = build_settings(
        task="累计 token usage",
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
        config_data={**_model_config(), "runtime": {"max_steps": 2}},
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert runtime_state.token_usage == {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "total_tokens": 42,
        "request_count": 2,
        "complete": False,
        "missing_usage_count": 1,
    }
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[0]["token_usage"]["available"] is True
    assert model_decision_payloads[1]["token_usage"]["available"] is False
    assert model_decision_payloads[1]["run_token_usage"]["missing_usage_count"] == 1
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["details"]["token_usage"]["complete"] is False


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


def test_second_plan_receives_previous_cross_round_plan(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    feedbacks: list[dict] = []

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-cross-round-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            feedbacks.append(runtime_feedback or {})
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake decision",
                rationale=_constraint_aware_rationale(runtime_feedback),
                planned_actions=["本轮执行可观察文件修改"],
                cross_round_plan=["如果验证失败，下一轮读取 README.md 后继续修复。"],
                tool_calls=[
                    PlannedToolCall(
                        tool_name="apply_patch",
                        tool_input={"path": "run_evidence.md", "old_text": None, "new_text": "# Run Evidence\n"},
                    ),
                    PlannedToolCall(tool_name="git_diff", tool_input={"paths": ["run_evidence.md"]}),
                ],
            )

    verify_calls = {"count": 0}

    def fake_verification(*, settings, tool_executions):
        verify_calls["count"] += 1
        passed = True
        return VerificationResult(
            passed=passed,
            summary="ok" if passed else "fail",
            checks=[VerificationCheck(name="fake_verify", passed=passed, detail="fake")],
            details={},
        )

    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)
    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())

    settings = build_settings(
        task="验证跨轮计划进入下一轮 feedback",
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
        config_data={**_model_config(), "runtime": {"max_steps": 2}},
    )

    assert runtime_state.stop_reason is not None
    assert runtime_state.stop_reason.code == loop_module.StopReasonCode.COMPLETED
    assert feedbacks[0] == {}
    assert feedbacks[1]["previous_cross_round_plan"] == ["如果验证失败，下一轮读取 README.md 后继续修复。"]
    trace_events = [
        json.loads(line)
        for line in trace_writer.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model_decision_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_decision"]
    assert model_decision_payloads[0]["cross_round_plan"] == ["如果验证失败，下一轮读取 README.md 后继续修复。"]
def test_loop_injects_refactor_runtime_rule_into_context_snapshot(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "task_board.py").write_text("from task_board.query_engine import render_task_list\n", encoding="utf-8")
    package_dir = repo_root / "task_board"
    package_dir.mkdir()
    (package_dir / "query_engine.py").write_text(
        "\n".join(
            [
                "from typing import Any",
                "",
                "def collect_matching_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:",
                "    return list(tasks)",
                "",
                "def collect_export_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:",
                "    return list(tasks)",
                "",
                "def render_task_list(tasks: list[dict[str, Any]]) -> str:",
                "    return str(len(tasks))",
                "",
                "def render_export_list(tasks: list[dict[str, Any]]) -> str:",
                "    return str(len(tasks))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    captured = {}

    class FakeAdapter:
        provider = "openai_compatible"
        model_name = "fake-refactor-runtime-rule-model"

        def decide(self, *, task, task_type, context_snapshot, config_data, runtime_feedback=None):
            captured["context_snapshot"] = context_snapshot.to_dict()
            return ModelDecision(
                provider=self.provider,
                model_name=self.model_name,
                task_type=task_type,
                summary="fake refactor decision",
                rationale="inspect refactor runtime rules",
                planned_actions=["inspect refactor runtime rules"],
                tool_calls=[],
            )

    def fake_verification(*, settings, tool_executions):
        return VerificationResult(
            passed=True,
            summary="验证通过。",
            checks=[VerificationCheck(name="verification passed", passed=True, detail="ok")],
            details={},
        )

    monkeypatch.setattr(loop_module, "build_model_adapter", lambda config_data: FakeAdapter())
    monkeypatch.setattr(loop_module, "build_phase_4_verification", fake_verification)

    settings = build_settings(
        task="重构 task_board/query_engine.py，共享 filter-and-sort helper",
        task_type="refactor",
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

    assert runtime_state.verification_result is not None
    assert runtime_state.verification_result.passed is True
    runtime_rule_entries = captured["context_snapshot"]["memory_context"]["runtime_rule_entries"]
    compat_rule = next(item for item in runtime_rule_entries if item["title"] == "兼容式重构优先原则")
    assert "未验证通过前不要删除旧函数" in compat_rule["summary"]
    assert "默认允许保留旧函数" in compat_rule["summary"]
