from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eval_runner import (
    EvalRunResult,
    StrategyComparisonRun,
    StrategySpec,
    _build_eval_batch_result,
    _build_strategy_comparison_markdown,
    _build_strategy_comparison_result,
)


def test_cli_strategy_comparison_summary_includes_failure_delta_fields(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# demo\n", encoding="utf-8")
    (repo_root / "app.py").write_text("def demo_logic():\n    return 'ok'\n", encoding="utf-8")

    eval_task_file = tmp_path / "compare_batch.json"
    eval_task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "general_compare",
                        "task": "read README and run the minimum tool chain",
                        "task_type": "general",
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
        "--compare-strategies",
        "default,memory_off",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    summary_data = json.loads(
        (output_root / "comparison-compare_batch" / "summary.json").read_text(encoding="utf-8")
    )
    delta = summary_data["deltas"][0]
    assert "failure_taxonomy_counts_delta" in delta
    assert "failure_taxonomy_tag_counts_delta" in delta
    assert "verification_failure_counts_delta" in delta
    assert "task_deltas" in summary_data
    assert len(summary_data["task_deltas"]) == 1
    assert summary_data["task_deltas"][0]["strategy"] == "memory_off"


def test_strategy_comparison_result_reports_failure_taxonomy_deltas() -> None:
    baseline_summary = _build_eval_batch_result(
        eval_name="compare_demo",
        run_results=[
            EvalRunResult(
                task_name="task_a",
                run_id="run-a",
                run_dir="runs/run-a",
                passed=True,
                step_count=8,
                tool_call_count=5,
                verify_count=1,
                reflect_count=1,
                reflect_triggered=True,
                reflect_trigger_reason="no_progress_after_observe",
                stop_reason="completed",
                config_name="default",
                context_strategy="file_recall_context",
                reflect_strategy="low_progress_plus_verify_reflect",
                memory_enabled=True,
                memory_strategy="structured_memory_on",
                outcome="passed_cleanly",
            )
        ],
    )
    candidate_summary = _build_eval_batch_result(
        eval_name="compare_demo",
        run_results=[
            EvalRunResult(
                task_name="task_a",
                run_id="run-b",
                run_dir="runs/run-b",
                passed=False,
                step_count=10,
                tool_call_count=6,
                verify_count=1,
                reflect_count=1,
                reflect_triggered=True,
                reflect_trigger_reason="verification_failed",
                stop_reason="completed",
                config_name="memory_off",
                context_strategy="naive_recent_context",
                reflect_strategy="verify_failure_only_reflect",
                memory_enabled=False,
                memory_strategy="memory_off",
                outcome="failed_verification",
                failing_checks=["doc_readable"],
                failure_taxonomy="verification:doc_readable",
                failure_taxonomy_tags=[
                    "outcome:failed_verification",
                    "verification_check:doc_readable",
                ],
            )
        ],
    )

    comparison_result = _build_strategy_comparison_result(
        comparison_name="compare_demo",
        task_file=Path("eval_tasks/compare_demo.json"),
        strategy_runs=[
            StrategyComparisonRun(
                strategy=StrategySpec(
                    name="default",
                    config_name="default",
                    context_strategy="file_recall_context",
                    reflect_strategy="low_progress_plus_verify_reflect",
                    memory_enabled=True,
                    memory_strategy="structured_memory_on",
                ),
                eval_dir="runs/default/eval-compare_demo",
                summary=baseline_summary,
            ),
            StrategyComparisonRun(
                strategy=StrategySpec(
                    name="memory_off",
                    config_name="memory_off",
                    context_strategy="naive_recent_context",
                    reflect_strategy="verify_failure_only_reflect",
                    memory_enabled=False,
                    memory_strategy="memory_off",
                ),
                eval_dir="runs/memory_off/eval-compare_demo",
                summary=candidate_summary,
            ),
        ],
    )

    delta = comparison_result.deltas[0]
    assert delta["failure_taxonomy_counts_delta"] == {
        "verification:doc_readable": 1,
    }
    assert delta["failure_taxonomy_tag_counts_delta"] == {
        "outcome:failed_verification": 1,
        "verification_check:doc_readable": 1,
    }
    assert delta["verification_failure_counts_delta"] == {
        "doc_readable": 1,
    }
    assert delta["reflect_trigger_reason_counts_delta"] == {
        "no_progress_after_observe": -1,
        "verification_failed": 1,
    }
    assert comparison_result.task_deltas == [
        {
            "baseline_strategy": "default",
            "strategy": "memory_off",
            "tasks": [
                {
                    "task_name": "task_a",
                    "baseline_present": True,
                    "candidate_present": True,
                    "baseline_run_id": "run-a",
                    "candidate_run_id": "run-b",
                    "baseline_run_dir": "runs/run-a",
                    "candidate_run_dir": "runs/run-b",
                    "baseline_outcome": "passed_cleanly",
                    "candidate_outcome": "failed_verification",
                    "baseline_passed": True,
                    "candidate_passed": False,
                    "step_count_delta": 2,
                    "tool_call_count_delta": 1,
                    "verify_count_delta": 0,
                    "reflect_count_delta": 0,
                    "baseline_reflect_trigger_reason": "no_progress_after_observe",
                    "candidate_reflect_trigger_reason": "verification_failed",
                    "baseline_failure_taxonomy": "none",
                    "candidate_failure_taxonomy": "verification:doc_readable",
                    "failing_checks_delta": {"doc_readable": 1},
                    "diagnostic_labels_delta": {},
                }
            ],
        }
    ]

    summary_text = _build_strategy_comparison_markdown(comparison_result)
    assert "failure taxonomy delta" in summary_text
    assert "verification checks delta" in summary_text
    assert "reflect 原因 delta" in summary_text
    assert "## Task Delta" in summary_text
    assert "task `task_a`" in summary_text
    assert "outcome `passed_cleanly` -> `failed_verification`" in summary_text
    assert "baseline run `run-a` @ `runs/run-a`" in summary_text
    assert "candidate run `run-b` @ `runs/run-b`" in summary_text
