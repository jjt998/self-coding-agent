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
    _build_failure_taxonomy_tags,
    _load_expectation_spec,
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

    run_dirs = list((eval_dir / "runs").iterdir())
    assert len(run_dirs) == 2


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
