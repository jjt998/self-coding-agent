from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from eval_runner import load_strategy_specs, run_strategy_comparison


@dataclass(slots=True)
class ExperimentSpec:
    """描述一条要执行的策略实验，包括任务集、策略组和实验问题。"""

    name: str
    task_file: str
    strategies: list[str]
    question: str = ""

    def to_dict(self) -> dict[str, Any]:
        """把实验定义转成普通字典，便于直接落盘。"""
        return asdict(self)


@dataclass(slots=True)
class ExperimentRunResult:
    """保存单条实验执行后的核心产物路径和摘要结果。"""

    name: str
    question: str
    task_file: str
    strategies: list[str]
    comparison_dir: str
    summary_json_path: str
    summary_md_path: str
    baseline_strategy: str
    deltas: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """把单条实验执行结果转成普通字典。"""
        return asdict(self)


@dataclass(slots=True)
class ExperimentSuiteResult:
    """保存一整套实验的执行结果，便于后续查看和归档。"""

    suite_name: str
    suite_file: str
    experiment_count: int
    experiments: list[ExperimentRunResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """把实验套件结果转成普通字典，并展开每条实验结果。"""
        return {
            "suite_name": self.suite_name,
            "suite_file": self.suite_file,
            "experiment_count": self.experiment_count,
            "experiments": [item.to_dict() for item in self.experiments],
        }


def run_experiment_suite(suite_file: Path, repo_root: str, output_root: str) -> Path:
    """执行一整套实验清单，并把每条 comparison 结果和总索引一起落盘。"""
    suite_name = suite_file.stem
    suite_dir = Path(output_root) / f"experiment-suite-{suite_name}"
    experiments_root = suite_dir / "experiments"
    suite_dir.mkdir(parents=True, exist_ok=False)
    experiments_root.mkdir(parents=True, exist_ok=False)

    experiment_specs = load_experiment_suite_specs(suite_file)
    experiment_results: list[ExperimentRunResult] = []
    for experiment_spec in experiment_specs:
        # 每条实验都单独占一个目录，后面回看结果时不需要再猜哪份 summary 对应哪组对比。
        experiment_output_root = experiments_root / experiment_spec.name
        strategy_specs = load_strategy_specs(experiment_spec.strategies)
        comparison_dir = run_strategy_comparison(
            task_file=_resolve_suite_relative_path(suite_file=suite_file, raw_path=experiment_spec.task_file),
            repo_root=repo_root,
            output_root=str(experiment_output_root),
            strategy_specs=strategy_specs,
        )
        comparison_summary = json.loads((comparison_dir / "summary.json").read_text(encoding="utf-8"))
        experiment_results.append(
            ExperimentRunResult(
                name=experiment_spec.name,
                question=experiment_spec.question,
                task_file=experiment_spec.task_file,
                strategies=list(experiment_spec.strategies),
                comparison_dir=str(comparison_dir).replace("\\", "/"),
                summary_json_path=str((comparison_dir / "summary.json")).replace("\\", "/"),
                summary_md_path=str((comparison_dir / "summary.md")).replace("\\", "/"),
                baseline_strategy=str(comparison_summary.get("baseline_strategy", "")).strip(),
                deltas=list(comparison_summary.get("deltas", [])),
            )
        )

    suite_result = ExperimentSuiteResult(
        suite_name=suite_name,
        suite_file=str(suite_file).replace("\\", "/"),
        experiment_count=len(experiment_results),
        experiments=experiment_results,
    )
    (suite_dir / "summary.json").write_text(
        json.dumps(suite_result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (suite_dir / "summary.md").write_text(
        _build_experiment_suite_markdown(suite_result),
        encoding="utf-8",
    )
    return suite_dir


def load_experiment_suite_specs(suite_file: Path) -> list[ExperimentSpec]:
    """读取实验套件文件，并解析出要执行的实验列表。"""
    raw_data = json.loads(suite_file.read_text(encoding="utf-8"))
    raw_experiments = raw_data.get("experiments", [])
    if not isinstance(raw_experiments, list):
        raise ValueError("experiment suite file must use {'experiments': [...]} structure")

    experiment_specs: list[ExperimentSpec] = []
    for index, raw_experiment in enumerate(raw_experiments):
        if not isinstance(raw_experiment, dict):
            raise ValueError(f"experiment at index {index} must be an object")
        name = str(raw_experiment.get("name", "")).strip() or f"experiment_{index + 1}"
        task_file = str(raw_experiment.get("task_file", "")).strip()
        if not task_file:
            raise ValueError(f"experiment '{name}' is missing 'task_file'")
        strategies = [str(item).strip() for item in raw_experiment.get("strategies", []) if str(item).strip()]
        if len(strategies) < 2:
            raise ValueError(f"experiment '{name}' must define at least two strategies")
        question = str(raw_experiment.get("question", "")).strip()
        experiment_specs.append(
            ExperimentSpec(
                name=name,
                task_file=task_file,
                strategies=strategies,
                question=question,
            )
        )
    return experiment_specs


def _build_experiment_suite_markdown(suite_result: ExperimentSuiteResult) -> str:
    """把实验套件执行结果整理成一份面向人的 Markdown 总览。"""
    experiment_lines: list[str] = []
    for experiment in suite_result.experiments:
        delta_summary = ", ".join(
            [
                (
                    f"{delta['strategy']} vs {delta['baseline_strategy']}: "
                    f"success `{delta['success_rate_delta']:+.2f}`, "
                    f"failure `{delta['failure_rate_delta']:+.2f}`, "
                    f"steps `{delta['average_steps_delta']:+.2f}`"
                )
                for delta in experiment.deltas
            ]
        )
        if not delta_summary:
            delta_summary = "no delta"
        line = (
            f"- `{experiment.name}` / baseline `{experiment.baseline_strategy}` / "
            f"strategies `{', '.join(experiment.strategies)}` / "
            f"task file `{experiment.task_file}` / summary `{experiment.summary_json_path}` / "
            f"delta {delta_summary}"
        )
        if experiment.question:
            line += f" / 问题：{experiment.question}"
        experiment_lines.append(line)

    return (
        f"# 实验套件汇总\n\n"
        f"- suite `{suite_result.suite_name}`\n"
        f"- suite file `{suite_result.suite_file}`\n"
        f"- experiment count `{suite_result.experiment_count}`\n\n"
        f"## 实验结果\n\n"
        f"{chr(10).join(experiment_lines) if experiment_lines else '- no experiments'}\n"
    )


def _resolve_suite_relative_path(suite_file: Path, raw_path: str) -> Path:
    """把实验套件里写的相对路径解析成真实文件路径。"""
    candidate_path = Path(raw_path)
    if candidate_path.is_absolute():
        return candidate_path
    return (suite_file.parent / candidate_path).resolve()
