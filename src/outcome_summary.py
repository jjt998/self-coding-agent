"""任务完成总览生成模块。

本模块分两层处理最终总结：
1. facts 层由 harness 根据运行状态、验证结果、diff 产物确定性生成。
2. polished_text 层只把 facts 改写成自然语言，不允许重新判断任务是否成功。
"""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from config import RunSettings
from model import ModelError, ModelResponseError, build_model_adapter


def build_task_outcome_facts(
    *,
    settings: RunSettings | None,
    runtime_state: Any,
    final_diff_artifact_result: Any | None = None,
    sandbox_cleanup_result: Any | None = None,
) -> dict[str, Any]:
    """构建报告、trace 和 eval 共用的确定性任务结果事实层。"""
    verification_result = getattr(runtime_state, "verification_result", None)
    stop_reason = getattr(runtime_state, "stop_reason", None)
    stop_code = ""
    stop_message = ""
    stop_details: dict[str, Any] = {}
    if stop_reason:
        stop_code = str(getattr(getattr(stop_reason, "code", ""), "value", getattr(stop_reason, "code", "")))
        stop_message = str(getattr(stop_reason, "message", ""))
        raw_details = getattr(stop_reason, "details", {})
        stop_details = raw_details if isinstance(raw_details, dict) else {}

    verification_passed = bool(verification_result and getattr(verification_result, "passed", False))
    status = _classify_status(stop_code=stop_code, verification_passed=verification_passed)
    failing_checks = _build_failing_checks(verification_result)
    changed_files = _normalize_string_list(getattr(runtime_state, "changed_files", []))
    task_text = settings.task if settings else str(getattr(runtime_state, "task", ""))
    task_type = settings.task_type if settings else str(getattr(runtime_state, "task_type", ""))

    facts = {
        "status": status,
        "headline": _build_headline(status=status, changed_files=changed_files, failing_checks=failing_checks),
        "task": {
            "text": task_text,
            "task_type": task_type,
        },
        "changed_files": changed_files,
        "actions_taken": _build_actions_taken(runtime_state=runtime_state, changed_files=changed_files),
        "rationale_trace": _build_rationale_trace(runtime_state=runtime_state),
        "verification": {
            "passed": verification_passed,
            "summary": str(getattr(verification_result, "summary", "")) if verification_result else "",
            "failing_checks": failing_checks,
        },
        "commands": _build_command_summaries(
            verification_result=verification_result,
            stop_details=stop_details,
        ),
        "metrics": _build_metrics(runtime_state=runtime_state),
        "artifacts": _build_artifacts(
            final_diff_artifact_result=final_diff_artifact_result,
            sandbox_cleanup_result=sandbox_cleanup_result,
        ),
        "stop_reason": {
            "code": stop_code or "unknown",
            "message": stop_message,
        },
    }
    return facts


def build_task_outcome_summary(
    *,
    facts: dict[str, Any],
    config_data: dict[str, Any],
) -> dict[str, Any]:
    """构建最终任务总结；按配置决定是否调用模型润色。"""
    if not _summary_enabled(config_data):
        return {
            "facts": facts,
            "polished_text": format_task_outcome_facts_markdown(facts),
            "polish_status": "skipped",
            "polish_error": "",
        }
    if not _model_polish_enabled(config_data):
        return {
            "facts": facts,
            "polished_text": format_task_outcome_facts_markdown(facts),
            "polish_status": "skipped",
            "polish_error": "",
        }
    try:
        polished_payload = polish_task_outcome_summary(facts=facts, config_data=config_data)
        polished_text = str(polished_payload.get("polished_text", "")).strip()
        if not polished_text:
            raise ModelResponseError(
                "任务完成总览润色响应缺少 polished_text",
                details={"field_path": "polished_text"},
            )
        return {
            "facts": facts,
            "polished_text": polished_text,
            "polish_status": "success",
            "polish_error": "",
        }
    except Exception as error:
        return {
            "facts": facts,
            "polished_text": format_task_outcome_facts_markdown(facts),
            "polish_status": "failed",
            "polish_error": _safe_error_summary(error),
        }


def polish_task_outcome_summary(*, facts: dict[str, Any], config_data: dict[str, Any]) -> dict[str, Any]:
    """调用当前配置的模型，把事实层改写成面向用户的简洁总结。"""
    polish_config = _task_outcome_config(config_data)
    adapter_config = dict(config_data)
    model_config = dict(adapter_config.get("model", {})) if isinstance(adapter_config.get("model"), dict) else {}
    timeout_seconds = polish_config.get("polish_timeout_seconds")
    if timeout_seconds:
        model_config["timeout_seconds"] = timeout_seconds
        adapter_config["model"] = model_config
    adapter = build_model_adapter(config_data=adapter_config)
    if not hasattr(adapter, "complete_json"):
        raise ModelResponseError("模型适配器不支持通用 JSON completion")
    return adapter.complete_json(_build_polish_request_payload(facts=facts))  # type: ignore[attr-defined]


def format_task_outcome_facts_markdown(facts: dict[str, Any]) -> str:
    """把事实层格式化成确定性的 Markdown 兜底文本。"""
    verification = facts.get("verification", {}) if isinstance(facts.get("verification"), dict) else {}
    metrics = facts.get("metrics", {}) if isinstance(facts.get("metrics"), dict) else {}
    artifacts = facts.get("artifacts", {}) if isinstance(facts.get("artifacts"), dict) else {}
    changed_files = _normalize_string_list(facts.get("changed_files", []))
    actions = _normalize_string_list(facts.get("actions_taken", []))
    failing_checks = _normalize_string_list(verification.get("failing_checks", []))
    lines = [
        str(facts.get("headline", "任务完成总览。")),
        "",
        f"- 状态：`{facts.get('status', 'unknown')}`",
        f"- 验证：`{'passed' if verification.get('passed') else 'failed'}`；{verification.get('summary', '')}",
        f"- 变更文件：`{', '.join(changed_files) if changed_files else 'none'}`",
        f"- 执行动作：{'；'.join(actions) if actions else 'none'}",
        f"- 失败检查：`{', '.join(failing_checks) if failing_checks else 'none'}`",
        f"- 推理轨迹：`{len(facts.get('rationale_trace', [])) if isinstance(facts.get('rationale_trace'), list) else 0}` 轮",
        (
            f"- 指标：steps `{metrics.get('steps', 0)}`，iterations `{metrics.get('iterations', 0)}`，"
            f"tool calls `{metrics.get('tool_calls', 0)}`，observe `{metrics.get('observe_count', 0)}`"
        ),
        f"- 产物：`{', '.join(_normalize_string_list(artifacts.get('paths', []))) or 'none'}`",
    ]
    return "\n".join(lines)


def truncate_eval_summary_text(value: str, limit: int = 160) -> str:
    """截断 eval 汇总行里的短摘要；完整文本仍保留在单次 run 产物中。"""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "...[truncated]"


def _build_polish_request_payload(*, facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你负责把确定性的任务完成事实改写成简洁、自然、面向用户的中文总结。"
                    "只能改写提供的 facts，不得编造文件、命令、检查项或结果。"
                    "请重点参考 facts.rationale_trace，总结 agent 调查了什么、哪些判断发生变化、"
                    "为什么选择这些步骤，以及最后如何收口。"
                    "除非 facts.verification.passed 为 true，否则不得声称验证通过。"
                    "如果存在失败检查，必须明确说明。只返回 JSON。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "facts": facts,
                        "output_schema": {
                            "polished_text": (
                                "中文纯文本。使用一段简短总述和 2-4 个短 bullet。"
                                "需要包含发生了什么、rationale_trace 中的关键动作/转折点、"
                                "改了什么、验证结果，以及失败时下一步应看哪里。"
                                "控制在 300-500 个中文字符以内。"
                            ),
                            "confidence_notes": ["可选的简短说明"],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _summary_enabled(config_data: dict[str, Any]) -> bool:
    config = _task_outcome_config(config_data)
    return bool(config.get("enabled", True))


def _model_polish_enabled(config_data: dict[str, Any]) -> bool:
    config = _task_outcome_config(config_data)
    return bool(config.get("model_polish", True))


def _task_outcome_config(config_data: dict[str, Any]) -> dict[str, Any]:
    report_config = config_data.get("report", {})
    if not isinstance(report_config, dict):
        return {}
    summary_config = report_config.get("task_outcome_summary", {})
    return summary_config if isinstance(summary_config, dict) else {}


def _classify_status(*, stop_code: str, verification_passed: bool) -> str:
    if verification_passed:
        return "passed"
    if stop_code == "verification_failed":
        return "failed_verification"
    if stop_code == "setup_failed":
        return "failed_setup"
    if stop_code == "model_error":
        return "model_error"
    if stop_code == "max_steps_reached":
        return "max_steps_reached"
    if stop_code == "completed" and not verification_passed:
        return "failed_verification"
    return "unknown"


def _build_headline(*, status: str, changed_files: list[str], failing_checks: list[str]) -> str:
    if status == "passed":
        return f"任务完成并通过验证，最终变更 {len(changed_files)} 个文件。"
    if status == "failed_verification":
        checks = ", ".join(failing_checks) if failing_checks else "unknown"
        return f"任务已执行但验证未通过，失败检查：{checks}。"
    if status == "failed_setup":
        return "任务在 setup 阶段失败，未进入完整求解流程。"
    if status == "model_error":
        return "任务因模型调用或模型响应错误停止。"
    if status == "max_steps_reached":
        return "任务达到最大步骤数后停止。"
    return "任务已结束，结果状态未知。"


def _build_failing_checks(verification_result: Any) -> list[str]:
    checks = getattr(verification_result, "checks", []) if verification_result else []
    failing: list[str] = []
    for check in checks:
        if not bool(getattr(check, "passed", False)):
            name = str(getattr(check, "name", "")).strip()
            if name:
                failing.append(name)
    return failing


def _build_actions_taken(*, runtime_state: Any, changed_files: list[str]) -> list[str]:
    actions: list[str] = []
    tool_executions = getattr(runtime_state, "tool_executions", []) or []
    for execution in tool_executions:
        tool_name = str(getattr(execution, "tool_name", "unknown")).strip() or "unknown"
        tool_input = getattr(execution, "tool_input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        target = tool_input.get("path") or tool_input.get("query") or tool_input.get("command")
        if isinstance(target, list):
            target = " ".join(str(item) for item in target[:6])
        action = f"{tool_name}"
        if target:
            action += f": {str(target)[:120]}"
        actions.append(action)
    for path in changed_files:
        action = f"changed file: {path}"
        if action not in actions:
            actions.append(action)
    return actions[:20]


def _build_rationale_trace(*, runtime_state: Any) -> list[dict[str, Any]]:
    """把每轮模型 rationale（推理理由）暴露为最终润色可参考的事实上下文。"""
    trace: list[dict[str, Any]] = []
    model_decisions = getattr(runtime_state, "model_decisions", []) or []
    for index, decision in enumerate(model_decisions, start=1):
        rationale = str(getattr(decision, "rationale", "") or "").strip()
        summary = str(getattr(decision, "summary", "") or "").strip()
        planned_actions = getattr(decision, "planned_actions", []) or []
        if not rationale and not summary and not planned_actions:
            continue
        trace.append(
            {
                "iteration": index,
                "summary": summary,
                "rationale": rationale,
                "planned_actions": _normalize_string_list(list(planned_actions) if isinstance(planned_actions, list) else []),
            }
        )
    return trace


def _build_command_summaries(*, verification_result: Any, stop_details: dict[str, Any]) -> list[dict[str, Any]]:
    command_results: list[dict[str, Any]] = []
    details = getattr(verification_result, "details", {}) if verification_result else {}
    if not isinstance(details, dict):
        details = {}
    for field_name in [
        "verify_setup_command_results",
        "verify_command_results",
        "verify_cleanup_command_results",
    ]:
        raw_items = details.get(field_name, [])
        if isinstance(raw_items, list):
            command_results.extend(_summarize_command(item, source=field_name) for item in raw_items if isinstance(item, dict))
    for field_name in ["failed_setup_commands", "setup_results"]:
        raw_items = stop_details.get(field_name, [])
        if isinstance(raw_items, list):
            command_results.extend(_summarize_command(item, source=field_name) for item in raw_items if isinstance(item, dict))
    return command_results[:20]


def _summarize_command(item: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "command": item.get("command", []),
        "returncode": item.get("returncode"),
        "ok": bool(item.get("ok")),
        "stdout": _first_nonempty_line(str(item.get("stdout", ""))),
        "stderr": _first_nonempty_line(str(item.get("stderr", ""))),
    }


def _build_metrics(*, runtime_state: Any) -> dict[str, Any]:
    token_usage = getattr(runtime_state, "token_usage", {})
    if not isinstance(token_usage, dict):
        token_usage = {}
    return {
        "steps": int(getattr(runtime_state, "step_count", 0) or 0),
        "iterations": int(getattr(runtime_state, "iteration_count", 0) or 0),
        "tool_calls": len(getattr(runtime_state, "tool_executions", []) or []),
        "observe_count": int(getattr(runtime_state, "observe_count", 0) or 0),
        "token_usage": dict(token_usage),
    }


def _build_artifacts(*, final_diff_artifact_result: Any | None, sandbox_cleanup_result: Any | None) -> dict[str, Any]:
    paths = ["report.md", "trace.jsonl"]
    payload: dict[str, Any] = {"paths": paths}
    if final_diff_artifact_result is not None:
        payload["final_diff"] = _dataclass_or_dict(final_diff_artifact_result)
        if getattr(final_diff_artifact_result, "written", False):
            paths.append("final_diff.patch")
    if sandbox_cleanup_result is not None:
        payload["sandbox_cleanup"] = _dataclass_or_dict(sandbox_cleanup_result)
    return payload


def _dataclass_or_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value if isinstance(value, dict) else {}


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _first_nonempty_line(value: str, limit: int = 240) -> str:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


def _safe_error_summary(error: Exception) -> str:
    if isinstance(error, ModelError):
        return f"{type(error).__name__}: {str(error)[:300]}"
    return f"{type(error).__name__}: {str(error)[:300]}"
