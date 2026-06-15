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
    """描述一条评测任务希望看到的最小结果断言。"""

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
        """转换成便于写入 summary 的字典。"""
        return asdict(self)


@dataclass(slots=True)
class EvalExpectationAssessment:
    """保存实际结果与期望字段的对照结论。"""

    defined: bool
    matched: bool
    failed_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 summary 的字典。"""
        return asdict(self)


@dataclass(slots=True)
class EvalTaskSpec:
    """描述一条可批量执行的评测任务。"""

    name: str
    task: str
    task_type: str = "general"
    repo_root: str | None = None
    config_name: str | None = None
    expectation: EvalExpectationSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 summary 的字典。"""
        data = asdict(self)
        data["expectation"] = self.expectation.to_dict() if self.expectation else None
        return data


@dataclass(slots=True)
class EvalRunResult:
    """保存单条评测任务执行后的关键结果。"""

    task_name: str
    run_id: str
    run_dir: str
    passed: bool
    step_count: int
    tool_call_count: int
    stop_reason: str
    diagnostic_labels: list[str] = field(default_factory=list)
    outcome: str = "unknown"
    verification_summary: str = ""
    failing_checks: list[str] = field(default_factory=list)
    failure_taxonomy: str | None = None
    failure_taxonomy_tags: list[str] = field(default_factory=list)
    expectation: EvalExpectationSpec | None = None
    expectation_result: EvalExpectationAssessment | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 summary 的字典。"""
        data = asdict(self)
        data["expectation"] = self.expectation.to_dict() if self.expectation else None
        data["expectation_result"] = self.expectation_result.to_dict() if self.expectation_result else None
        return data


@dataclass(slots=True)
class EvalBatchResult:
    """保存一批评测任务的聚合结果。"""

    eval_name: str
    task_count: int
    success_count: int
    success_rate: float
    failure_rate: float
    average_steps: float
    average_tool_calls: float
    clean_pass_count: int = 0
    clean_pass_rate: float = 0.0
    warning_pass_count: int = 0
    warning_rate: float = 0.0
    outcome_counts: dict[str, int] = field(default_factory=dict)
    expectation_defined_count: int = 0
    expectation_matched_count: int = 0
    expectation_miss_count: int = 0
    expectation_miss_rate: float = 0.0
    verification_failure_rate: float = 0.0
    expectation_failure_counts: dict[str, int] = field(default_factory=dict)
    failure_distribution: dict[str, int] = field(default_factory=dict)
    failure_taxonomy_counts: dict[str, int] = field(default_factory=dict)
    failure_taxonomy_tag_counts: dict[str, int] = field(default_factory=dict)
    verification_failure_counts: dict[str, int] = field(default_factory=dict)
    diagnostic_label_counts: dict[str, int] = field(default_factory=dict)
    runs: list[EvalRunResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 JSON summary 的字典。"""
        data = asdict(self)
        data["runs"] = [run.to_dict() for run in self.runs]
        return data


def load_eval_task_specs(task_file: Path) -> list[EvalTaskSpec]:
    """读取 JSON 任务文件，并转换成结构化评测任务列表。"""
    raw_data = json.loads(task_file.read_text(encoding="utf-8"))
    raw_tasks = raw_data.get("tasks", []) if isinstance(raw_data, dict) else []
    task_specs: list[EvalTaskSpec] = []
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            continue
        task_text = str(item.get("task", "")).strip()
        if not task_text:
            continue
        task_specs.append(
            EvalTaskSpec(
                name=str(item.get("name", f"task_{index + 1}")).strip() or f"task_{index + 1}",
                task=task_text,
                task_type=str(item.get("task_type", "general")).strip() or "general",
                repo_root=str(item.get("repo_root", "")).strip() or None,
                config_name=str(item.get("config_name", "")).strip() or None,
                expectation=_load_expectation_spec(item.get("expectation")),
            )
        )
    return task_specs


def run_eval_batch(
    task_file: Path,
    repo_root: str,
    output_root: str,
    config_name: str,
) -> Path:
    """批量执行任务文件里的评测项，并生成聚合 summary。"""
    task_specs = load_eval_task_specs(task_file=task_file)
    if not task_specs:
        raise ValueError("评测任务文件中没有可执行任务。")
    eval_name = task_file.stem
    eval_dir = Path(output_root) / f"eval-{eval_name}"
    eval_runs_root = eval_dir / "runs"
    eval_dir.mkdir(parents=True, exist_ok=False)
    eval_runs_root.mkdir(parents=True, exist_ok=False)

    run_results: list[EvalRunResult] = []
    for task_spec in task_specs:
        current_repo_root = task_spec.repo_root or repo_root
        current_config_name = task_spec.config_name or config_name
        settings = build_settings(
            task=task_spec.task,
            task_type=task_spec.task_type,
            repo_root=current_repo_root,
            output_root=str(eval_runs_root),
            config_name=current_config_name,
        )
        config_data = load_named_config(config_dir=Path("configs"), config_name=current_config_name)
        run_dir = execute_initial_run(settings=settings, config_data=config_data)
        run_results.append(
            _collect_eval_run_result(
                task_spec=task_spec,
                run_id=settings.run_id,
                run_dir=run_dir,
            )
        )

    batch_result = _build_eval_batch_result(eval_name=eval_name, run_results=run_results)
    (eval_dir / "summary.json").write_text(
        json.dumps(batch_result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (eval_dir / "summary.md").write_text(
        _build_eval_summary_markdown(
            task_file=task_file,
            batch_result=batch_result,
        ),
        encoding="utf-8",
    )
    return eval_dir


def _collect_eval_run_result(task_spec: EvalTaskSpec, run_id: str, run_dir: Path) -> EvalRunResult:
    """从单次 run 的 trace 中回收最小评测指标。"""
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verification_payload = next(
        (event["payload"] for event in trace_events if event["event_type"] == "verification_result"),
        {},
    )
    run_finished_payload = next(
        (event["payload"] for event in trace_events if event["event_type"] == "run_finished"),
        {},
    )
    context_payload = next(
        (event["payload"] for event in trace_events if event["event_type"] == "context_snapshot"),
        {},
    )
    tool_call_count = sum(1 for event in trace_events if event["event_type"] == "tool_called")
    diagnostic_labels = context_payload.get("memory_context", {}).get("diagnostic_labels", [])
    stop_reason = run_finished_payload.get("stop_reason", {}).get("code", "unknown")
    verification_summary = str(verification_payload.get("summary", ""))
    failing_checks = [
        str(check.get("name", "unknown"))
        for check in verification_payload.get("checks", [])
        if isinstance(check, dict) and not bool(check.get("passed", False))
    ]
    outcome = _classify_eval_outcome(
        passed=bool(verification_payload.get("passed", False)),
        stop_reason=str(stop_reason),
        diagnostic_labels=diagnostic_labels,
        failing_checks=failing_checks,
    )
    failure_taxonomy = _build_failure_taxonomy(
        outcome=outcome,
        stop_reason=str(stop_reason),
        failing_checks=failing_checks,
    )
    normalized_diagnostic_labels = list(diagnostic_labels) if isinstance(diagnostic_labels, list) else []
    failure_taxonomy_tags = _build_failure_taxonomy_tags(
        outcome=outcome,
        stop_reason=str(stop_reason),
        failing_checks=failing_checks,
        diagnostic_labels=normalized_diagnostic_labels,
    )
    expectation_result = _assess_expectation(
        expectation=task_spec.expectation,
        passed=bool(verification_payload.get("passed", False)),
        outcome=outcome,
        step_count=int(run_finished_payload.get("step_count", 0)),
        tool_call_count=tool_call_count,
        failing_checks=failing_checks,
        diagnostic_labels=normalized_diagnostic_labels,
        failure_taxonomy=failure_taxonomy,
    )
    return EvalRunResult(
        task_name=task_spec.name,
        run_id=run_id,
        run_dir=str(run_dir),
        passed=bool(verification_payload.get("passed", False)),
        step_count=int(run_finished_payload.get("step_count", 0)),
        tool_call_count=tool_call_count,
        stop_reason=str(stop_reason),
        diagnostic_labels=normalized_diagnostic_labels,
        outcome=outcome,
        verification_summary=verification_summary,
        failing_checks=failing_checks,
        failure_taxonomy=failure_taxonomy,
        failure_taxonomy_tags=failure_taxonomy_tags,
        expectation=task_spec.expectation,
        expectation_result=expectation_result,
    )


def _build_eval_batch_result(eval_name: str, run_results: list[EvalRunResult]) -> EvalBatchResult:
    """把单条 run 结果汇总成最小聚合指标。"""
    task_count = len(run_results)
    success_count = sum(1 for item in run_results if item.passed)
    clean_pass_count = sum(1 for item in run_results if item.outcome == "passed_cleanly")
    warning_pass_count = sum(1 for item in run_results if item.outcome == "passed_with_warnings")
    verification_failure_count = sum(1 for item in run_results if item.outcome == "failed_verification")
    outcome_counts: dict[str, int] = {}
    expectation_defined_count = 0
    expectation_matched_count = 0
    expectation_failure_counts: dict[str, int] = {}
    failure_distribution: dict[str, int] = {}
    failure_taxonomy_counts: dict[str, int] = {}
    failure_taxonomy_tag_counts: dict[str, int] = {}
    verification_failure_counts: dict[str, int] = {}
    diagnostic_label_counts: dict[str, int] = {}
    for item in run_results:
        outcome_counts[item.outcome] = outcome_counts.get(item.outcome, 0) + 1
        if item.expectation_result and item.expectation_result.defined:
            expectation_defined_count += 1
            if item.expectation_result.matched:
                expectation_matched_count += 1
            for failed_field in item.expectation_result.failed_fields:
                expectation_failure_counts[failed_field] = expectation_failure_counts.get(failed_field, 0) + 1
        if not item.passed:
            failure_distribution[item.stop_reason] = failure_distribution.get(item.stop_reason, 0) + 1
        if item.failure_taxonomy:
            failure_taxonomy_counts[item.failure_taxonomy] = failure_taxonomy_counts.get(item.failure_taxonomy, 0) + 1
        for taxonomy_tag in item.failure_taxonomy_tags:
            failure_taxonomy_tag_counts[taxonomy_tag] = failure_taxonomy_tag_counts.get(taxonomy_tag, 0) + 1
        for check_name in item.failing_checks:
            verification_failure_counts[check_name] = verification_failure_counts.get(check_name, 0) + 1
        for label in item.diagnostic_labels:
            diagnostic_label_counts[label] = diagnostic_label_counts.get(label, 0) + 1
    return EvalBatchResult(
        eval_name=eval_name,
        task_count=task_count,
        success_count=success_count,
        success_rate=(success_count / task_count) if task_count else 0.0,
        failure_rate=((task_count - success_count) / task_count) if task_count else 0.0,
        average_steps=mean(item.step_count for item in run_results) if run_results else 0.0,
        average_tool_calls=mean(item.tool_call_count for item in run_results) if run_results else 0.0,
        clean_pass_count=clean_pass_count,
        clean_pass_rate=(clean_pass_count / task_count) if task_count else 0.0,
        warning_pass_count=warning_pass_count,
        warning_rate=(warning_pass_count / task_count) if task_count else 0.0,
        outcome_counts=outcome_counts,
        expectation_defined_count=expectation_defined_count,
        expectation_matched_count=expectation_matched_count,
        expectation_miss_count=expectation_defined_count - expectation_matched_count,
        expectation_miss_rate=((expectation_defined_count - expectation_matched_count) / expectation_defined_count)
        if expectation_defined_count
        else 0.0,
        verification_failure_rate=(verification_failure_count / task_count) if task_count else 0.0,
        expectation_failure_counts=expectation_failure_counts,
        failure_distribution=failure_distribution,
        failure_taxonomy_counts=failure_taxonomy_counts,
        failure_taxonomy_tag_counts=failure_taxonomy_tag_counts,
        verification_failure_counts=verification_failure_counts,
        diagnostic_label_counts=diagnostic_label_counts,
        runs=run_results,
    )


def _build_eval_summary_markdown(task_file: Path, batch_result: EvalBatchResult) -> str:
    """生成一份聚焦聚合指标的最小评测报告。"""
    run_lines = []
    for item in batch_result.runs:
        warning_text = (
            f"，诊断 `{', '.join(item.diagnostic_labels)}`"
            if item.diagnostic_labels
            else ""
        )
        failing_check_text = (
            f"，失败检查 `{', '.join(item.failing_checks)}`"
            if item.failing_checks
            else ""
        )
        taxonomy_tag_text = (
            f"，taxonomy tags `{', '.join(item.failure_taxonomy_tags)}`"
            if item.failure_taxonomy_tags
            else ""
        )
        expectation_text = ""
        if item.expectation_result and item.expectation_result.defined:
            expectation_text = (
                "，expectation 匹配"
                if item.expectation_result.matched
                else f"，expectation 未命中 `{', '.join(item.expectation_result.failed_fields)}`"
            )
        run_lines.append(
            f"- `{item.task_name}`：{'通过' if item.passed else '未通过'}，"
            f"步数 `{item.step_count}`，工具调用 `{item.tool_call_count}`，"
            f"stop reason `{item.stop_reason}`，"
            f"结果分层 `{item.outcome}`"
            f"{warning_text}"
            f"{failing_check_text}"
            f"{taxonomy_tag_text}"
            f"{expectation_text}"
        )
    outcome_lines = (
        "\n".join(f"- `{key}`：`{value}` 次" for key, value in sorted(batch_result.outcome_counts.items()))
        if batch_result.outcome_counts
        else "- 无结果分层统计。"
    )
    failure_lines = (
        "\n".join(f"- `{key}`：`{value}` 次" for key, value in sorted(batch_result.failure_distribution.items()))
        if batch_result.failure_distribution
        else "- 无失败分布。"
    )
    taxonomy_lines = (
        "\n".join(
            f"- `{key}`：`{value}` 次" for key, value in sorted(batch_result.failure_taxonomy_counts.items())
        )
        if batch_result.failure_taxonomy_counts
        else "- 无 failure taxonomy。"
    )
    taxonomy_tag_lines = (
        "\n".join(
            f"- `{key}`：`{value}` 次" for key, value in sorted(batch_result.failure_taxonomy_tag_counts.items())
        )
        if batch_result.failure_taxonomy_tag_counts
        else "- 无 failure taxonomy tags。"
    )
    verification_failure_lines = (
        "\n".join(
            f"- `{key}`：`{value}` 次"
            for key, value in sorted(batch_result.verification_failure_counts.items())
        )
        if batch_result.verification_failure_counts
        else "- 无验证失败检查项。"
    )
    expectation_lines = (
        "\n".join(
            f"- `{key}`：`{value}` 次"
            for key, value in sorted(batch_result.expectation_failure_counts.items())
        )
        if batch_result.expectation_failure_counts
        else "- 无 expectation 失配字段。"
    )
    diagnostic_lines = (
        "\n".join(f"- `{key}`：`{value}` 次" for key, value in sorted(batch_result.diagnostic_label_counts.items()))
        if batch_result.diagnostic_label_counts
        else "- 无诊断标签。"
    )
    return (
        f"# 评测汇总\n\n"
        f"- 任务文件：`{task_file}`\n"
        f"- 任务总数：`{batch_result.task_count}`\n"
        f"- 成功数：`{batch_result.success_count}`\n"
        f"- 成功率：`{batch_result.success_rate:.2f}`\n"
        f"- 失败率：`{batch_result.failure_rate:.2f}`\n"
        f"- 平均步数：`{batch_result.average_steps:.2f}`\n"
        f"- 平均工具调用数：`{batch_result.average_tool_calls:.2f}`\n"
        f"- 干净成功：`{batch_result.clean_pass_count}`\n"
        f"- 干净成功率：`{batch_result.clean_pass_rate:.2f}`\n"
        f"- 带警告成功：`{batch_result.warning_pass_count}`\n"
        f"- 警告率：`{batch_result.warning_rate:.2f}`\n"
        f"- 验证失败率：`{batch_result.verification_failure_rate:.2f}`\n"
        f"- 定义 expectation 的任务数：`{batch_result.expectation_defined_count}`\n"
        f"- expectation 命中数：`{batch_result.expectation_matched_count}`\n"
        f"- expectation 失配数：`{batch_result.expectation_miss_count}`\n"
        f"- expectation 失配率：`{batch_result.expectation_miss_rate:.2f}`\n\n"
        f"## 结果分层\n\n"
        f"{outcome_lines}\n\n"
        f"## Expectation 对照\n\n"
        f"{expectation_lines}\n\n"
        f"## 失败分布\n\n"
        f"{failure_lines}\n\n"
        f"## Failure Taxonomy\n\n"
        f"{taxonomy_lines}\n\n"
        f"## Failure Taxonomy Tags\n\n"
        f"{taxonomy_tag_lines}\n\n"
        f"## 验证失败检查项\n\n"
        f"{verification_failure_lines}\n\n"
        f"## 诊断标签\n\n"
        f"{diagnostic_lines}\n\n"
        f"## 运行明细\n\n"
        f"{chr(10).join(run_lines) if run_lines else '- 无 run。'}\n"
    )


def _classify_eval_outcome(
    passed: bool,
    stop_reason: str,
    diagnostic_labels: list[str] | Any,
    failing_checks: list[str],
) -> str:
    """给单条 run 一个稳定的结果分层，便于区分风险成功与真正失败。"""
    labels = list(diagnostic_labels) if isinstance(diagnostic_labels, list) else []
    if passed:
        return "passed_with_warnings" if labels else "passed_cleanly"
    if stop_reason != "completed":
        return "stopped_early"
    if failing_checks:
        return "failed_verification"
    return "failed_unknown"


def _build_failure_taxonomy(outcome: str, stop_reason: str, failing_checks: list[str]) -> str | None:
    """把失败进一步整理成可聚合的 taxonomy key。"""
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
    """生成多维失败标签，避免只靠单个 primary taxonomy 丢失诊断线索。"""
    if outcome in {"passed_cleanly", "passed_with_warnings"}:
        return []
    tags = [f"outcome:{outcome}", f"stop_reason:{stop_reason}"]
    if outcome == "failed_verification":
        tags.append(f"verification_check_count:{len(failing_checks)}")
        tags.extend(f"verification_check:{check_name}" for check_name in failing_checks)
    tags.extend(f"diagnostic_label:{label}" for label in diagnostic_labels)
    return tags


def _load_expectation_spec(raw_expectation: Any) -> EvalExpectationSpec | None:
    """把任务文件里的 expectation 字段解析成结构化对象。"""
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


def _normalize_string_list(raw_value: Any) -> list[str]:
    """把任意输入收敛成稳定的字符串列表。"""
    if not isinstance(raw_value, list):
        return []
    return [str(item).strip() for item in raw_value if str(item).strip()]


def _normalize_optional_string(raw_value: Any) -> str | None:
    """把 expectation 里的可选字符串断言收敛成稳定字符串。"""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def _normalize_optional_int(raw_value: Any) -> int | None:
    """把 expectation 里的可选整数断言收敛成 int。"""
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return int(raw_value.strip())
        except ValueError:
            return None
    return None


def _assess_expectation(
    expectation: EvalExpectationSpec | None,
    passed: bool,
    outcome: str,
    step_count: int,
    tool_call_count: int,
    failing_checks: list[str],
    diagnostic_labels: list[str],
    failure_taxonomy: str | None,
) -> EvalExpectationAssessment | None:
    """比较实际结果和 expectation，输出最小失配信息。"""
    if not expectation:
        return None
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
    label_set = set(diagnostic_labels)
    if any(label not in label_set for label in expectation.required_diagnostic_labels):
        failed_fields.append("required_diagnostic_labels")
    if any(label in label_set for label in expectation.forbidden_diagnostic_labels):
        failed_fields.append("forbidden_diagnostic_labels")
    return EvalExpectationAssessment(
        defined=True,
        matched=not failed_fields,
        failed_fields=failed_fields,
    )
