from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from experiment_runner import load_experiment_suite_specs


def test_load_experiment_suite_specs_reads_minimal_suite_file(tmp_path: Path) -> None:
    suite_file = tmp_path / "suite.json"
    suite_file.write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "name": "context_compare",
                        "task_file": "../eval_tasks/sample_batch.json",
                        "strategies": ["default", "naive_recent_context"],
                        "question": "相关性召回是否更稳。",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    specs = load_experiment_suite_specs(suite_file)

    assert len(specs) == 1
    assert specs[0].name == "context_compare"
    assert specs[0].task_file == "../eval_tasks/sample_batch.json"
    assert specs[0].strategies == ["default", "naive_recent_context"]
    assert specs[0].question == "相关性召回是否更稳。"


def test_cli_runs_experiment_suite_and_writes_suite_summary(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这个仓库用于执行首批策略实验。\n",
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

    suite_root = tmp_path / "experiment_suites"
    suite_root.mkdir()
    task_root = tmp_path / "eval_tasks"
    task_root.mkdir()

    task_file = task_root / "sample_batch.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "name": "general_scaffold",
                        "task": "创建脚手架",
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
    suite_file = suite_root / "first_batch.json"
    suite_file.write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        "name": "context_compare",
                        "task_file": "../eval_tasks/sample_batch.json",
                        "strategies": ["default", "naive_recent_context"],
                        "question": "相关性召回是否优于最近修改召回。",
                    },
                    {
                        "name": "memory_compare",
                        "task_file": "../eval_tasks/sample_batch.json",
                        "strategies": ["default", "memory_off"],
                        "question": "memory 是否能减少重复探索。",
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
        "--experiment-suite-file",
        str(suite_file),
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    suite_dir = output_root / "experiment-suite-first_batch"
    assert suite_dir.exists()
    assert (suite_dir / "summary.json").exists()
    assert (suite_dir / "summary.md").exists()

    summary_data = json.loads((suite_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["suite_name"] == "first_batch"
    assert summary_data["experiment_count"] == 2
    assert len(summary_data["experiments"]) == 2
    assert summary_data["experiments"][0]["name"] == "context_compare"
    assert summary_data["experiments"][1]["name"] == "memory_compare"
    assert summary_data["experiments"][0]["strategies"] == ["default", "naive_recent_context"]
    assert summary_data["experiments"][1]["strategies"] == ["default", "memory_off"]
    assert summary_data["experiments"][0]["baseline_strategy"] == "default"
    assert summary_data["experiments"][0]["deltas"][0]["strategy"] == "naive_recent_context"
    assert summary_data["experiments"][1]["deltas"][0]["strategy"] == "memory_off"

    summary_text = (suite_dir / "summary.md").read_text(encoding="utf-8")
    assert "# 实验套件汇总" in summary_text
    assert "## 实验结果" in summary_text
    assert "`context_compare`" in summary_text
    assert "`memory_compare`" in summary_text
    assert "问题：相关性召回是否优于最近修改召回。" in summary_text
    assert "问题：memory 是否能减少重复探索。" in summary_text


def test_sample_batch_is_now_a_research_like_fixed_task_set() -> None:
    sample_batch_path = Path("eval_tasks/sample_batch.json")
    sample_batch = json.loads(sample_batch_path.read_text(encoding="utf-8"))

    tasks = sample_batch["tasks"]
    task_types = {task["task_type"] for task in tasks}
    task_names = {task["name"] for task in tasks}

    assert len(tasks) >= 5
    assert task_types == {
        "general",
        "bug_fix",
        "code_understanding",
        "test_generation",
        "refactor",
    }
    assert task_names == {
        "general_run_artifact_audit",
        "bug_fix_fail_regression",
        "code_understanding_context_flow",
        "test_generation_comparison_guard",
        "refactor_eval_summary_cleanup",
    }
