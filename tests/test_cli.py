from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import build_settings
from runner import execute_initial_run


def test_cli_creates_run_artifacts(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    # 先放一个和任务相关的说明文件，方便验证 Phase 5 的文件召回是否真的选中了它。
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这个仓库用于创建脚手架和验证最小 agent 流程。\n",
        encoding="utf-8",
    )
    long_lines = ["# 长说明"] + [f"第{i}行：这里继续讨论创建脚手架的实现细节。" for i in range(1, 55)]
    (repo_root / "LONG_GUIDE.md").write_text("\n".join(long_lines) + "\n", encoding="utf-8")
    (repo_root / "DIRECTORY_GUIDE.md").write_text(
        "# 目录说明\n\n这个文件主要介绍目录结构。\n",
        encoding="utf-8",
    )

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
        "verify",
        "reflect",
        "plan",
        "act",
        "observe",
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
        "search_text",
        "apply_patch",
        "read_file",
        "run_command",
        "git_diff",
    ]

    model_decision_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision")
    assert model_decision_payload["provider"] == "openai_compatible"
    assert model_decision_payload["model_name"] == "deepseek-v4-flash"
    assert model_decision_payload["planned_actions"][0].startswith("执行测试工具计划")
    assert "fix_failing_verification_checks" in model_decision_payload["planned_actions"][0]
    raw_response_payloads = [event["payload"] for event in trace_events if event["event_type"] == "model_raw_response"]
    assert len(raw_response_payloads) == 2
    assert raw_response_payloads[0]["provider"] == "openai_compatible"
    assert raw_response_payloads[0]["model_name"] == "deepseek-v4-flash"
    assert raw_response_payloads[0]["iteration"] == 1
    assert raw_response_payloads[0]["parsed_ok"] is True

    tool_results = [event["payload"] for event in trace_events if event["event_type"] == "tool_result"]
    assert len(tool_results) == 10
    assert tool_results[1]["tool_output"]["ok"] is True
    assert tool_results[2]["tool_output"]["content"].startswith("# Run Evidence")
    assert tool_results[3]["tool_output"]["stdout"].strip() == "# Run Evidence"
    assert tool_results[4]["tool_output"]["changed_file_count"] == 1
    assert "run_evidence.md" in tool_results[4]["tool_output"]["diffs"][0]["path"]

    progress_events = [event["payload"] for event in trace_events if event["event_type"] == "progress_observed"]
    assert len(progress_events) == 2
    assert progress_events[0]["progress_made"] is True
    assert progress_events[0]["changed_files"] == ["run_evidence.md"]
    assert progress_events[0]["failed_tool_count"] == 0

    verification_events = [event["payload"] for event in trace_events if event["event_type"] == "verification_result"]
    assert len(verification_events) == 2
    assert verification_events[0]["passed"] is False
    assert verification_events[0]["details"]["verification_mode"] == "missing_task_verification"
    assert verification_events[0]["checks"][0]["name"] == "task_verification_configured"

    memory_search_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_search_result"]
    assert len(memory_search_events) == 1
    assert memory_search_events[0]["query"] == "general:创建脚手架"
    assert memory_search_events[0]["runtime_rule_count"] >= 1
    assert memory_search_events[0]["long_term_count"] == 0
    assert memory_search_events[0]["suppressed_long_term_count"] == 0
    assert memory_search_events[0]["matched_count"] >= 1

    memory_entry_written_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_entry_written"]
    assert memory_entry_written_events == []

    memory_write_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_write_result"]
    assert len(memory_write_events) == 1
    assert memory_write_events[0]["written"] is False
    assert memory_write_events[0]["store_path"].endswith(".agent_memory\\long_term_memory.jsonl")

    context_events = [event["payload"] for event in trace_events if event["event_type"] == "context_snapshot"]
    assert len(context_events) == 1
    assert context_events[0]["task_context"]["task"] == "创建脚手架"
    assert context_events[0]["repo_context"]["candidate_file_count"] >= 3
    assert context_events[0]["repo_context"]["selected_file_count"] == 3
    assert context_events[0]["repo_context"]["clipped_file_count"] >= 1
    assert context_events[0]["repo_context"]["total_original_lines"] >= context_events[0]["repo_context"]["total_selected_lines"]
    assert context_events[0]["memory_context"]["enabled"] is True
    assert context_events[0]["memory_context"]["query"] == "general:创建脚手架"
    assert context_events[0]["memory_context"]["source"] == "runtime_memory_manager"
    assert len(context_events[0]["memory_context"]["matched_entries"]) >= 1
    assert len(context_events[0]["memory_context"]["runtime_rule_entries"]) >= 1
    assert context_events[0]["memory_context"]["long_term_entries"] == []
    assert context_events[0]["memory_context"]["suppressed_long_term_entries"] == []
    assert context_events[0]["memory_context"]["conflict_evidence"] == []
    assert context_events[0]["memory_context"]["diagnostic_labels"] == []
    selected_files = context_events[0]["repo_context"]["selected_files"]
    selected_by_path = {item["path"]: item for item in selected_files}
    assert selected_by_path["README.md"]["injection_mode"] == "original"
    assert selected_by_path["README.md"]["included_line_count"] >= 1
    assert selected_by_path["README.md"]["was_clipped"] is False
    assert "# 项目说明" in selected_by_path["README.md"]["injection_content"]
    assert selected_by_path["LONG_GUIDE.md"]["injection_mode"] == "summary"
    assert selected_by_path["LONG_GUIDE.md"]["was_clipped"] is True
    assert "内容摘要：" in selected_by_path["LONG_GUIDE.md"]["injection_content"]
    assert selected_by_path["LONG_GUIDE.md"]["included_line_count"] == 8
    assert selected_by_path["DIRECTORY_GUIDE.md"]["injection_mode"] == "index"
    assert "索引提示：" in selected_by_path["DIRECTORY_GUIDE.md"]["injection_content"]

    evidence_path = repo_root / "run_evidence.md"
    assert evidence_path.exists()
    assert "当前情况：已记录到 真实 loop 运行证据。" in evidence_path.read_text(encoding="utf-8")

    memory_store_path = repo_root / ".agent_memory" / "long_term_memory.jsonl"
    assert not memory_store_path.exists()

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "`finalize`" in report_text
    assert "## 反思反馈" in report_text
    assert "## 模型返回摘要" in report_text
    assert "原始返回：见 `trace.jsonl` 中的 `model_raw_response` 事件。" in report_text
    assert "reflect：已触发" in report_text
    assert "## 进展观察" in report_text
    assert "是否观察到进展：是" in report_text
    assert "## 上下文摘要" in report_text
    assert "`README.md`" in report_text
    assert "`LONG_GUIDE.md`" in report_text
    assert "是否裁剪：是" in report_text
    assert "选中文件数：`3`" in report_text
    assert "memory：已启用" in report_text
    assert "长期 memory `0` 条" in report_text
    assert "## 工具调用摘要" in report_text
    assert "## 验证结果" in report_text
    assert "## Memory 写入" in report_text
    assert "## Sandbox 清理" in report_text
    assert "写入状态：未写入" in report_text
    assert "验证状态：未通过" in report_text
    assert "`apply_patch`：成功" in report_text


def test_cli_deletes_sandbox_after_success_by_default(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里用于验证 sandbox 默认清理策略。\n",
        encoding="utf-8",
    )

    eval_task_file = tmp_path / "eval_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "sandbox_cleanup_default",
                        "task": "创建脚手架",
                        "task_type": "general",
                        "verify_rules": [
                            {"type": "file_exists", "name": "run evidence exists", "path": "run_evidence.md"}
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--eval-task-file",
        str(eval_task_file),
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    summary_data = json.loads((output_root / "eval-eval_batch" / "summary.json").read_text(encoding="utf-8"))
    run_dir = Path(summary_data["runs"][0]["run_dir"])
    snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    sandbox_dir = Path(snapshot["sandbox_dir"])
    assert sandbox_dir.parent == repo_root.resolve() / ".agent_sandboxes"
    assert Path(snapshot["repo_root"]) == sandbox_dir / "repo"
    assert not sandbox_dir.exists()

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cleanup_payload = next(event["payload"] for event in trace_events if event["event_type"] == "sandbox_cleanup_result")
    assert cleanup_payload["attempted"] is True
    assert cleanup_payload["kept"] is False
    assert cleanup_payload["retention_policy"] == "delete_on_success"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "保留策略：`delete_on_success`" in report_text
    assert "清理结果：已删除" in report_text


def test_cli_keeps_sandbox_after_failed_verify_command_under_default_policy(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里用于验证失败后保留 sandbox。\n",
        encoding="utf-8",
    )

    eval_task_file = tmp_path / "eval_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "sandbox_keep_on_failed_verify",
                        "task": "创建脚手架",
                        "task_type": "general",
                        "verify_commands": [[sys.executable, "-c", "raise SystemExit(1)"]],
                        "expectation": {
                            "passed": False,
                            "outcome": "failed_verification",
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--eval-task-file",
        str(eval_task_file),
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    summary_data = json.loads((output_root / "eval-eval_batch" / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["success_count"] == 0
    assert summary_data["outcome_counts"] == {"failed_verification": 1}
    assert summary_data["failure_taxonomy_counts"] == {"verification:verify_command_returncode": 1}

    run_dir = Path(summary_data["runs"][0]["run_dir"])
    snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    sandbox_dir = Path(snapshot["sandbox_dir"])
    assert sandbox_dir.parent == repo_root.resolve() / ".agent_sandboxes"
    assert Path(snapshot["repo_root"]) == sandbox_dir / "repo"
    assert sandbox_dir.exists()
    assert (sandbox_dir / "repo").exists()

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verification_payload = next(event["payload"] for event in trace_events if event["event_type"] == "verification_result")
    assert verification_payload["passed"] is False
    assert verification_payload["details"]["verification_mode"] == "task_verify_commands"
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["code"] == "verification_failed"
    assert run_finished_payload["stop_reason"]["details"]["verification_failure"]["failed_commands"][0]["returncode"] == 1
    cleanup_payload = next(event["payload"] for event in trace_events if event["event_type"] == "sandbox_cleanup_result")
    assert cleanup_payload["attempted"] is False
    assert cleanup_payload["kept"] is True
    assert cleanup_payload["retention_policy"] == "delete_on_success"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "清理结果：已保留" in report_text


def test_cli_runs_sample_batch_and_comparison_smoke(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n\n用于 sample batch smoke。\n", encoding="utf-8")

    eval_command = [
        sys.executable,
        "-m",
        "cli",
        "--eval-task-file",
        str(Path.cwd() / "eval_tasks" / "sample_batch.json"),
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    eval_result = run(eval_command, capture_output=True, text=True, check=False, env=env)

    assert eval_result.returncode == 0, eval_result.stderr
    eval_summary_path = output_root / "eval-sample_batch" / "summary.json"
    eval_summary = json.loads(eval_summary_path.read_text(encoding="utf-8"))
    assert eval_summary["task_count"] == 5
    assert eval_summary["success_count"] == 5
    assert eval_summary["failure_taxonomy_counts"] == {}
    assert eval_summary["failure_taxonomy_tag_counts"] == {}
    eval_summary_text = (output_root / "eval-sample_batch" / "summary.md").read_text(encoding="utf-8")
    assert "## Failure Taxonomy" in eval_summary_text
    assert "## Reflect 原因" in eval_summary_text

    comparison_output_root = tmp_path / "comparison_runs"
    comparison_command = [
        sys.executable,
        "-m",
        "cli",
        "--eval-task-file",
        str(Path.cwd() / "eval_tasks" / "sample_batch.json"),
        "--compare-strategies",
        "default,verify_failure_only_reflect",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(comparison_output_root),
    ]
    comparison_result = run(comparison_command, capture_output=True, text=True, check=False, env=env)

    assert comparison_result.returncode == 0, comparison_result.stderr
    comparison_summary = json.loads(
        (comparison_output_root / "comparison-sample_batch" / "summary.json").read_text(encoding="utf-8")
    )
    delta = comparison_summary["deltas"][0]
    assert "failure_taxonomy_counts_delta" in delta
    assert "failure_taxonomy_tag_counts_delta" in delta
    assert "reflect_trigger_reason_counts_delta" in delta
    assert comparison_summary["task_deltas"]


def test_cli_stops_with_structured_setup_failure(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    eval_task_file = tmp_path / "eval_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "setup_failure",
                        "task": "准备失败时停止",
                        "task_type": "general",
                        "setup_commands": [[sys.executable, "-c", "raise SystemExit(7)"]],
                        "expectation": {
                            "passed": False,
                            "outcome": "failed_setup",
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--eval-task-file",
        str(eval_task_file),
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    summary_data = json.loads((output_root / "eval-eval_batch" / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["success_count"] == 0
    assert summary_data["outcome_counts"] == {"failed_setup": 1}
    assert summary_data["failure_taxonomy_counts"] == {"setup:command_returncode": 1}

    run_dir = Path(summary_data["runs"][0]["run_dir"])
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    setup_payload = next(event["payload"] for event in trace_events if event["event_type"] == "task_setup_result")
    assert setup_payload["ok"] is False
    assert setup_payload["returncode"] == 7
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["code"] == "setup_failed"
    assert run_finished_payload["stop_reason"]["details"]["failed_setup_commands"][0]["returncode"] == 7
    assert [event["event_type"] for event in trace_events].count("model_decision") == 0


def test_cli_uses_task_type_specific_recall_strategy_for_bug_fix(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里主要介绍仓库背景。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    assert context_payload["task_context"]["task_type"] == "bug_fix"
    assert context_payload["repo_context"]["recall_strategy"] == "优先测试文件和相关代码文件"
    assert context_payload["memory_context"]["query"] == "bug_fix:修复 fail 错误"
    assert context_payload["memory_context"]["source"] == "runtime_memory_manager"
    assert len(context_payload["memory_context"]["matched_entries"]) >= 2
    assert len(context_payload["memory_context"]["runtime_rule_entries"]) >= 2
    assert context_payload["memory_context"]["long_term_entries"] == []
    assert context_payload["memory_context"]["conflict_evidence"] == []
    assert context_payload["memory_context"]["diagnostic_labels"] == []

    selected_files = context_payload["repo_context"]["selected_files"]
    selected_paths = [item["path"] for item in selected_files]
    assert "tests/test_app.py" in selected_paths
    assert "app.py" in selected_paths

    selected_by_path = {item["path"]: item for item in selected_files}
    assert "当前任务像修 bug" in selected_by_path["tests/test_app.py"]["reason"]
    assert "当前任务像修 bug" in selected_by_path["app.py"]["reason"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "召回倾向：优先测试文件和相关代码文件" in report_text
    assert "memory：已启用" in report_text
    assert "写入状态：未写入" in report_text


def test_cli_verify_failure_only_reflects_when_verification_is_missing(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里用于验证 reflect 触发策略。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def helper():\n    return 'ok'\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "检查 reflect 策略",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
        "--config-name",
        "verify_failure_only_reflect",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
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
        "verify",
        "reflect",
        "plan",
        "act",
        "observe",
        "verify",
        "finalize",
    ]

    verification_payload = next(event["payload"] for event in trace_events if event["event_type"] == "verification_result")
    assert verification_payload["details"]["verification_mode"] == "missing_task_verification"
    run_finished_payload = next(event["payload"] for event in trace_events if event["event_type"] == "run_finished")
    assert run_finished_payload["stop_reason"]["details"]["reflect_triggered"] is True
    assert run_finished_payload["stop_reason"]["details"]["reflect_trigger_reason"] == "verification_failed"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "reflect：已触发" in report_text
    assert "任务未配置 `verify_commands` 或 `verify_rules`" in report_text


def test_report_shows_model_error_diagnostics_without_api_key_value(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    settings = build_settings(
        task="触发模型配置错误",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(output_root),
        config_name="default",
    )
    config_data = {
        "model": {
            "provider": "openai_compatible",
            "name": "demo-model",
            "base_url": "bad-url",
        }
    }

    run_dir = execute_initial_run(settings=settings, config_data=config_data)

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failure_payload = next(event["payload"] for event in trace_events if event["event_type"] == "model_decision_failed")
    assert failure_payload["error_type"] == "ModelConfigError"
    assert failure_payload["field_path"] == "model.base_url"
    assert failure_payload["base_url"] == "bad-url"
    assert "secret-test-key" not in json.dumps(failure_payload, ensure_ascii=False)

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## 失败诊断" in report_text
    assert "模型错误类型：`ModelConfigError`" in report_text
    assert "base_url：`bad-url`" in report_text
    assert "secret-test-key" not in report_text


def test_cli_uses_naive_recent_context_strategy_from_config(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    file_specs = [
        ("README.md", "# 项目说明\n\n最早写入的说明文件。\n", 1_700_000_001),
        ("app.py", "def helper():\n    return 'app'\n", 1_700_000_002),
        ("notes.md", "# 临时笔记\n\n第二新的文本文件。\n", 1_700_000_003),
        ("latest.txt", "这是最后更新的文件。\n", 1_700_000_004),
    ]
    for file_name, content, timestamp in file_specs:
        file_path = repo_root / file_name
        file_path.write_text(content, encoding="utf-8")
        os.utime(file_path, (timestamp, timestamp))

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "查看最近改动的上下文文件",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
        "--config-name",
        "naive_recent_context",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    assert context_payload["repo_context"]["recall_strategy"] == "优先最近修改的文本文件（naive_recent_context）"

    selected_files = context_payload["repo_context"]["selected_files"]
    selected_paths = [item["path"] for item in selected_files]
    assert selected_paths == ["latest.txt", "notes.md", "app.py"]
    assert "README.md" not in selected_paths
    assert selected_files[0]["reason"] == "当前使用 naive recent context，按最近修改时间选中第 1 个文件。"
    assert selected_files[1]["reason"] == "当前使用 naive recent context，按最近修改时间选中第 2 个文件。"
    assert selected_files[2]["reason"] == "当前使用 naive recent context，按最近修改时间选中第 3 个文件。"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "优先最近修改的文本文件（naive_recent_context）" in report_text
    assert "`latest.txt`" in report_text
    assert "`notes.md`" in report_text
    assert "`app.py`" in report_text


def test_cli_reads_long_term_memory_with_task_type_keyword_and_path_filters(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里记录 app fail 问题和处理方式。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-memory-match",
                        "task": "修复 app fail 错误",
                        "task_type": "bug_fix",
                        "summary": "之前通过先看 test_app.py 和 app.py 很快定位了 fail 原因。"
                        "后面还补查了 README、错误路径、调用顺序和验证输出，最终确认这条经验对同类问题依然有效。",
                        "tags": ["bug_fix", "verified", "mvp"],
                        "evidence": {
                            "selected_context_files": ["app.py", "tests/test_app.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "run_id": "run-memory-ignore",
                        "task": "重构 utils helper",
                        "task_type": "refactor",
                        "summary": "这条经验和当前 bug 修复无关。",
                        "tags": ["refactor", "verified"],
                        "evidence": {
                            "selected_context_files": ["utils.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    memory_search_payload = next(event["payload"] for event in trace_events if event["event_type"] == "memory_search_result")
    assert memory_search_payload["query"] == "bug_fix:修复 app fail 错误"
    assert memory_search_payload["long_term_count"] == 1
    assert memory_search_payload["suppressed_long_term_count"] == 0
    assert memory_search_payload["matched_count"] >= 3

    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    memory_context = context_payload["memory_context"]
    assert memory_context["enabled"] is True
    assert len(memory_context["runtime_rule_entries"]) >= 2
    assert len(memory_context["long_term_entries"]) == 1
    assert memory_context["suppressed_long_term_entries"] == []
    assert len(memory_context["matched_entries"]) >= 3
    assert memory_context["conflict_evidence"] == []
    assert memory_context["diagnostic_labels"] == []

    long_term_entry = memory_context["long_term_entries"][0]
    assert long_term_entry["source"] == "long_term_memory"
    assert long_term_entry["evidence"]["run_id"] == "run-memory-match"
    assert long_term_entry["evidence"]["summary_was_compressed"] is True
    assert long_term_entry["evidence"]["original_summary_length"] > len(long_term_entry["summary"])
    assert long_term_entry["summary"].endswith("…")
    assert long_term_entry["evidence"]["stored_task_keywords"] == []
    assert long_term_entry["evidence"]["stored_summary_keywords"] == []
    assert long_term_entry["evidence"]["matched_on"]["task_type"] == "bug_fix"
    assert "bug_fix" in long_term_entry["evidence"]["matched_on"]["tags"]
    assert "fail" in long_term_entry["evidence"]["matched_on"]["keywords"]
    assert "app.py" in long_term_entry["evidence"]["matched_on"]["file_paths"]
    assert "tests/test_app.py" in long_term_entry["evidence"]["matched_on"]["file_paths"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "长期 memory `1` 条" in report_text


def test_cli_records_memory_conflict_evidence_and_pollution_labels(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-memory-bug-fix",
                        "task": "修复 app fail 错误",
                        "task_type": "bug_fix",
                        "summary": "之前通过检查 tests/test_app.py 和 app.py 修掉了 fail。",
                        "tags": ["bug_fix", "verified"],
                        "evidence": {
                            "selected_context_files": ["app.py", "tests/test_app.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "run_id": "run-memory-refactor",
                        "task": "重构 app fail 流程",
                        "task_type": "refactor",
                        "summary": "这次也改过 app.py，但目标是重构，不是修 bug。",
                        "tags": ["refactor", "verified"],
                        "evidence": {
                            "selected_context_files": ["app.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    conflict_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_conflict_detected"]
    assert len(conflict_events) == 1
    assert conflict_events[0]["query"] == "bug_fix:修复 app fail 错误"
    assert conflict_events[0]["conflict_count"] == 1
    memory_search_payload = next(event["payload"] for event in trace_events if event["event_type"] == "memory_search_result")
    assert memory_search_payload["long_term_count"] == 1
    assert memory_search_payload["suppressed_long_term_count"] == 1

    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    memory_context = context_payload["memory_context"]
    assert len(memory_context["long_term_entries"]) == 1
    assert len(memory_context["suppressed_long_term_entries"]) == 1
    assert "memory_conflict" in memory_context["diagnostic_labels"]
    assert "memory_pollution" in memory_context["diagnostic_labels"]
    assert "memory_injection_suppressed" in memory_context["diagnostic_labels"]
    assert len(memory_context["conflict_evidence"]) == 1
    assert memory_context["suppressed_long_term_entries"][0]["task_type"] == "refactor"
    assert memory_context["suppressed_long_term_entries"][0]["reason"] == "strong_conflict_with_current_task"

    conflict = memory_context["conflict_evidence"][0]
    assert conflict["kind"] == "task_type_mismatch"
    assert conflict["severity"] == "strong"
    assert "bug_fix" in conflict["task_types"]
    assert "refactor" in conflict["task_types"]
    assert "fail" in conflict["shared_keywords"]
    assert "app.py" in conflict["shared_file_paths"]
    assert conflict["shared_signal_types"] == 2

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "memory 诊断标签：`memory_conflict, memory_pollution, memory_injection_suppressed`" in report_text
    assert "memory 冲突：[强冲突]" in report_text
    assert "memory 注入抑制：" in report_text


def test_cli_records_weak_memory_conflict_warning_when_only_single_signal_is_shared(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-memory-bug-fix",
                        "task": "修复 app fail 错误",
                        "task_type": "bug_fix",
                        "summary": "之前通过检查 app.py 修掉了 fail。",
                        "tags": ["bug_fix", "verified"],
                        "evidence": {
                            "selected_context_files": ["app.py"],
                            "task_keywords": ["修复", "app", "fail", "错误"],
                            "summary_keywords": ["检查", "app.py", "修掉了", "fail"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "run_id": "run-memory-refactor",
                        "task": "重构 app fail 流程",
                        "task_type": "refactor",
                        "summary": "这次只是重构流程，没有沿用之前的 bug 修复结论。",
                        "tags": ["refactor", "verified"],
                        "evidence": {
                            "selected_context_files": ["docs/irrelevant.md"],
                            "task_keywords": ["重构", "app", "fail", "流程"],
                            "summary_keywords": ["重构", "流程"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    conflict_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_conflict_detected"]
    assert len(conflict_events) == 1
    assert conflict_events[0]["conflict_count"] == 1
    memory_search_payload = next(event["payload"] for event in trace_events if event["event_type"] == "memory_search_result")
    assert memory_search_payload["long_term_count"] == 2
    assert memory_search_payload["suppressed_long_term_count"] == 0

    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    memory_context = context_payload["memory_context"]
    assert len(memory_context["long_term_entries"]) == 2
    assert memory_context["suppressed_long_term_entries"] == []
    assert len(memory_context["conflict_evidence"]) == 1
    assert memory_context["diagnostic_labels"] == ["memory_conflict_warning"]
    assert memory_context["conflict_evidence"][0]["severity"] == "weak"
    assert memory_context["conflict_evidence"][0]["shared_keywords"] == ["app", "fail"]
    assert memory_context["conflict_evidence"][0]["shared_file_paths"] == []
    assert memory_context["long_term_entries"][0]["evidence"]["summary_was_compressed"] is False
    weak_penalized_entry = next(
        item for item in memory_context["long_term_entries"] if item["evidence"]["task_type"] == "refactor"
    )
    assert weak_penalized_entry["evidence"]["ranking_penalty"] == 3
    assert weak_penalized_entry["evidence"]["adjusted_score"] == (
        weak_penalized_entry["evidence"]["raw_score"] - 3
    )
    assert weak_penalized_entry["evidence"]["ranking_adjustment_reason"] == "weak_conflict_with_current_task"

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "memory 诊断标签：`memory_conflict_warning`" in report_text
    assert "memory 冲突：[弱提醒]" in report_text


def test_cli_uses_configured_weak_conflict_penalty_for_ranking(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-memory-bug-fix",
                        "task": "修复 app fail 错误",
                        "task_type": "bug_fix",
                        "summary": "之前通过检查 app.py 修掉了 fail。",
                        "tags": ["bug_fix", "verified"],
                        "evidence": {
                            "selected_context_files": ["app.py"],
                            "task_keywords": ["修复", "app", "fail", "错误"],
                            "summary_keywords": ["检查", "app.py", "修掉了", "fail"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "run_id": "run-memory-refactor",
                        "task": "重构 app fail 流程",
                        "task_type": "refactor",
                        "summary": "这次只是重构流程，没有沿用之前的 bug 修复结论。",
                        "tags": ["refactor", "verified"],
                        "evidence": {
                            "selected_context_files": ["docs/irrelevant.md"],
                            "task_keywords": ["重构", "app", "fail", "流程"],
                            "summary_keywords": ["重构", "流程"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
        "--config-name",
        "high_weak_conflict_penalty",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    weak_penalized_entry = next(
        item
        for item in context_payload["memory_context"]["long_term_entries"]
        if item["evidence"]["task_type"] == "refactor"
    )
    assert weak_penalized_entry["evidence"]["ranking_penalty"] == 5
    assert weak_penalized_entry["evidence"]["adjusted_score"] == (
        weak_penalized_entry["evidence"]["raw_score"] - 5
    )


def test_cli_uses_configured_summary_max_length_for_long_term_memory(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里记录 app fail 问题和处理方式。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        json.dumps(
            {
                "run_id": "run-memory-match",
                "task": "修复 app fail 错误",
                "task_type": "bug_fix",
                "summary": "之前通过先看 test_app.py 和 app.py 很快定位了 fail 原因。"
                "后面还补查了 README、错误路径、调用顺序和验证输出，最终确认这条经验对同类问题依然有效。",
                "tags": ["bug_fix", "verified", "mvp"],
                "evidence": {
                    "selected_context_files": ["app.py", "tests/test_app.py"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
        "--config-name",
        "short_memory_summary",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    long_term_entry = context_payload["memory_context"]["long_term_entries"][0]
    assert len(long_term_entry["summary"]) == 40
    assert long_term_entry["summary"].endswith("…")
    assert long_term_entry["evidence"]["original_summary_length"] > 40
