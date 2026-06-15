from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from statistics import mean
from typing import Any

from config import build_settings, load_named_config
from runner import execute_initial_run


@dataclass(slots=True)
class EvalExpectationSpec:
    passed: bool | None = None
    outcome: str | None = None
    min_step_count: int | None = None
    max_step_count: int | None = None
    min_tool_call_count: int | None = None
    max_tool_call_count: int | None = None
    required_failing_checks: list[str] = field(default_factory=list)
    forbidden_failing_checks: list[str] = field(default_factory=list)
    required_diagnostic_labels: list[str] = field(default_factory=list)
    forbidden_diagnostic_labels: list[str] = field(default_factory=list)
    failure_taxonomy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalExpectationAssessment:
    defined: bool = False
    matched: bool = True
    failed_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalTaskSpec:
    name: str
    task: str
    task_type: str = "general"
    expectation: EvalExpectationSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expectation"] = self.expectation.to_dict() if self.expectation else None
        return data


@dataclass(slots=True)
class EvalRunResult:
    task_name: str
    run_id: str
    run_dir: str
    passed: bool
    step_count: int
    tool_call_count: int
    stop_reason: str
    verification_summary: str = ""
    failing_checks: list[str] = field(default_factory=list)
    diagnostic_labels: list[str] = field(default_factory=list)
    outcome: str = "failed_unknown"
    expectation: EvalExpectationSpec | None = None
    expectation_result: EvalExpectationAssessment | None = None
    failure_taxonomy: str | None = None
    failure_taxonomy_tags: list[str] = field(default_factory=list)
    verify_count: int = 0
    reflect_count: int = 0
    reflect_triggered: bool = False
    reflect_trigger_reason: str = ""
    config_name: str = ""
    context_strategy: str = ""
    reflect_strategy: str = ""
    memory_enabled: bool = False
    memory_strategy: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expectation"] = self.expectation.to_dict() if self.expectation else None
        data["expectation_result"] = self.expectation_result.to_dict() if self.expectation_result else None
        return data


@dataclass(slots=True)
class EvalBatchResult:
    eval_name: str
    task_count: int
    success_count: int
    success_rate: float
    failure_rate: float
    average_steps: float
    average_tool_calls: float
    average_verify_count: float
    average_reflect_count: float
    reflect_trigger_rate: float
    clean_pass_count: int
    clean_pass_rate: float
    warning_pass_count: int
    warning_rate: float
    verification_failure_rate: float
    outcome_counts: dict[str, int] = field(default_factory=dict)
    expectation_defined_count: int = 0
    expectation_matched_count: int = 0
    expectation_miss_count: int = 0
    expectation_miss_rate: float = 0.0
    expectation_failure_counts: dict[str, int] = field(default_factory=dict)
    failure_distribution: dict[str, int] = field(default_factory=dict)
    failure_taxonomy_counts: dict[str, int] = field(default_factory=dict)
    failure_taxonomy_tag_counts: dict[str, int] = field(default_factory=dict)
    verification_failure_counts: dict[str, int] = field(default_factory=dict)
    reflect_trigger_reason_counts: dict[str, int] = field(default_factory=dict)
    diagnostic_label_counts: dict[str, int] = field(default_factory=dict)
    config_names: list[str] = field(default_factory=list)
    context_strategies: list[str] = field(default_factory=list)
    reflect_strategies: list[str] = field(default_factory=list)
    memory_strategies: list[str] = field(default_factory=list)
    runs: list[EvalRunResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["runs"] = [run.to_dict() for run in self.runs]
        return data


@dataclass(slots=True)
class StrategySpec:
    name: str
    config_name: str
    context_strategy: str
    reflect_strategy: str
    memory_enabled: bool
    memory_strategy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StrategyComparisonRun:
    strategy: StrategySpec
    eval_dir: str
    summary: EvalBatchResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.to_dict(),
            "eval_dir": self.eval_dir,
            "summary": self.summary.to_dict(),
        }


@dataclass(slots=True)
class StrategyComparisonResult:
    comparison_name: str
    task_file: str
    baseline_strategy: str
    strategies: list[StrategyComparisonRun]
    deltas: list[dict[str, Any]]
    task_deltas: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_name": self.comparison_name,
            "task_file": self.task_file,
            "baseline_strategy": self.baseline_strategy,
            "strategies": [item.to_dict() for item in self.strategies],
            "deltas": list(self.deltas),
            "task_deltas": list(self.task_deltas),
        }


def load_eval_task_specs(task_file: Path) -> list[EvalTaskSpec]:
    raw_data = json.loads(task_file.read_text(encoding="utf-8"))
    raw_tasks = raw_data.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise ValueError("eval task file must use {'tasks': [...]} structure")

    task_specs: list[EvalTaskSpec] = []
    for index, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            raise ValueError(f"task at index {index} must be an object")
        task_text = str(raw_task.get("task", "")).strip()
        if not task_text:
            raise ValueError(f"task at index {index} is missing 'task'")
        task_name = str(raw_task.get("name", "")).strip() or f"task_{index + 1}"
        task_type = str(raw_task.get("task_type", "general")).strip() or "general"
        task_specs.append(
            EvalTaskSpec(
                name=task_name,
                task=task_text,
                task_type=task_type,
                expectation=_load_expectation_spec(raw_task.get("expectation")),
            )
        )
    return task_specs


def load_strategy_specs(strategy_names: list[str]) -> list[StrategySpec]:
    strategy_specs: list[StrategySpec] = []
    for raw_name in strategy_names:
        config_name = str(raw_name).strip()
        if not config_name:
            continue
        config_data = load_named_config(config_dir=Path("configs"), config_name=config_name)
        strategy_specs.append(
            StrategySpec(
                name=config_name,
                config_name=config_name,
                context_strategy=_extract_context_strategy(config_data),
                reflect_strategy=_extract_reflect_strategy(config_data),
                memory_enabled=_extract_memory_enabled(config_data),
                memory_strategy=_extract_memory_strategy(config_data),
            )
        )
    return strategy_specs


def run_eval_batch(
    task_file: Path,
    repo_root: str,
    output_root: str,
    config_name: str,
) -> Path:
    task_specs = load_eval_task_specs(task_file)
    eval_name = task_file.stem
    eval_dir = Path(output_root) / f"eval-{eval_name}"
    runs_dir = eval_dir / "runs"
    eval_dir.mkdir(parents=True, exist_ok=False)
    runs_dir.mkdir(parents=True, exist_ok=False)

    run_results: list[EvalRunResult] = []
    config_data = load_named_config(config_dir=Path("configs"), config_name=config_name)
    for task_spec in task_specs:
        settings = build_settings(
            task=task_spec.task,
            task_type=task_spec.task_type,
            repo_root=repo_root,
            output_root=str(runs_dir),
            config_name=config_name,
        )
        run_dir = execute_initial_run(settings=settings, config_data=config_data)
        run_results.append(_collect_eval_run_result(task_spec=task_spec, run_id=settings.run_id, run_dir=run_dir))

    batch_result = _build_eval_batch_result(eval_name=eval_name, run_results=run_results)
    (eval_dir / "summary.json").write_text(
        json.dumps(batch_result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (eval_dir / "summary.md").write_text(
        _build_eval_summary_markdown(task_file=task_file, batch_result=batch_result),
        encoding="utf-8",
    )
    return eval_dir


def run_strategy_comparison(
    task_file: Path,
    repo_root: str,
    output_root: str,
    strategy_specs: list[StrategySpec],
) -> Path:
    if not strategy_specs:
        raise ValueError("at least one strategy is required for comparison")

    comparison_name = task_file.stem
    comparison_dir = Path(output_root) / f"comparison-{comparison_name}"
    strategies_root = comparison_dir / "strategies"
    comparison_dir.mkdir(parents=True, exist_ok=False)
    strategies_root.mkdir(parents=True, exist_ok=False)

    strategy_runs: list[StrategyComparisonRun] = []
    for strategy in strategy_specs:
        strategy_root = strategies_root / strategy.name
        eval_dir = run_eval_batch(
            task_file=task_file,
            repo_root=repo_root,
            output_root=str(strategy_root),
            config_name=strategy.config_name,
        )
        batch_result = _load_eval_batch_result(eval_dir / "summary.json")
        strategy_runs.append(
            StrategyComparisonRun(
                strategy=strategy,
                eval_dir=str(eval_dir).replace("\\", "/"),
                summary=batch_result,
            )
        )

    comparison_result = _build_strategy_comparison_result(
        comparison_name=comparison_name,
        task_file=task_file,
        strategy_runs=strategy_runs,
    )
    (comparison_dir / "summary.json").write_text(
        json.dumps(comparison_result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (comparison_dir / "summary.md").write_text(
        _build_strategy_comparison_markdown(comparison_result),
        encoding="utf-8",
    )
    return comparison_dir


def _collect_eval_run_result(task_spec: EvalTaskSpec, run_id: str, run_dir: Path) -> EvalRunResult:
    trace_events = _load_trace_events(run_dir / "trace.jsonl")
    config_snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))

    verification_payload = _find_last_payload(trace_events, "verification_result")
    run_finished_payload = _find_last_payload(trace_events, "run_finished")
    context_snapshot_payload = _find_last_payload(trace_events, "context_snapshot")

    verification_checks = verification_payload.get("checks", []) if verification_payload else []
    failing_checks = [
        str(check.get("name", "")).strip()
        for check in verification_checks
        if not bool(check.get("passed")) and str(check.get("name", "")).strip()
    ]
    diagnostic_labels = _normalize_string_list(
        (((context_snapshot_payload or {}).get("memory_context", {})).get("diagnostic_labels", []))
    )
    stop_reason_dict = (run_finished_payload or {}).get("stop_reason", {})
    stop_reason = str(stop_reason_dict.get("code", "unknown")).strip() or "unknown"
    stop_reason_details = stop_reason_dict.get("details", {})
    step_count = _normalize_optional_int((run_finished_payload or {}).get("step_count")) or 0
    tool_call_count = sum(1 for event in trace_events if event.get("event_type") == "tool_called")
    verify_count = sum(
        1
        for event in trace_events
        if event.get("event_type") == "state_transitioned"
        and str(event.get("payload", {}).get("to_state", "")).strip() == "verify"
    )
    reflect_count = sum(
        1
        for event in trace_events
        if event.get("event_type") == "state_transitioned"
        and str(event.get("payload", {}).get("to_state", "")).strip() == "reflect"
    )
    reflect_trigger_reason = str(stop_reason_details.get("reflect_trigger_reason", "")).strip()
    reflect_triggered = bool(stop_reason_details.get("reflect_triggered")) or reflect_count > 0
    passed = bool((verification_payload or {}).get("passed"))
    verification_summary = str((verification_payload or {}).get("summary", "")).strip()
    failure_taxonomy = _build_failure_taxonomy(
        outcome=_classify_eval_outcome(
            passed=passed,
            stop_reason=stop_reason,
            diagnostic_labels=diagnostic_labels,
            failing_checks=failing_checks,
        ),
        stop_reason=stop_reason,
        failing_checks=failing_checks,
    )
    outcome = _classify_eval_outcome(
        passed=passed,
        stop_reason=stop_reason,
        diagnostic_labels=diagnostic_labels,
        failing_checks=failing_checks,
    )
    expectation_result = _assess_expectation(
        expectation=task_spec.expectation,
        passed=passed,
        outcome=outcome,
        step_count=step_count,
        tool_call_count=tool_call_count,
        failing_checks=failing_checks,
        diagnostic_labels=diagnostic_labels,
        failure_taxonomy=failure_taxonomy,
    )

    config_data = config_snapshot.get("config", {})
    return EvalRunResult(
        task_name=task_spec.name,
        run_id=run_id,
        run_dir=str(run_dir).replace("\\", "/"),
        passed=passed,
        step_count=step_count,
        tool_call_count=tool_call_count,
        stop_reason=stop_reason,
        verification_summary=verification_summary,
        failing_checks=failing_checks,
        diagnostic_labels=diagnostic_labels,
        outcome=outcome,
        expectation=task_spec.expectation,
        expectation_result=expectation_result,
        failure_taxonomy=failure_taxonomy,
        failure_taxonomy_tags=_build_failure_taxonomy_tags(
            outcome=outcome,
            stop_reason=stop_reason,
            failing_checks=failing_checks,
            diagnostic_labels=diagnostic_labels,
        ),
        verify_count=verify_count,
        reflect_count=reflect_count,
        reflect_triggered=reflect_triggered,
        reflect_trigger_reason=reflect_trigger_reason,
        config_name=str(config_snapshot.get("config_name", "")).strip(),
        context_strategy=_extract_context_strategy(config_data),
        reflect_strategy=_extract_reflect_strategy(config_data),
        memory_enabled=_extract_memory_enabled(config_data),
        memory_strategy=_extract_memory_strategy(config_data),
    )


def _build_eval_batch_result(eval_name: str, run_results: list[EvalRunResult]) -> EvalBatchResult:
    task_count = len(run_results)
    success_count = sum(1 for item in run_results if item.passed)
    clean_pass_count = sum(1 for item in run_results if item.outcome == "passed_cleanly")
    warning_pass_count = sum(1 for item in run_results if item.outcome == "passed_with_warnings")
    verification_failure_count = sum(1 for item in run_results if item.outcome == "failed_verification")
    reflect_trigger_count = sum(1 for item in run_results if item.reflect_triggered)

    outcome_counts = _count_values([item.outcome for item in run_results if item.outcome])
    expectation_defined_count = sum(
        1 for item in run_results if item.expectation_result and item.expectation_result.defined
    )
    expectation_matched_count = sum(
        1 for item in run_results if item.expectation_result and item.expectation_result.defined and item.expectation_result.matched
    )
    expectation_failure_counts = _count_values(
        [
            failed_field
            for item in run_results
            for failed_field in (item.expectation_result.failed_fields if item.expectation_result else [])
        ]
    )
    failure_distribution = _count_values([item.stop_reason for item in run_results if not item.passed])
    failure_taxonomy_counts = _count_values([item.failure_taxonomy for item in run_results if item.failure_taxonomy])
    failure_taxonomy_tag_counts = _count_values(
        [tag for item in run_results for tag in item.failure_taxonomy_tags if tag]
    )
    verification_failure_counts = _count_values(
        [check for item in run_results for check in item.failing_checks if check]
    )
    reflect_trigger_reason_counts = _count_values(
        [item.reflect_trigger_reason for item in run_results if item.reflect_trigger_reason]
    )
    diagnostic_label_counts = _count_values(
        [label for item in run_results for label in item.diagnostic_labels if label]
    )

    return EvalBatchResult(
        eval_name=eval_name,
        task_count=task_count,
        success_count=success_count,
        success_rate=(success_count / task_count) if task_count else 0.0,
        failure_rate=((task_count - success_count) / task_count) if task_count else 0.0,
        average_steps=mean(item.step_count for item in run_results) if run_results else 0.0,
        average_tool_calls=mean(item.tool_call_count for item in run_results) if run_results else 0.0,
        average_verify_count=mean(item.verify_count for item in run_results) if run_results else 0.0,
        average_reflect_count=mean(item.reflect_count for item in run_results) if run_results else 0.0,
        reflect_trigger_rate=(reflect_trigger_count / task_count) if task_count else 0.0,
        clean_pass_count=clean_pass_count,
        clean_pass_rate=(clean_pass_count / task_count) if task_count else 0.0,
        warning_pass_count=warning_pass_count,
        warning_rate=(warning_pass_count / task_count) if task_count else 0.0,
        verification_failure_rate=(verification_failure_count / task_count) if task_count else 0.0,
        outcome_counts=outcome_counts,
        expectation_defined_count=expectation_defined_count,
        expectation_matched_count=expectation_matched_count,
        expectation_miss_count=expectation_defined_count - expectation_matched_count,
        expectation_miss_rate=(
            (expectation_defined_count - expectation_matched_count) / expectation_defined_count
            if expectation_defined_count
            else 0.0
        ),
        expectation_failure_counts=expectation_failure_counts,
        failure_distribution=failure_distribution,
        failure_taxonomy_counts=failure_taxonomy_counts,
        failure_taxonomy_tag_counts=failure_taxonomy_tag_counts,
        verification_failure_counts=verification_failure_counts,
        reflect_trigger_reason_counts=reflect_trigger_reason_counts,
        diagnostic_label_counts=diagnostic_label_counts,
        config_names=sorted({item.config_name for item in run_results if item.config_name}),
        context_strategies=sorted({item.context_strategy for item in run_results if item.context_strategy}),
        reflect_strategies=sorted({item.reflect_strategy for item in run_results if item.reflect_strategy}),
        memory_strategies=sorted({item.memory_strategy for item in run_results if item.memory_strategy}),
        runs=run_results,
    )


def _build_eval_summary_markdown(task_file: Path, batch_result: EvalBatchResult) -> str:
    run_lines: list[str] = []
    for item in batch_result.runs:
        line = (
            f"- `{item.task_name}` / outcome `{item.outcome}` / stop reason `{item.stop_reason}` / "
            f"steps `{item.step_count}` / tools `{item.tool_call_count}` / "
            f"verify `{item.verify_count}` / reflect `{item.reflect_count}`"
        )
        if item.diagnostic_labels:
            line += f" / 诊断 `{', '.join(item.diagnostic_labels)}`"
        if item.failing_checks:
            line += f" / 失败检查 `{', '.join(item.failing_checks)}`"
        if item.failure_taxonomy_tags:
            line += f" / taxonomy tags `{', '.join(item.failure_taxonomy_tags)}`"
        if item.expectation_result and item.expectation_result.defined:
            if item.expectation_result.matched:
                line += " / expectation 命中"
            else:
                line += f" / expectation 未命中 `{', '.join(item.expectation_result.failed_fields)}`"
        run_lines.append(line)

    return (
        f"# 评测汇总\n\n"
        f"- task file `{task_file}`\n"
        f"- task count `{batch_result.task_count}`\n"
        f"- success count `{batch_result.success_count}`\n"
        f"- success rate `{batch_result.success_rate:.2f}`\n"
        f"- failure rate `{batch_result.failure_rate:.2f}`\n"
        f"- average steps `{batch_result.average_steps:.2f}`\n"
        f"- average tool calls `{batch_result.average_tool_calls:.2f}`\n"
        f"- average verify `{batch_result.average_verify_count:.2f}`\n"
        f"- average reflect `{batch_result.average_reflect_count:.2f}`\n"
        f"- clean pass count `{batch_result.clean_pass_count}`\n"
        f"- clean pass rate `{batch_result.clean_pass_rate:.2f}`\n"
        f"- 带警告成功：`{batch_result.warning_pass_count}`\n"
        f"- 警告率：`{batch_result.warning_rate:.2f}`\n"
        f"- 验证失败率：`{batch_result.verification_failure_rate:.2f}`\n"
        f"- expectation defined count `{batch_result.expectation_defined_count}`\n"
        f"- expectation matched count `{batch_result.expectation_matched_count}`\n"
        f"- expectation 失配数：`{batch_result.expectation_miss_count}`\n"
        f"- expectation 失配率：`{batch_result.expectation_miss_rate:.2f}`\n\n"
        f"## 结果分层\n\n"
        f"{_build_markdown_count_lines(batch_result.outcome_counts, '- no outcomes')}\n\n"
        f"## Expectation 对照\n\n"
        f"{_build_markdown_count_lines(batch_result.expectation_failure_counts, '- no expectation misses')}\n\n"
        f"## 失败分布\n\n"
        f"{_build_markdown_count_lines(batch_result.failure_distribution, '- no failures')}\n\n"
        f"## Failure Taxonomy\n\n"
        f"{_build_markdown_count_lines(batch_result.failure_taxonomy_counts, '- no failure taxonomy')}\n\n"
        f"## Failure Taxonomy Tags\n\n"
        f"{_build_markdown_count_lines(batch_result.failure_taxonomy_tag_counts, '- no failure taxonomy tags')}\n\n"
        f"## 验证失败检查项\n\n"
        f"{_build_verification_failure_lines(batch_result.verification_failure_counts)}\n\n"
        f"## Reflect 原因\n\n"
        f"{_build_markdown_count_lines(batch_result.reflect_trigger_reason_counts, '- no reflect reasons')}\n\n"
        f"## 诊断标签\n\n"
        f"{_build_markdown_count_lines(batch_result.diagnostic_label_counts, '- no diagnostic labels')}\n\n"
        f"## 运行明细\n\n"
        f"{chr(10).join(run_lines) if run_lines else '- no runs'}\n"
    )


def _build_strategy_comparison_result(
    comparison_name: str,
    task_file: Path,
    strategy_runs: list[StrategyComparisonRun],
) -> StrategyComparisonResult:
    if not strategy_runs:
        raise ValueError("strategy_runs cannot be empty")

    baseline = strategy_runs[0]
    deltas: list[dict[str, Any]] = []
    task_deltas: list[dict[str, Any]] = []
    for candidate in strategy_runs[1:]:
        deltas.append(_build_strategy_delta(baseline, candidate))
        task_deltas.append(_build_strategy_task_delta(baseline, candidate))

    return StrategyComparisonResult(
        comparison_name=comparison_name,
        task_file=str(task_file).replace("\\", "/"),
        baseline_strategy=baseline.strategy.name,
        strategies=strategy_runs,
        deltas=deltas,
        task_deltas=task_deltas,
    )


def _build_strategy_delta(
    baseline: StrategyComparisonRun,
    candidate: StrategyComparisonRun,
) -> dict[str, Any]:
    baseline_summary = baseline.summary
    candidate_summary = candidate.summary
    return {
        "baseline_strategy": baseline.strategy.name,
        "strategy": candidate.strategy.name,
        "success_rate_delta": candidate_summary.success_rate - baseline_summary.success_rate,
        "failure_rate_delta": candidate_summary.failure_rate - baseline_summary.failure_rate,
        "average_steps_delta": candidate_summary.average_steps - baseline_summary.average_steps,
        "average_tool_calls_delta": candidate_summary.average_tool_calls - baseline_summary.average_tool_calls,
        "average_verify_count_delta": candidate_summary.average_verify_count - baseline_summary.average_verify_count,
        "average_reflect_count_delta": candidate_summary.average_reflect_count - baseline_summary.average_reflect_count,
        "reflect_trigger_rate_delta": candidate_summary.reflect_trigger_rate - baseline_summary.reflect_trigger_rate,
        "clean_pass_rate_delta": candidate_summary.clean_pass_rate - baseline_summary.clean_pass_rate,
        "warning_rate_delta": candidate_summary.warning_rate - baseline_summary.warning_rate,
        "verification_failure_rate_delta": (
            candidate_summary.verification_failure_rate - baseline_summary.verification_failure_rate
        ),
        "expectation_miss_rate_delta": (
            candidate_summary.expectation_miss_rate - baseline_summary.expectation_miss_rate
        ),
        "context_strategy_changed": candidate.strategy.context_strategy != baseline.strategy.context_strategy,
        "reflect_strategy_changed": candidate.strategy.reflect_strategy != baseline.strategy.reflect_strategy,
        "memory_strategy_changed": candidate.strategy.memory_strategy != baseline.strategy.memory_strategy,
        "failure_taxonomy_counts_delta": _build_count_delta(
            baseline_summary.failure_taxonomy_counts,
            candidate_summary.failure_taxonomy_counts,
        ),
        "failure_taxonomy_tag_counts_delta": _build_count_delta(
            baseline_summary.failure_taxonomy_tag_counts,
            candidate_summary.failure_taxonomy_tag_counts,
        ),
        "verification_failure_counts_delta": _build_count_delta(
            baseline_summary.verification_failure_counts,
            candidate_summary.verification_failure_counts,
        ),
        "reflect_trigger_reason_counts_delta": _build_count_delta(
            baseline_summary.reflect_trigger_reason_counts,
            candidate_summary.reflect_trigger_reason_counts,
        ),
    }


def _build_strategy_comparison_markdown(comparison_result: StrategyComparisonResult) -> str:
    strategy_lines = [
        (
            f"- `{item.strategy.name}`"
            f" ({'baseline' if item.strategy.name == comparison_result.baseline_strategy else 'candidate'})"
            f": config `{item.strategy.config_name}`, "
            f"context `{item.strategy.context_strategy}`, "
            f"reflect `{item.strategy.reflect_strategy}`, "
            f"memory `{item.strategy.memory_strategy}`, "
            f"success rate `{item.summary.success_rate:.2f}`, "
            f"average steps `{item.summary.average_steps:.2f}`, "
            f"average verify `{item.summary.average_verify_count:.2f}`, "
            f"average reflect `{item.summary.average_reflect_count:.2f}`"
        )
        for item in comparison_result.strategies
    ]

    delta_lines = [
        (
            f"- `{delta['strategy']}` relative to `{delta['baseline_strategy']}`: "
            f"success rate delta `{delta['success_rate_delta']:.2f}`, "
            f"failure rate delta `{delta['failure_rate_delta']:.2f}`, "
            f"average steps delta `{delta['average_steps_delta']:.2f}`, "
            f"average tool calls delta `{delta['average_tool_calls_delta']:.2f}`, "
            f"average verify delta `{delta['average_verify_count_delta']:.2f}`, "
            f"average reflect delta `{delta['average_reflect_count_delta']:.2f}`, "
            f"reflect trigger rate delta `{delta['reflect_trigger_rate_delta']:.2f}`, "
            f"context changed `{delta['context_strategy_changed']}`, "
            f"reflect changed `{delta['reflect_strategy_changed']}`, "
            f"memory changed `{delta['memory_strategy_changed']}`, "
            f"failure taxonomy delta `{_format_count_delta(delta['failure_taxonomy_counts_delta'])}`, "
            f"failure taxonomy tags delta `{_format_count_delta(delta['failure_taxonomy_tag_counts_delta'])}`, "
            f"verification checks delta `{_format_count_delta(delta['verification_failure_counts_delta'])}`, "
            f"reflect 原因 delta `{_format_count_delta(delta['reflect_trigger_reason_counts_delta'])}`"
        )
        for delta in comparison_result.deltas
    ]

    task_delta_lines: list[str] = []
    for strategy_task_delta in comparison_result.task_deltas:
        candidate_name = strategy_task_delta["strategy"]
        baseline_name = strategy_task_delta["baseline_strategy"]
        per_task_items = strategy_task_delta.get("tasks", [])
        if not per_task_items:
            task_delta_lines.append(f"- `{candidate_name}` relative to `{baseline_name}`: no task-level delta.")
            continue
        for item in per_task_items:
            task_delta_lines.append(
                f"- `{candidate_name}` relative to `{baseline_name}` / task `{item['task_name']}`: "
                f"outcome `{item['baseline_outcome']}` -> `{item['candidate_outcome']}`, "
                f"passed `{item['baseline_passed']}` -> `{item['candidate_passed']}`, "
                f"steps delta `{item['step_count_delta']:+d}`, "
                f"tool calls delta `{item['tool_call_count_delta']:+d}`, "
                f"verify delta `{item['verify_count_delta']:+d}`, "
                f"reflect delta `{item['reflect_count_delta']:+d}`, "
                f"reflect reason `{item['baseline_reflect_trigger_reason']}` -> `{item['candidate_reflect_trigger_reason']}`, "
                f"failure taxonomy `{item['baseline_failure_taxonomy']}` -> `{item['candidate_failure_taxonomy']}`, "
                f"baseline run `{item['baseline_run_id']}` @ `{item['baseline_run_dir']}`, "
                f"candidate run `{item['candidate_run_id']}` @ `{item['candidate_run_dir']}`"
            )

    return (
        f"# 策略对比汇总\n\n"
        f"- task file `{comparison_result.task_file}`\n"
        f"- baseline `{comparison_result.baseline_strategy}`\n\n"
        f"## 策略结果\n\n"
        f"{chr(10).join(strategy_lines) if strategy_lines else '- no strategies'}\n\n"
        f"## Delta\n\n"
        f"{chr(10).join(delta_lines) if delta_lines else '- no deltas'}\n\n"
        f"## Task Delta\n\n"
        f"{chr(10).join(task_delta_lines) if task_delta_lines else '- no task-level delta'}\n"
    )


def _build_strategy_task_delta(
    baseline: StrategyComparisonRun,
    candidate: StrategyComparisonRun,
) -> dict[str, Any]:
    baseline_runs = {item.task_name: item for item in baseline.summary.runs}
    candidate_runs = {item.task_name: item for item in candidate.summary.runs}
    task_names = sorted(set(baseline_runs) | set(candidate_runs))

    tasks: list[dict[str, Any]] = []
    for task_name in task_names:
        baseline_run = baseline_runs.get(task_name)
        candidate_run = candidate_runs.get(task_name)
        if not _task_delta_changed(baseline_run, candidate_run):
            continue

        tasks.append(
            {
                "task_name": task_name,
                "baseline_present": baseline_run is not None,
                "candidate_present": candidate_run is not None,
                "baseline_run_id": baseline_run.run_id if baseline_run else "",
                "candidate_run_id": candidate_run.run_id if candidate_run else "",
                "baseline_run_dir": baseline_run.run_dir if baseline_run else "",
                "candidate_run_dir": candidate_run.run_dir if candidate_run else "",
                "baseline_outcome": baseline_run.outcome if baseline_run else "missing",
                "candidate_outcome": candidate_run.outcome if candidate_run else "missing",
                "baseline_passed": baseline_run.passed if baseline_run else False,
                "candidate_passed": candidate_run.passed if candidate_run else False,
                "step_count_delta": (candidate_run.step_count if candidate_run else 0)
                - (baseline_run.step_count if baseline_run else 0),
                "tool_call_count_delta": (candidate_run.tool_call_count if candidate_run else 0)
                - (baseline_run.tool_call_count if baseline_run else 0),
                "verify_count_delta": (candidate_run.verify_count if candidate_run else 0)
                - (baseline_run.verify_count if baseline_run else 0),
                "reflect_count_delta": (candidate_run.reflect_count if candidate_run else 0)
                - (baseline_run.reflect_count if baseline_run else 0),
                "baseline_reflect_trigger_reason": (
                    baseline_run.reflect_trigger_reason if baseline_run and baseline_run.reflect_trigger_reason else "none"
                ),
                "candidate_reflect_trigger_reason": (
                    candidate_run.reflect_trigger_reason if candidate_run and candidate_run.reflect_trigger_reason else "none"
                ),
                "baseline_failure_taxonomy": (
                    baseline_run.failure_taxonomy if baseline_run and baseline_run.failure_taxonomy else "none"
                ),
                "candidate_failure_taxonomy": (
                    candidate_run.failure_taxonomy if candidate_run and candidate_run.failure_taxonomy else "none"
                ),
                "failing_checks_delta": _build_count_delta(
                    _count_values(baseline_run.failing_checks if baseline_run else []),
                    _count_values(candidate_run.failing_checks if candidate_run else []),
                ),
                "diagnostic_labels_delta": _build_count_delta(
                    _count_values(baseline_run.diagnostic_labels if baseline_run else []),
                    _count_values(candidate_run.diagnostic_labels if candidate_run else []),
                ),
            }
        )

    return {
        "baseline_strategy": baseline.strategy.name,
        "strategy": candidate.strategy.name,
        "tasks": tasks,
    }


def _load_eval_batch_result(summary_path: Path) -> EvalBatchResult:
    raw_data = json.loads(summary_path.read_text(encoding="utf-8"))
    run_results = [_load_eval_run_result(item) for item in raw_data.get("runs", [])]
    return EvalBatchResult(
        eval_name=str(raw_data.get("eval_name", "")).strip(),
        task_count=int(raw_data.get("task_count", 0)),
        success_count=int(raw_data.get("success_count", 0)),
        success_rate=float(raw_data.get("success_rate", 0.0)),
        failure_rate=float(raw_data.get("failure_rate", 0.0)),
        average_steps=float(raw_data.get("average_steps", 0.0)),
        average_tool_calls=float(raw_data.get("average_tool_calls", 0.0)),
        average_verify_count=float(raw_data.get("average_verify_count", 0.0)),
        average_reflect_count=float(raw_data.get("average_reflect_count", 0.0)),
        reflect_trigger_rate=float(raw_data.get("reflect_trigger_rate", 0.0)),
        clean_pass_count=int(raw_data.get("clean_pass_count", 0)),
        clean_pass_rate=float(raw_data.get("clean_pass_rate", 0.0)),
        warning_pass_count=int(raw_data.get("warning_pass_count", 0)),
        warning_rate=float(raw_data.get("warning_rate", 0.0)),
        verification_failure_rate=float(raw_data.get("verification_failure_rate", 0.0)),
        outcome_counts=_normalize_count_dict(raw_data.get("outcome_counts")),
        expectation_defined_count=int(raw_data.get("expectation_defined_count", 0)),
        expectation_matched_count=int(raw_data.get("expectation_matched_count", 0)),
        expectation_miss_count=int(raw_data.get("expectation_miss_count", 0)),
        expectation_miss_rate=float(raw_data.get("expectation_miss_rate", 0.0)),
        expectation_failure_counts=_normalize_count_dict(raw_data.get("expectation_failure_counts")),
        failure_distribution=_normalize_count_dict(raw_data.get("failure_distribution")),
        failure_taxonomy_counts=_normalize_count_dict(raw_data.get("failure_taxonomy_counts")),
        failure_taxonomy_tag_counts=_normalize_count_dict(raw_data.get("failure_taxonomy_tag_counts")),
        verification_failure_counts=_normalize_count_dict(raw_data.get("verification_failure_counts")),
        reflect_trigger_reason_counts=_normalize_count_dict(raw_data.get("reflect_trigger_reason_counts")),
        diagnostic_label_counts=_normalize_count_dict(raw_data.get("diagnostic_label_counts")),
        config_names=_normalize_string_list(raw_data.get("config_names")),
        context_strategies=_normalize_string_list(raw_data.get("context_strategies")),
        reflect_strategies=_normalize_string_list(raw_data.get("reflect_strategies")),
        memory_strategies=_normalize_string_list(raw_data.get("memory_strategies")),
        runs=run_results,
    )


def _load_eval_run_result(raw_run: Any) -> EvalRunResult:
    if not isinstance(raw_run, dict):
        raise ValueError("run item must be an object")
    return EvalRunResult(
        task_name=str(raw_run.get("task_name", "")).strip(),
        run_id=str(raw_run.get("run_id", "")).strip(),
        run_dir=str(raw_run.get("run_dir", "")).replace("\\", "/").strip(),
        passed=bool(raw_run.get("passed")),
        step_count=int(raw_run.get("step_count", 0)),
        tool_call_count=int(raw_run.get("tool_call_count", 0)),
        stop_reason=str(raw_run.get("stop_reason", "unknown")).strip(),
        verification_summary=str(raw_run.get("verification_summary", "")).strip(),
        failing_checks=_normalize_string_list(raw_run.get("failing_checks")),
        diagnostic_labels=_normalize_string_list(raw_run.get("diagnostic_labels")),
        outcome=str(raw_run.get("outcome", "failed_unknown")).strip() or "failed_unknown",
        expectation=_load_expectation_spec(raw_run.get("expectation")),
        expectation_result=_load_expectation_assessment(raw_run.get("expectation_result")),
        failure_taxonomy=_normalize_optional_string(raw_run.get("failure_taxonomy")),
        failure_taxonomy_tags=_normalize_string_list(raw_run.get("failure_taxonomy_tags")),
        verify_count=int(raw_run.get("verify_count", 0)),
        reflect_count=int(raw_run.get("reflect_count", 0)),
        reflect_triggered=bool(raw_run.get("reflect_triggered")),
        reflect_trigger_reason=str(raw_run.get("reflect_trigger_reason", "")).strip(),
        config_name=str(raw_run.get("config_name", "")).strip(),
        context_strategy=str(raw_run.get("context_strategy", "")).strip(),
        reflect_strategy=str(raw_run.get("reflect_strategy", "")).strip(),
        memory_enabled=bool(raw_run.get("memory_enabled")),
        memory_strategy=str(raw_run.get("memory_strategy", "")).strip(),
    )


def _build_markdown_count_lines(counts: dict[str, int], empty_text: str) -> str:
    if not counts:
        return empty_text
    return "\n".join(f"- `{key}`: `{value}`" for key, value in sorted(counts.items()))


def _build_verification_failure_lines(counts: dict[str, int]) -> str:
    if not counts:
        return "- no verification failures"
    return "\n".join(f"- 失败检查 `{key}`: `{value}`" for key, value in sorted(counts.items()))


def _classify_eval_outcome(
    passed: bool,
    stop_reason: str,
    diagnostic_labels: list[str] | Any,
    failing_checks: list[str],
) -> str:
    normalized_labels = _normalize_string_list(diagnostic_labels)
    if passed and not normalized_labels:
        return "passed_cleanly"
    if passed:
        return "passed_with_warnings"
    if failing_checks:
        return "failed_verification"
    if stop_reason != "completed":
        return "stopped_early"
    return "failed_unknown"


def _build_failure_taxonomy(outcome: str, stop_reason: str, failing_checks: list[str]) -> str | None:
    if outcome == "failed_verification":
        primary_check = failing_checks[0] if failing_checks else "unknown_check"
        return f"verification:{primary_check}"
    if outcome == "stopped_early":
        return f"stop_reason:{stop_reason}"
    if outcome == "failed_unknown":
        return "unknown_failure"
    return None


def _build_failure_taxonomy_tags(
    outcome: str,
    stop_reason: str,
    failing_checks: list[str],
    diagnostic_labels: list[str],
) -> list[str]:
    if outcome in {"passed_cleanly", "passed_with_warnings"}:
        return []

    tags = [f"outcome:{outcome}", f"stop_reason:{stop_reason}"]
    if failing_checks:
        tags.append(f"verification_check_count:{len(failing_checks)}")
        for check in failing_checks:
            tags.append(f"verification_check:{check}")
    for label in diagnostic_labels:
        tags.append(f"diagnostic_label:{label}")
    return tags


def _load_expectation_spec(raw_expectation: Any) -> EvalExpectationSpec | None:
    if not isinstance(raw_expectation, dict):
        return None
    return EvalExpectationSpec(
        passed=raw_expectation.get("passed") if isinstance(raw_expectation.get("passed"), bool) else None,
        outcome=_normalize_optional_string(raw_expectation.get("outcome")),
        min_step_count=_normalize_optional_int(raw_expectation.get("min_step_count")),
        max_step_count=_normalize_optional_int(raw_expectation.get("max_step_count")),
        min_tool_call_count=_normalize_optional_int(raw_expectation.get("min_tool_call_count")),
        max_tool_call_count=_normalize_optional_int(raw_expectation.get("max_tool_call_count")),
        required_failing_checks=_normalize_string_list(raw_expectation.get("required_failing_checks")),
        forbidden_failing_checks=_normalize_string_list(raw_expectation.get("forbidden_failing_checks")),
        required_diagnostic_labels=_normalize_string_list(raw_expectation.get("required_diagnostic_labels")),
        forbidden_diagnostic_labels=_normalize_string_list(raw_expectation.get("forbidden_diagnostic_labels")),
        failure_taxonomy=_normalize_optional_string(raw_expectation.get("failure_taxonomy")),
    )


def _load_expectation_assessment(raw_assessment: Any) -> EvalExpectationAssessment | None:
    if not isinstance(raw_assessment, dict):
        return None
    return EvalExpectationAssessment(
        defined=bool(raw_assessment.get("defined")),
        matched=bool(raw_assessment.get("matched", True)),
        failed_fields=_normalize_string_list(raw_assessment.get("failed_fields")),
    )


def _normalize_string_list(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[str] = []
    for item in raw_value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_optional_string(raw_value: Any) -> str | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    text = str(raw_value).strip()
    return text or None


def _normalize_optional_int(raw_value: Any) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return int(raw_value.strip())
        except ValueError:
            return None
    return None


def _normalize_count_dict(raw_value: Any) -> dict[str, int]:
    if not isinstance(raw_value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in raw_value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        try:
            normalized[key_text] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _assess_expectation(
    expectation: EvalExpectationSpec | None,
    passed: bool,
    outcome: str,
    step_count: int,
    tool_call_count: int,
    failing_checks: list[str],
    diagnostic_labels: list[str],
    failure_taxonomy: str | None,
) -> EvalExpectationAssessment:
    if not expectation:
        return EvalExpectationAssessment(defined=False, matched=True)

    failed_fields: list[str] = []
    if expectation.passed is not None and expectation.passed != passed:
        failed_fields.append("passed")
    if expectation.outcome and expectation.outcome != outcome:
        failed_fields.append("outcome")
    if expectation.min_step_count is not None and step_count < expectation.min_step_count:
        failed_fields.append("min_step_count")
    if expectation.max_step_count is not None and step_count > expectation.max_step_count:
        failed_fields.append("max_step_count")
    if expectation.min_tool_call_count is not None and tool_call_count < expectation.min_tool_call_count:
        failed_fields.append("min_tool_call_count")
    if expectation.max_tool_call_count is not None and tool_call_count > expectation.max_tool_call_count:
        failed_fields.append("max_tool_call_count")
    if expectation.failure_taxonomy and expectation.failure_taxonomy != (failure_taxonomy or ""):
        failed_fields.append("failure_taxonomy")

    failing_check_set = set(failing_checks)
    if any(check not in failing_check_set for check in expectation.required_failing_checks):
        failed_fields.append("required_failing_checks")
    if any(check in failing_check_set for check in expectation.forbidden_failing_checks):
        failed_fields.append("forbidden_failing_checks")

    diagnostic_label_set = set(diagnostic_labels)
    if any(label not in diagnostic_label_set for label in expectation.required_diagnostic_labels):
        failed_fields.append("required_diagnostic_labels")
    if any(label in diagnostic_label_set for label in expectation.forbidden_diagnostic_labels):
        failed_fields.append("forbidden_diagnostic_labels")

    return EvalExpectationAssessment(
        defined=True,
        matched=not failed_fields,
        failed_fields=failed_fields,
    )


def _extract_context_strategy(config_data: dict[str, Any]) -> str:
    context_config = config_data.get("context", {})
    if not isinstance(context_config, dict):
        return "file_recall_context"
    strategy = str(context_config.get("strategy", "file_recall_context")).strip()
    return strategy or "file_recall_context"


def _extract_reflect_strategy(config_data: dict[str, Any]) -> str:
    reflect_config = config_data.get("reflect", {})
    if not isinstance(reflect_config, dict):
        return "low_progress_plus_verify_reflect"
    strategy = str(reflect_config.get("strategy", "low_progress_plus_verify_reflect")).strip()
    return strategy or "low_progress_plus_verify_reflect"


def _extract_memory_enabled(config_data: dict[str, Any]) -> bool:
    memory_config = config_data.get("memory", {})
    if not isinstance(memory_config, dict):
        return False
    return bool(memory_config.get("enabled"))


def _extract_memory_strategy(config_data: dict[str, Any]) -> str:
    return "structured_memory_on" if _extract_memory_enabled(config_data) else "memory_off"


def _build_count_delta(baseline_counts: dict[str, int], candidate_counts: dict[str, int]) -> dict[str, int]:
    all_keys = sorted(set(baseline_counts) | set(candidate_counts))
    delta: dict[str, int] = {}
    for key in all_keys:
        change = candidate_counts.get(key, 0) - baseline_counts.get(key, 0)
        if change:
            delta[key] = change
    return delta


def _format_count_delta(count_delta: dict[str, int]) -> str:
    if not count_delta:
        return "none"
    return ", ".join(f"{key}: {value:+d}" for key, value in sorted(count_delta.items()))


def _count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _task_delta_changed(baseline_run: EvalRunResult | None, candidate_run: EvalRunResult | None) -> bool:
    if baseline_run is None or candidate_run is None:
        return True
    return any(
        [
            baseline_run.outcome != candidate_run.outcome,
            baseline_run.passed != candidate_run.passed,
            baseline_run.step_count != candidate_run.step_count,
            baseline_run.tool_call_count != candidate_run.tool_call_count,
            baseline_run.verify_count != candidate_run.verify_count,
            baseline_run.reflect_count != candidate_run.reflect_count,
            baseline_run.reflect_trigger_reason != candidate_run.reflect_trigger_reason,
            (baseline_run.failure_taxonomy or "") != (candidate_run.failure_taxonomy or ""),
            baseline_run.failing_checks != candidate_run.failing_checks,
            baseline_run.diagnostic_labels != candidate_run.diagnostic_labels,
        ]
    )


def _load_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        events.append(json.loads(stripped))
    return events


def _find_last_payload(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event_type") == event_type:
            payload = event.get("payload", {})
            return payload if isinstance(payload, dict) else {}
    return {}
