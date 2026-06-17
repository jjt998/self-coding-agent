from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eval_runner import (
    EvalExpectationAssessment,
    EvalExpectationSpec,
    EvalRunResult,
    _build_eval_batch_result,
    _build_eval_summary_markdown,
    _build_failure_taxonomy,
    _build_failure_taxonomy_tags,
    _load_expectation_spec,
    load_eval_task_specs,
    run_eval_batch,
)


def test_cli_runs_eval_batch_and_writes_summary(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这个仓库用于创建脚手架和修复 fail 错误。\n",
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

    eval_task_file = tmp_path / "eval_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "general_scaffold",
                        "task": "创建脚手架",
                        "task_type": "general",
                        "sandbox_retention": "always_keep",
                        "setup_commands": [
                            [
                                sys.executable,
                                "-c",
                                "from pathlib import Path; Path('setup_marker.txt').write_text('sandbox-ready', encoding='utf-8')",
                            ]
                        ],
                        "verify_rules": [
                            {"type": "file_exists", "name": "run evidence exists", "path": "run_evidence.md"}
                        ],
                        "expectation": {
                            "passed": True,
                            "outcome": "passed_cleanly",
                            "min_step_count": 1,
                            "min_tool_call_count": 1,
                            "forbidden_diagnostic_labels": ["memory_conflict_warning"],
                        },
                    },
                    {
                        "name": "bug_fix_fail",
                        "task": "修复 fail 错误",
                        "task_type": "bug_fix",
                        "verify_commands": [
                            [
                                sys.executable,
                                "-c",
                                "from pathlib import Path; raise SystemExit(0 if Path('app.py').exists() else 1)",
                            ]
                        ],
                        "expectation": {
                            "passed": True,
                            "outcome": "passed_cleanly",
                            "max_step_count": 12,
                            "max_tool_call_count": 8,
                        },
                    },
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

    eval_dir = output_root / "eval-eval_batch"
    assert eval_dir.exists()
    assert (eval_dir / "summary.json").exists()
    assert (eval_dir / "summary.md").exists()

    summary_data = json.loads((eval_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["eval_name"] == "eval_batch"
    assert summary_data["task_count"] == 2
    assert summary_data["success_count"] == 2
    assert summary_data["success_rate"] == 1.0
    assert summary_data["failure_rate"] == 0.0
    assert summary_data["average_steps"] >= 1
    assert summary_data["average_tool_calls"] >= 1
    assert summary_data["clean_pass_count"] == 2
    assert summary_data["clean_pass_rate"] == 1.0
    assert summary_data["warning_pass_count"] == 0
    assert summary_data["warning_rate"] == 0.0
    assert summary_data["verification_failure_rate"] == 0.0
    assert summary_data["outcome_counts"] == {"passed_cleanly": 2}
    assert summary_data["expectation_defined_count"] == 2
    assert summary_data["expectation_matched_count"] == 2
    assert summary_data["expectation_miss_count"] == 0
    assert summary_data["expectation_miss_rate"] == 0.0
    assert summary_data["expectation_failure_counts"] == {}
    assert summary_data["failure_taxonomy_counts"] == {}
    assert summary_data["failure_taxonomy_tag_counts"] == {}
    assert summary_data["verification_failure_counts"] == {}
    assert len(summary_data["runs"]) == 2
    assert summary_data["runs"][0]["task_name"] == "general_scaffold"
    assert summary_data["runs"][1]["task_name"] == "bug_fix_fail"
    assert summary_data["runs"][0]["outcome"] == "passed_cleanly"
    assert summary_data["runs"][1]["outcome"] == "passed_cleanly"
    assert summary_data["runs"][0]["expectation_result"]["matched"] is True
    assert summary_data["runs"][1]["expectation_result"]["matched"] is True

    summary_text = (eval_dir / "summary.md").read_text(encoding="utf-8")


    assert "# 评测汇总" in summary_text
    assert "## 结果分层" in summary_text
    assert "## Expectation 对照" in summary_text
    assert "## 失败分布" in summary_text
    assert "## Failure Taxonomy" in summary_text
    assert "## Failure Taxonomy Tags" in summary_text
    assert "## 验证失败检查项" in summary_text
    assert "## 诊断标签" in summary_text
    assert "## 运行明细" in summary_text

    run_dirs = sorted((eval_dir / "runs").iterdir())
    assert len(run_dirs) == 2
    assert not (repo_root / "run_evidence.md").exists()
    assert not (repo_root / "setup_marker.txt").exists()

    run_dir_by_task = {
        item["task_name"]: Path(item["run_dir"])
        for item in summary_data["runs"]
    }
    first_run_dir = run_dir_by_task["general_scaffold"]
    first_snapshot = json.loads((first_run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    assert first_snapshot["workspace_mode"] == "per_task_sandbox"
    assert first_snapshot["source_repo_root"] == str(repo_root.resolve())
    sandbox_repo_root = Path(first_snapshot["repo_root"])
    assert sandbox_repo_root.exists()
    assert (sandbox_repo_root / "run_evidence.md").exists()
    assert (sandbox_repo_root / "setup_marker.txt").read_text(encoding="utf-8") == "sandbox-ready"
    assert Path(first_snapshot["sandbox_dir"]).exists()

    first_trace_events = [
        json.loads(line)
        for line in (first_run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    workspace_payload = next(event["payload"] for event in first_trace_events if event["event_type"] == "workspace_prepared")
    assert workspace_payload["workspace_mode"] == "per_task_sandbox"
    assert workspace_payload["source_repo_root"] == str(repo_root.resolve())
    setup_result_payload = next(event["payload"] for event in first_trace_events if event["event_type"] == "task_setup_result")
    assert setup_result_payload["ok"] is True
    cleanup_payload = next(event["payload"] for event in first_trace_events if event["event_type"] == "sandbox_cleanup_result")
    assert cleanup_payload["kept"] is True
    assert cleanup_payload["retention_policy"] == "always_keep"

    second_run_dir = run_dir_by_task["bug_fix_fail"]
    second_trace_events = [
        json.loads(line)
        for line in (second_run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    second_verification_payload = next(
        event["payload"] for event in second_trace_events if event["event_type"] == "verification_result"
    )
    assert second_verification_payload["passed"] is True
    assert second_verification_payload["details"]["verification_mode"] == "task_verify_commands"
    assert second_verification_payload["checks"][0]["name"] == "verify_command_1"


def test_eval_batch_uses_unique_output_dir_when_previous_run_exists(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")
    eval_task_file = tmp_path / "repeatable_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "repeatable",
                        "task": "record a repeatable eval run",
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

    first_eval_dir = run_eval_batch(
        task_file=eval_task_file,
        repo_root=str(repo_root),
        output_root=str(output_root),
        config_name="default",
    )
    second_eval_dir = run_eval_batch(
        task_file=eval_task_file,
        repo_root=str(repo_root),
        output_root=str(output_root),
        config_name="default",
    )

    assert first_eval_dir.name == "eval-repeatable_batch"
    assert second_eval_dir.name.startswith("eval-repeatable_batch-")
    assert second_eval_dir != first_eval_dir
    assert (second_eval_dir / "summary.json").exists()


def test_eval_batch_result_distinguishes_clean_pass_warning_pass_and_failure() -> None:
    run_results = [
        EvalRunResult(
            task_name="clean_pass",
            run_id="run-clean",
            run_dir="runs/run-clean",
            passed=True,
            step_count=8,
            tool_call_count=5,
            stop_reason="completed",
            outcome="passed_cleanly",
            expectation=EvalExpectationSpec(passed=True, outcome="passed_cleanly"),
            expectation_result=EvalExpectationAssessment(defined=True, matched=True),
        ),
        EvalRunResult(
            task_name="warning_pass",
            run_id="run-warning",
            run_dir="runs/run-warning",
            passed=True,
            step_count=9,
            tool_call_count=5,
            stop_reason="completed",
            diagnostic_labels=["memory_conflict_warning"],
            outcome="passed_with_warnings",
            expectation=EvalExpectationSpec(
                passed=True,
                outcome="passed_cleanly",
                max_step_count=8,
                max_tool_call_count=4,
                forbidden_failing_checks=["说明文件可读"],
                forbidden_diagnostic_labels=["memory_conflict_warning"],
            ),
            expectation_result=EvalExpectationAssessment(
                defined=True,
                matched=False,
                failed_fields=[
                    "outcome",
                    "max_step_count",
                    "max_tool_call_count",
                    "forbidden_diagnostic_labels",
                ],
            ),
        ),
        EvalRunResult(
            task_name="failed_run",
            run_id="run-failed",
            run_dir="runs/run-failed",
            passed=False,
            step_count=7,
            tool_call_count=4,
            stop_reason="completed",
            outcome="failed_verification",
            verification_summary="验证失败：至少有一项关键检查未通过。",
            failing_checks=["说明文件可读", "命令检查通过"],
            failure_taxonomy="verification:说明文件可读",
            failure_taxonomy_tags=[
                "outcome:failed_verification",
                "stop_reason:completed",
                "verification_check_count:2",
                "verification_check:说明文件可读",
                "verification_check:命令检查通过",
            ],
            expectation=EvalExpectationSpec(
                passed=False,
                min_step_count=5,
                min_tool_call_count=3,
                required_failing_checks=["说明文件可读"],
                failure_taxonomy="verification:说明文件可读",
            ),
            expectation_result=EvalExpectationAssessment(defined=True, matched=True),
        ),
    ]

    batch_result = _build_eval_batch_result(eval_name="diagnostics_demo", run_results=run_results)

    assert batch_result.task_count == 3
    assert batch_result.success_count == 2
    assert batch_result.success_rate == 2 / 3
    assert batch_result.failure_rate == 1 / 3
    assert batch_result.clean_pass_count == 1
    assert batch_result.clean_pass_rate == 1 / 3
    assert batch_result.warning_pass_count == 1
    assert batch_result.warning_rate == 1 / 3
    assert batch_result.verification_failure_rate == 1 / 3
    assert batch_result.outcome_counts == {
        "failed_verification": 1,
        "passed_cleanly": 1,
        "passed_with_warnings": 1,
    }
    assert batch_result.expectation_defined_count == 3
    assert batch_result.expectation_matched_count == 2
    assert batch_result.expectation_miss_count == 1
    assert batch_result.expectation_miss_rate == 1 / 3
    assert batch_result.expectation_failure_counts == {
        "forbidden_diagnostic_labels": 1,
        "max_step_count": 1,
        "max_tool_call_count": 1,
        "outcome": 1,
    }
    assert batch_result.failure_distribution == {"completed": 1}
    assert batch_result.failure_taxonomy_counts == {"verification:说明文件可读": 1}
    assert batch_result.failure_taxonomy_tag_counts == {
        "outcome:failed_verification": 1,
        "stop_reason:completed": 1,
        "verification_check:命令检查通过": 1,
        "verification_check:说明文件可读": 1,
        "verification_check_count:2": 1,
    }
    assert batch_result.verification_failure_counts == {
        "命令检查通过": 1,
        "说明文件可读": 1,
    }
    assert batch_result.diagnostic_label_counts == {"memory_conflict_warning": 1}


def test_eval_summary_markdown_includes_outcome_layers_and_taxonomy() -> None:
    batch_result = _build_eval_batch_result(
        eval_name="diagnostics_demo",
        run_results=[
            EvalRunResult(
                task_name="warning_pass",
                run_id="run-warning",
                run_dir="runs/run-warning",
                passed=True,
                step_count=9,
                tool_call_count=5,
                stop_reason="completed",
                diagnostic_labels=["memory_conflict_warning"],
                outcome="passed_with_warnings",
                expectation_result=EvalExpectationAssessment(
                    defined=True,
                    matched=False,
                    failed_fields=["outcome", "max_step_count"],
                ),
            ),
            EvalRunResult(
                task_name="failed_run",
                run_id="run-failed",
                run_dir="runs/run-failed",
                passed=False,
                step_count=7,
                tool_call_count=4,
                stop_reason="completed",
                outcome="failed_verification",
                failing_checks=["说明文件可读"],
                failure_taxonomy="verification:说明文件可读",
                failure_taxonomy_tags=[
                    "outcome:failed_verification",
                    "verification_check:说明文件可读",
                ],
                expectation_result=EvalExpectationAssessment(defined=True, matched=True),
            ),
        ],
    )

    summary_text = _build_eval_summary_markdown(Path("eval_tasks/demo.json"), batch_result)

    assert "带警告成功：`1`" in summary_text
    assert "警告率：`0.50`" in summary_text
    assert "验证失败率：`0.50`" in summary_text
    assert "expectation 失配数：`1`" in summary_text
    assert "expectation 失配率：`0.50`" in summary_text
    assert "## 结果分层" in summary_text
    assert "## Expectation 对照" in summary_text
    assert "`passed_with_warnings`" in summary_text
    assert "## Failure Taxonomy" in summary_text
    assert "`verification:说明文件可读`" in summary_text
    assert "## Failure Taxonomy Tags" in summary_text
    assert "`verification_check:说明文件可读`" in summary_text
    assert "## 验证失败检查项" in summary_text
    assert "失败检查 `说明文件可读`" in summary_text
    assert "expectation 未命中 `outcome, max_step_count`" in summary_text


def test_load_expectation_spec_normalizes_minimal_expectation_fields() -> None:
    expectation = _load_expectation_spec(
        {
            "passed": True,
            "outcome": " passed_cleanly ",
            "min_step_count": " 3 ",
            "max_step_count": 12,
            "min_tool_call_count": "4",
            "max_tool_call_count": " 8 ",
            "required_failing_checks": ["说明文件可读", " "],
            "forbidden_failing_checks": ["命令检查通过"],
            "required_diagnostic_labels": ["memory_conflict_warning", " "],
            "forbidden_diagnostic_labels": ["memory_pollution"],
            "failure_taxonomy": " verification:说明文件可读 ",
        }
    )

    assert expectation == EvalExpectationSpec(
        passed=True,
        outcome="passed_cleanly",
        min_step_count=3,
        max_step_count=12,
        min_tool_call_count=4,
        max_tool_call_count=8,
        required_failing_checks=["说明文件可读"],
        forbidden_failing_checks=["命令检查通过"],
        required_diagnostic_labels=["memory_conflict_warning"],
        forbidden_diagnostic_labels=["memory_pollution"],
        failure_taxonomy="verification:说明文件可读",
    )


def test_expectation_can_check_steps_tool_calls_and_failing_checks() -> None:
    expectation = EvalExpectationSpec(
        passed=False,
        outcome="failed_verification",
        min_step_count=6,
        max_step_count=8,
        min_tool_call_count=4,
        max_tool_call_count=5,
        required_failing_checks=["说明文件可读"],
        forbidden_failing_checks=["变更已被记录"],
    )

    matched = _load_expectation_spec(expectation.to_dict())
    assert matched == expectation


def test_load_eval_task_specs_supports_sandbox_and_setup_fields(tmp_path: Path) -> None:
    task_file = tmp_path / "task_file.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "sandbox_bug_fix",
                        "task": "修复 sandbox 中的问题",
                        "task_type": "bug_fix",
                        "repo_subdir": "packages/api",
                        "workspace_mode": "per_task_sandbox",
                        "sandbox_retention": "always_delete",
                        "setup_commands": [["python", "-V"], ["python", "-c", "print('setup')"]],
                        "verify_commands": [["python", "-m", "pytest", "-q"]],
                        "verify_rules": [
                            {"type": "file_exists", "path": "tests/test_api.py"},
                            {"type": "command_stdout_contains", "command_index": 1, "contains": "passed"},
                            {"type": "command_stdout_not_contains", "command_index": 1, "not_contains": "failed"},
                            {"type": "file_not_exists", "path": "tmp/debug.log"},
                            {"type": "file_line_count_at_least", "path": "tests/test_api.py", "min_line_count": 3},
                            {"type": "file_line_count_at_most", "path": "tests/test_api.py", "max_line_count": 50},
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

    specs = load_eval_task_specs(task_file)

    assert len(specs) == 1
    assert specs[0].name == "sandbox_bug_fix"
    assert specs[0].repo_subdir == "packages/api"
    assert specs[0].workspace_mode == "per_task_sandbox"
    assert specs[0].sandbox_retention == "always_delete"
    assert specs[0].setup_commands == [["python", "-V"], ["python", "-c", "print('setup')"]]
    assert specs[0].verify_commands == [["python", "-m", "pytest", "-q"]]
    assert specs[0].verify_rules == [
        {"type": "file_exists", "path": "tests/test_api.py"},
        {"type": "command_stdout_contains", "command_index": "1", "contains": "passed"},
        {"type": "command_stdout_not_contains", "command_index": "1", "not_contains": "failed"},
        {"type": "file_not_exists", "path": "tmp/debug.log"},
        {"type": "file_line_count_at_least", "path": "tests/test_api.py", "min_line_count": 3},
        {"type": "file_line_count_at_most", "path": "tests/test_api.py", "max_line_count": 50},
    ]


def test_load_eval_task_specs_preserves_structured_verify_rule_fields(tmp_path: Path) -> None:
    task_file = tmp_path / "task_file.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "structured_verify_rules",
                        "task": "check structured outputs",
                        "verify_commands": [["python", "-c", "pass"]],
                        "verify_rules": [
                            {
                                "type": "json_file_value_equals",
                                "path": "result.json",
                                "json_path": "items.0.enabled",
                                "expected_value": True,
                            },
                            {
                                "type": "json_file_value_equals",
                                "path": "metrics.json",
                                "json_path": "score",
                                "expected_value": 3,
                            },
                            {
                                "type": "json_file_value_equals",
                                "path": "payload.json",
                                "json_path": "data",
                                "expected_value": {"labels": ["ok"], "count": 1},
                            },
                            {
                                "type": "files_matching_count_at_least",
                                "glob": "docs/*.md",
                                "contains": "status=ok",
                                "not_contains": "DEBUG",
                                "min_count": "2",
                            },
                            {
                                "type": "diff_changed_file_count_at_most",
                                "max_count": 4,
                            },
                            {
                                "type": "command_stdout_matches_regex",
                                "command_index": 1,
                                "regex": "ok-[0-9]+",
                            },
                            {
                                "type": "json_array_length_at_least",
                                "path": "result.json",
                                "json_path": "items",
                                "min_length": "2",
                            },
                            {
                                "type": "json_array_length_equals",
                                "path": "result.json",
                                "json_path": "items",
                                "expected_length": 3,
                            },
                            {
                                "type": "json_object_key_exists",
                                "path": "result.json",
                                "json_path": "metadata",
                                "key": "status",
                            },
                            {
                                "type": "diff_contains_text",
                                "contains": "+status=ok",
                            },
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

    specs = load_eval_task_specs(task_file)

    assert specs[0].verify_rules == [
        {
            "type": "json_file_value_equals",
            "path": "result.json",
            "json_path": "items.0.enabled",
            "expected_value": True,
        },
        {
            "type": "json_file_value_equals",
            "path": "metrics.json",
            "json_path": "score",
            "expected_value": 3,
        },
        {
            "type": "json_file_value_equals",
            "path": "payload.json",
            "json_path": "data",
            "expected_value": {"labels": ["ok"], "count": 1},
        },
        {
            "type": "files_matching_count_at_least",
            "min_count": 2,
            "contains": "status=ok",
            "not_contains": "DEBUG",
            "glob": "docs/*.md",
        },
        {"type": "diff_changed_file_count_at_most", "max_count": 4},
        {"type": "command_stdout_matches_regex", "command_index": "1", "regex": "ok-[0-9]+"},
        {
            "type": "json_array_length_at_least",
            "path": "result.json",
            "min_length": 2,
            "json_path": "items",
        },
        {
            "type": "json_array_length_equals",
            "path": "result.json",
            "expected_length": 3,
            "json_path": "items",
        },
        {
            "type": "json_object_key_exists",
            "path": "result.json",
            "json_path": "metadata",
            "key": "status",
        },
        {"type": "diff_contains_text", "contains": "+status=ok"},
    ]


def test_failure_taxonomy_tags_keep_all_failure_dimensions() -> None:
    tags = _build_failure_taxonomy_tags(
        outcome="failed_verification",
        stop_reason="completed",
        failing_checks=["说明文件可读", "命令检查通过"],
        diagnostic_labels=["memory_pollution"],
    )

    assert tags == [
        "outcome:failed_verification",
        "stop_reason:completed",
        "verification_check_count:2",
        "verification_check:说明文件可读",
        "verification_check:命令检查通过",
        "diagnostic_label:memory_pollution",
    ]


def test_missing_task_verification_gets_stable_taxonomy_and_tags() -> None:
    stop_reason_details = {
        "verification_failure": {
            "verification_mode": "missing_task_verification",
        }
    }

    taxonomy = _build_failure_taxonomy(
        outcome="failed_verification",
        stop_reason="verification_failed",
        failing_checks=["task_verification_configured"],
        stop_reason_details=stop_reason_details,
    )
    tags = _build_failure_taxonomy_tags(
        outcome="failed_verification",
        stop_reason="verification_failed",
        failing_checks=["task_verification_configured"],
        diagnostic_labels=[],
        stop_reason_details=stop_reason_details,
    )

    assert taxonomy == "verification:missing_task_verification"
    assert "verification_mode:missing_task_verification" in tags
    assert "verification_check:task_verification_configured" in tags


def test_runtime_and_model_failures_get_stable_taxonomy_and_tags() -> None:
    model_details = {"error_type": "ModelResponseError"}
    model_taxonomy = _build_failure_taxonomy(
        outcome="stopped_early",
        stop_reason="model_error",
        failing_checks=[],
        stop_reason_details=model_details,
    )
    model_tags = _build_failure_taxonomy_tags(
        outcome="stopped_early",
        stop_reason="model_error",
        failing_checks=[],
        diagnostic_labels=[],
        stop_reason_details=model_details,
    )
    max_steps_taxonomy = _build_failure_taxonomy(
        outcome="stopped_early",
        stop_reason="max_steps_reached",
        failing_checks=["verify_command_1"],
        stop_reason_details={"verification_failure": {"verification_mode": "task_verify_commands"}},
    )
    max_steps_tags = _build_failure_taxonomy_tags(
        outcome="stopped_early",
        stop_reason="max_steps_reached",
        failing_checks=["verify_command_1"],
        diagnostic_labels=[],
        stop_reason_details={"verification_failure": {"verification_mode": "task_verify_commands"}},
    )

    assert model_taxonomy == "model:ModelResponseError"
    assert "model_error_type:ModelResponseError" in model_tags
    assert max_steps_taxonomy == "runtime:max_steps_reached"
    assert "runtime:max_steps_reached" in max_steps_tags
    assert "verification_check:verify_command_1" in max_steps_tags


def test_eval_batch_result_counts_structured_setup_and_verify_taxonomy() -> None:
    run_results = [
        EvalRunResult(
            task_name="setup_failed",
            run_id="run-setup",
            run_dir="runs/run-setup",
            passed=False,
            step_count=0,
            tool_call_count=0,
            stop_reason="setup_failed",
            outcome="failed_setup",
            failure_taxonomy="setup:command_returncode",
            failure_taxonomy_tags=["outcome:failed_setup", "stop_reason:setup_failed", "setup_failure"],
        ),
        EvalRunResult(
            task_name="verify_failed",
            run_id="run-verify",
            run_dir="runs/run-verify",
            passed=False,
            step_count=8,
            tool_call_count=5,
            stop_reason="verification_failed",
            outcome="failed_verification",
            failing_checks=["verify_command_1"],
            failure_taxonomy="verification:verify_command_returncode",
            failure_taxonomy_tags=[
                "outcome:failed_verification",
                "stop_reason:verification_failed",
                "verification_check_count:1",
                "verification_check:verify_command_1",
            ],
        ),
        EvalRunResult(
            task_name="missing_verification",
            run_id="run-missing-verification",
            run_dir="runs/run-missing-verification",
            passed=False,
            step_count=8,
            tool_call_count=5,
            stop_reason="verification_failed",
            outcome="failed_verification",
            failing_checks=["task_verification_configured"],
            failure_taxonomy="verification:missing_task_verification",
            failure_taxonomy_tags=[
                "outcome:failed_verification",
                "stop_reason:verification_failed",
                "verification_mode:missing_task_verification",
                "verification_check_count:1",
                "verification_check:task_verification_configured",
            ],
        ),
        EvalRunResult(
            task_name="model_error",
            run_id="run-model-error",
            run_dir="runs/run-model-error",
            passed=False,
            step_count=2,
            tool_call_count=0,
            stop_reason="model_error",
            outcome="stopped_early",
            failure_taxonomy="model:ModelResponseError",
            failure_taxonomy_tags=[
                "outcome:stopped_early",
                "stop_reason:model_error",
                "model_error_type:ModelResponseError",
            ],
        ),
        EvalRunResult(
            task_name="max_steps",
            run_id="run-max-steps",
            run_dir="runs/run-max-steps",
            passed=False,
            step_count=8,
            tool_call_count=5,
            stop_reason="max_steps_reached",
            outcome="stopped_early",
            failing_checks=["verify_command_1"],
            failure_taxonomy="runtime:max_steps_reached",
            failure_taxonomy_tags=[
                "outcome:stopped_early",
                "stop_reason:max_steps_reached",
                "runtime:max_steps_reached",
                "verification_check_count:1",
                "verification_check:verify_command_1",
            ],
        ),
    ]

    batch_result = _build_eval_batch_result(eval_name="structured_failures", run_results=run_results)

    assert batch_result.outcome_counts == {"failed_setup": 1, "failed_verification": 2, "stopped_early": 2}
    assert batch_result.failure_distribution == {
        "setup_failed": 1,
        "verification_failed": 2,
        "model_error": 1,
        "max_steps_reached": 1,
    }
    assert batch_result.failure_taxonomy_counts == {
        "setup:command_returncode": 1,
        "verification:verify_command_returncode": 1,
        "verification:missing_task_verification": 1,
        "model:ModelResponseError": 1,
        "runtime:max_steps_reached": 1,
    }
