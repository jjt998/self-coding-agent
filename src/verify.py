from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from config import RunSettings
from tools import ToolExecution


@dataclass(slots=True)
class VerificationCheck:
    """表示一条具体检查项，以及它是否通过。"""

    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        return asdict(self)


@dataclass(slots=True)
class VerificationResult:
    """汇总本次 run 的验证结论和每条检查项。"""

    passed: bool
    summary: str
    checks: list[VerificationCheck] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于写入 trace 和报告的字典。"""
        data = asdict(self)
        data["checks"] = [check.to_dict() for check in self.checks]
        return data


@dataclass(slots=True)
class VerifyCommandResult:
    """记录一条真实 verify 命令的执行结果，供 trace 和报告复用。"""

    command: list[str]
    cwd: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        """把 verify 命令结果转成普通字典。"""
        return asdict(self)


def build_phase_4_verification(settings: RunSettings, tool_executions: list[ToolExecution]) -> VerificationResult:
    """根据任务设置决定走真实 verify 还是旧的演示型 verify。"""
    if settings.verify_commands:
        return _build_task_command_verification(settings=settings, tool_executions=tool_executions)
    return _build_stub_tool_verification(tool_executions=tool_executions)


def _build_stub_tool_verification(tool_executions: list[ToolExecution]) -> VerificationResult:
    """根据工具执行结果做最小验证，判断本次 run 是否真的产生了预期产物。"""
    execution_by_name = {execution.tool_name: execution for execution in tool_executions}
    checks: list[VerificationCheck] = []

    expected_tools = ["search_text", "apply_patch", "read_file", "run_command", "git_diff"]
    called_tools = [execution.tool_name for execution in tool_executions]
    checks.append(
        VerificationCheck(
            name="工具调用顺序",
            passed=called_tools == expected_tools,
            detail=f"实际调用顺序：{', '.join(called_tools) if called_tools else '无'}",
        )
    )

    apply_patch_result = execution_by_name.get("apply_patch")
    apply_patch_ok = bool(apply_patch_result and apply_patch_result.tool_output.get("ok"))
    checks.append(
        VerificationCheck(
            name="说明文件写入",
            passed=apply_patch_ok,
            detail="已成功写入 agent_notes.md。" if apply_patch_ok else "未成功写入 agent_notes.md。",
        )
    )

    read_file_result = execution_by_name.get("read_file")
    read_file_content = read_file_result.tool_output.get("content", "") if read_file_result else ""
    read_file_ok = bool(read_file_result and read_file_result.tool_output.get("ok") and "# Agent Notes" in read_file_content)
    checks.append(
        VerificationCheck(
            name="说明文件可读",
            passed=read_file_ok,
            detail="已读回 agent_notes.md，且标题符合预期。"
            if read_file_ok
            else "未能正确读回 agent_notes.md。",
        )
    )

    command_result = execution_by_name.get("run_command")
    command_stdout = command_result.tool_output.get("stdout", "").strip() if command_result else ""
    command_ok = bool(command_result and command_result.tool_output.get("ok") and command_stdout == "# Agent Notes")
    checks.append(
        VerificationCheck(
            name="命令检查通过",
            passed=command_ok,
            detail=f"命令输出首行：{command_stdout or '空'}",
        )
    )

    diff_result = execution_by_name.get("git_diff")
    diff_count = int(diff_result.tool_output.get("changed_file_count", 0)) if diff_result else 0
    diff_ok = diff_count > 0
    checks.append(
        VerificationCheck(
            name="变更已被记录",
            passed=diff_ok,
            detail=f"diff 记录到的变更文件数：{diff_count}",
        )
    )

    passed = all(check.passed for check in checks)
    summary = "验证通过：本次 run 已写入说明文件，并保留了可检查的工具结果。" if passed else "验证失败：至少有一项关键检查未通过。"
    return VerificationResult(
        passed=passed,
        summary=summary,
        checks=checks,
        details={
            "verification_mode": "stub_tool_chain",
            "tool_call_count": len(tool_executions),
            "called_tools": called_tools,
            "changed_file_count": diff_count,
        },
    )


def _build_task_command_verification(settings: RunSettings, tool_executions: list[ToolExecution]) -> VerificationResult:
    """按任务定义的 verify_commands 执行真实验证，并把结果收敛成统一结构。"""
    checks: list[VerificationCheck] = []
    command_results: list[VerifyCommandResult] = []

    for index, command in enumerate(settings.verify_commands, start=1):
        completed = subprocess.run(
            command,
            cwd=settings.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        command_result = VerifyCommandResult(
            command=list(command),
            cwd=settings.repo_root,
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        command_results.append(command_result)
        checks.append(
            VerificationCheck(
                name=f"verify_command_{index}",
                passed=command_result.ok,
                detail=(
                    f"命令 `{' '.join(command_result.command)}` 返回码为 {command_result.returncode}。"
                    f" stdout 首行：{_first_line(command_result.stdout)}"
                ),
            )
        )

    rule_checks = _build_verify_rule_checks(
        repo_root=settings.repo_root,
        verify_rules=settings.verify_rules,
        command_results=command_results,
        tool_executions=tool_executions,
    )
    checks.extend(rule_checks)

    passed = all(check.passed for check in checks)
    summary = (
        "验证通过：任务定义的 verify_commands 与 verify_rules 全部满足。"
        if passed
        else "验证失败：至少有一条任务级 verify command 或 verify rule 未满足。"
    )
    return VerificationResult(
        passed=passed,
        summary=summary,
        checks=checks,
        details={
            "verification_mode": "task_verify_commands",
            "verify_command_count": len(command_results),
            "verify_rule_count": len(settings.verify_rules),
            "verify_command_results": [item.to_dict() for item in command_results],
        },
    )


def _build_verify_rule_checks(
    repo_root: str,
    verify_rules: list[dict[str, Any]],
    command_results: list[VerifyCommandResult],
    tool_executions: list[ToolExecution],
) -> list[VerificationCheck]:
    """把 verify_rules 解释成结构化检查项，补足“退出码成功但任务没完成”的场景。"""
    checks: list[VerificationCheck] = []
    for index, rule in enumerate(verify_rules, start=1):
        rule_type = str(rule.get("type", "")).strip()
        rule_name = str(rule.get("name", "")).strip() or f"verify_rule_{index}"

        if rule_type == "command_stdout_contains":
            checks.append(_check_command_output_contains(rule_name, rule, command_results, stream_name="stdout"))
            continue
        if rule_type == "command_stdout_not_contains":
            checks.append(_check_command_output_not_contains(rule_name, rule, command_results, stream_name="stdout"))
            continue
        if rule_type == "command_stdout_matches_regex":
            checks.append(_check_command_output_matches_regex(rule_name, rule, command_results, stream_name="stdout"))
            continue
        if rule_type == "command_stderr_contains":
            checks.append(_check_command_output_contains(rule_name, rule, command_results, stream_name="stderr"))
            continue
        if rule_type == "command_stderr_not_contains":
            checks.append(_check_command_output_not_contains(rule_name, rule, command_results, stream_name="stderr"))
            continue
        if rule_type == "command_stderr_matches_regex":
            checks.append(_check_command_output_matches_regex(rule_name, rule, command_results, stream_name="stderr"))
            continue
        if rule_type == "command_returncode":
            checks.append(_check_command_returncode(rule_name, rule, command_results))
            continue
        if rule_type == "file_exists":
            checks.append(_check_file_exists(rule_name, rule, repo_root))
            continue
        if rule_type == "file_not_exists":
            checks.append(_check_file_not_exists(rule_name, rule, repo_root))
            continue
        if rule_type == "file_contains":
            checks.append(_check_file_contains(rule_name, rule, repo_root))
            continue
        if rule_type == "file_not_contains":
            checks.append(_check_file_not_contains(rule_name, rule, repo_root))
            continue
        if rule_type == "file_line_count_at_least":
            checks.append(_check_file_line_count(rule_name, rule, repo_root, mode="at_least"))
            continue
        if rule_type == "file_line_count_at_most":
            checks.append(_check_file_line_count(rule_name, rule, repo_root, mode="at_most"))
            continue
        if rule_type == "json_file_value_equals":
            checks.append(_check_json_file_value_equals(rule_name, rule, repo_root))
            continue
        if rule_type == "json_path_exists":
            checks.append(_check_json_path_exists(rule_name, rule, repo_root))
            continue
        if rule_type == "json_array_length_equals":
            checks.append(_check_json_array_length(rule_name, rule, repo_root, mode="equals"))
            continue
        if rule_type == "json_array_length_at_least":
            checks.append(_check_json_array_length(rule_name, rule, repo_root, mode="at_least"))
            continue
        if rule_type == "json_array_length_at_most":
            checks.append(_check_json_array_length(rule_name, rule, repo_root, mode="at_most"))
            continue
        if rule_type == "json_object_key_exists":
            checks.append(_check_json_object_key_exists(rule_name, rule, repo_root))
            continue
        if rule_type == "diff_changed_file_count_at_least":
            checks.append(_check_diff_changed_file_count(rule_name, rule, tool_executions, mode="at_least"))
            continue
        if rule_type == "diff_changed_file_count_at_most":
            checks.append(_check_diff_changed_file_count(rule_name, rule, tool_executions, mode="at_most"))
            continue
        if rule_type == "diff_contains_file":
            checks.append(_check_diff_contains_file(rule_name, rule, tool_executions))
            continue
        if rule_type == "diff_contains_text":
            checks.append(_check_diff_text(rule_name, rule, tool_executions, should_contain=True))
            continue
        if rule_type == "diff_not_contains_text":
            checks.append(_check_diff_text(rule_name, rule, tool_executions, should_contain=False))
            continue
        if rule_type == "files_matching_count_at_least":
            checks.append(_check_files_matching_count(rule_name, rule, repo_root, mode="at_least"))
            continue
        if rule_type == "files_matching_count_at_most":
            checks.append(_check_files_matching_count(rule_name, rule, repo_root, mode="at_most"))
            continue

        checks.append(
            VerificationCheck(
                name=rule_name,
                passed=False,
                detail=f"不支持的 verify rule 类型：{rule_type or '空'}",
            )
        )
    return checks


def _check_command_output_contains(
    rule_name: str,
    rule: dict[str, Any],
    command_results: list[VerifyCommandResult],
    stream_name: str,
) -> VerificationCheck:
    """检查某条 verify 命令输出里是否包含指定文本。"""
    command_result = _find_command_result(rule=rule, command_results=command_results)
    expected_text = str(rule.get(f"{stream_name}_contains") or rule.get("contains") or "").strip()
    if command_result is None:
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail="指定的 verify command 不存在，无法检查输出。",
        )
    output = command_result.stdout if stream_name == "stdout" else command_result.stderr
    passed = bool(expected_text) and expected_text in output
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=(
            f"检查 verify command #{_get_command_index(rule)} 的 {stream_name} 是否包含 `{expected_text or '空'}`。"
            f" 实际首行：{_first_line(output)}"
        ),
    )


def _check_command_output_not_contains(
    rule_name: str,
    rule: dict[str, Any],
    command_results: list[VerifyCommandResult],
    stream_name: str,
) -> VerificationCheck:
    """检查某条 verify 命令输出里是否不包含指定文本。"""
    command_result = _find_command_result(rule=rule, command_results=command_results)
    expected_text = str(rule.get(f"{stream_name}_not_contains") or rule.get("not_contains") or "").strip()
    if command_result is None:
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail="指定的 verify command 不存在，无法检查输出。",
        )
    output = command_result.stdout if stream_name == "stdout" else command_result.stderr
    passed = bool(expected_text) and expected_text not in output
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=(
            f"检查 verify command #{_get_command_index(rule)} 的 {stream_name} 是否不包含 `{expected_text or '空'}`。"
            f" 实际首行：{_first_line(output)}"
        ),
    )


def _check_command_output_matches_regex(
    rule_name: str,
    rule: dict[str, Any],
    command_results: list[VerifyCommandResult],
    stream_name: str,
) -> VerificationCheck:
    """Check a verify command output stream with Python re.search."""
    command_result = _find_command_result(rule=rule, command_results=command_results)
    regex_pattern = str(rule.get("regex") or "").strip()
    if command_result is None:
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail="指定的 verify command 不存在，无法检查 regex 输出。",
        )
    if not regex_pattern:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing regex.")

    output = command_result.stdout if stream_name == "stdout" else command_result.stderr
    try:
        passed = re.search(regex_pattern, output) is not None
    except re.error as error:
        return VerificationCheck(name=rule_name, passed=False, detail=f"invalid regex `{regex_pattern}`: {error}.")
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=(
            f"check verify command #{_get_command_index(rule)} {stream_name} matches regex `{regex_pattern}`. "
            f"first line: {_first_line(output)}"
        ),
    )


def _check_command_returncode(
    rule_name: str,
    rule: dict[str, Any],
    command_results: list[VerifyCommandResult],
) -> VerificationCheck:
    """检查某条 verify 命令是否返回指定退出码。"""
    command_result = _find_command_result(rule=rule, command_results=command_results)
    expected_returncode = rule.get("expected_returncode")
    if command_result is None:
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail="指定的 verify command 不存在，无法检查返回码。",
        )
    passed = isinstance(expected_returncode, int) and command_result.returncode == expected_returncode
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=(
            f"检查 verify command #{_get_command_index(rule)} 返回码是否为 "
            f"{expected_returncode if isinstance(expected_returncode, int) else '未配置'}。"
            f" 实际返回码：{command_result.returncode}"
        ),
    )


def _check_file_exists(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """检查 sandbox 内是否存在指定文件。"""
    file_path = _resolve_rule_file_path(repo_root=repo_root, rule=rule)
    if file_path is None:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule 缺少合法的 path。")
    passed = file_path.exists()
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"检查文件 `{file_path}` 是否存在。",
    )


def _check_file_not_exists(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """检查 sandbox 内指定文件是否已不存在。"""
    file_path = _resolve_rule_file_path(repo_root=repo_root, rule=rule)
    if file_path is None:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule 缺少合法的 path。")
    passed = not file_path.exists()
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"检查文件 `{file_path}` 是否不存在。",
    )


def _check_file_contains(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """检查指定文件内容里是否包含目标文本。"""
    return _check_file_text(rule_name=rule_name, rule=rule, repo_root=repo_root, should_contain=True)


def _check_file_not_contains(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """检查指定文件内容里是否不再包含目标文本。"""
    return _check_file_text(rule_name=rule_name, rule=rule, repo_root=repo_root, should_contain=False)


def _check_file_line_count(
    rule_name: str,
    rule: dict[str, Any],
    repo_root: str,
    mode: str,
) -> VerificationCheck:
    """检查文件行数是否满足最小值或最大值约束。"""
    file_path = _resolve_rule_file_path(repo_root=repo_root, rule=rule)
    if file_path is None:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule 缺少合法的 path。")
    if not file_path.exists():
        return VerificationCheck(name=rule_name, passed=False, detail=f"目标文件不存在：`{file_path}`。")

    line_count = len(file_path.read_text(encoding="utf-8").splitlines())
    if mode == "at_least":
        threshold = rule.get("min_line_count")
        passed = isinstance(threshold, int) and line_count >= threshold
        compare_text = f"不少于 {threshold if isinstance(threshold, int) else '未配置'}"
    else:
        threshold = rule.get("max_line_count")
        passed = isinstance(threshold, int) and line_count <= threshold
        compare_text = f"不多于 {threshold if isinstance(threshold, int) else '未配置'}"

    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"检查文件 `{file_path}` 的行数是否{compare_text}。实际行数：{line_count}",
    )


def _check_file_text(rule_name: str, rule: dict[str, Any], repo_root: str, should_contain: bool) -> VerificationCheck:
    """按包含或不包含两种模式检查文件内容。"""
    file_path = _resolve_rule_file_path(repo_root=repo_root, rule=rule)
    expected_text = str(rule.get("contains") or rule.get("not_contains") or "").strip()
    if file_path is None:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule 缺少合法的 path。")
    if not file_path.exists():
        return VerificationCheck(name=rule_name, passed=False, detail=f"目标文件不存在：`{file_path}`。")

    content = file_path.read_text(encoding="utf-8")
    text_found = bool(expected_text) and expected_text in content
    passed = text_found if should_contain else not text_found
    action_text = "包含" if should_contain else "不包含"
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"检查文件 `{file_path}` 是否{action_text} `{expected_text or '空'}`。",
    )


def _check_json_file_value_equals(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """Check a JSON file value selected by simple dot-path syntax."""
    json_payload = _load_json_rule_payload(rule_name=rule_name, rule=rule, repo_root=repo_root)
    if isinstance(json_payload, VerificationCheck):
        return json_payload
    json_path, data = json_payload
    found, actual_value, error_detail = _resolve_simple_json_path(data, json_path)
    expected_value = rule.get("expected_value")
    passed = found and actual_value == expected_value
    detail = (
        f"JSON path `{json_path}` actual value is {actual_value!r}; expected {expected_value!r}."
        if found
        else f"JSON path `{json_path}` was not found: {error_detail}."
    )
    return VerificationCheck(name=rule_name, passed=passed, detail=detail)


def _check_json_path_exists(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """Check that a simple JSON path resolves successfully."""
    json_payload = _load_json_rule_payload(rule_name=rule_name, rule=rule, repo_root=repo_root)
    if isinstance(json_payload, VerificationCheck):
        return json_payload
    json_path, data = json_payload
    found, actual_value, error_detail = _resolve_simple_json_path(data, json_path)
    return VerificationCheck(
        name=rule_name,
        passed=found,
        detail=(
            f"JSON path `{json_path}` exists with value type `{type(actual_value).__name__}`."
            if found
            else f"JSON path `{json_path}` was not found: {error_detail}."
        ),
    )


def _check_json_array_length(
    rule_name: str,
    rule: dict[str, Any],
    repo_root: str,
    mode: str,
) -> VerificationCheck:
    """Check array length at a simple JSON path."""
    json_payload = _load_json_rule_payload(rule_name=rule_name, rule=rule, repo_root=repo_root)
    if isinstance(json_payload, VerificationCheck):
        return json_payload
    json_path, data = json_payload
    found, actual_value, error_detail = _resolve_simple_json_path(data, json_path)
    if not found:
        return VerificationCheck(name=rule_name, passed=False, detail=f"JSON path `{json_path}` was not found: {error_detail}.")
    if not isinstance(actual_value, list):
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail=f"JSON path `{json_path}` is `{type(actual_value).__name__}`, not array.",
        )

    actual_length = len(actual_value)
    if mode == "equals":
        expected_length = _normalize_int(rule.get("expected_length"))
        passed = expected_length is not None and actual_length == expected_length
        detail = f"JSON array `{json_path}` length is {actual_length}; expected {expected_length if expected_length is not None else 'unset'}."
    elif mode == "at_least":
        min_length = _normalize_int(rule.get("min_length"))
        passed = min_length is not None and actual_length >= min_length
        detail = f"JSON array `{json_path}` length is {actual_length}; expected at least {min_length if min_length is not None else 'unset'}."
    else:
        max_length = _normalize_int(rule.get("max_length"))
        passed = max_length is not None and actual_length <= max_length
        detail = f"JSON array `{json_path}` length is {actual_length}; expected at most {max_length if max_length is not None else 'unset'}."
    return VerificationCheck(name=rule_name, passed=passed, detail=detail)


def _check_json_object_key_exists(rule_name: str, rule: dict[str, Any], repo_root: str) -> VerificationCheck:
    """Check that an object at a simple JSON path contains a key."""
    json_payload = _load_json_rule_payload(rule_name=rule_name, rule=rule, repo_root=repo_root)
    if isinstance(json_payload, VerificationCheck):
        return json_payload
    json_path, data = json_payload
    key = str(rule.get("key") or "").strip()
    if not key:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing key.")
    found, actual_value, error_detail = _resolve_simple_json_path(data, json_path)
    if not found:
        return VerificationCheck(name=rule_name, passed=False, detail=f"JSON path `{json_path}` was not found: {error_detail}.")
    if not isinstance(actual_value, dict):
        return VerificationCheck(
            name=rule_name,
            passed=False,
            detail=f"JSON path `{json_path}` is `{type(actual_value).__name__}`, not object.",
        )
    passed = key in actual_value
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"JSON object `{json_path}` keys are {sorted(actual_value.keys())}; expected key `{key}`.",
    )


def _load_json_rule_payload(
    rule_name: str,
    rule: dict[str, Any],
    repo_root: str,
) -> tuple[str, Any] | VerificationCheck:
    """Load JSON file and return the requested simple path with parsed data."""
    file_path = _resolve_rule_file_path(repo_root=repo_root, rule=rule)
    json_path = str(rule.get("json_path", "")).strip()
    if file_path is None:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing a valid path.")
    if not json_path:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing json_path.")
    if not file_path.exists():
        return VerificationCheck(name=rule_name, passed=False, detail=f"JSON file does not exist: `{file_path}`.")

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return VerificationCheck(name=rule_name, passed=False, detail=f"JSON parse failed: {error}.")
    return json_path, data


def _resolve_simple_json_path(data: Any, json_path: str) -> tuple[bool, Any, str]:
    """Resolve paths like `a.b.0.name` against dict/list JSON data."""
    current = data
    for segment in json_path.split("."):
        if not segment:
            return False, None, "empty path segment"
        if isinstance(current, dict):
            if segment not in current:
                return False, None, f"missing object key `{segment}`"
            current = current[segment]
            continue
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return False, None, f"array index `{segment}` is not an integer"
            if index < 0 or index >= len(current):
                return False, None, f"array index `{index}` is out of range"
            current = current[index]
            continue
        return False, None, f"value type `{type(current).__name__}` cannot resolve `{segment}`"
    return True, current, ""


def _check_diff_changed_file_count(
    rule_name: str,
    rule: dict[str, Any],
    tool_executions: list[ToolExecution],
    mode: str,
) -> VerificationCheck:
    """Check changed file count from an existing git_diff tool result."""
    diff_output = _find_latest_git_diff_output(tool_executions)
    if diff_output is None:
        return VerificationCheck(name=rule_name, passed=False, detail="No git_diff tool result is available.")

    changed_file_count = _normalize_int(diff_output.get("changed_file_count"))
    if changed_file_count is None:
        changed_file_count = len(_extract_diff_paths(diff_output))

    if mode == "at_least":
        threshold = _normalize_int(rule.get("min_count"))
        passed = threshold is not None and changed_file_count >= threshold
        detail = f"diff changed_file_count is {changed_file_count}; expected at least {threshold if threshold is not None else 'unset'}."
    else:
        threshold = _normalize_int(rule.get("max_count"))
        passed = threshold is not None and changed_file_count <= threshold
        detail = f"diff changed_file_count is {changed_file_count}; expected at most {threshold if threshold is not None else 'unset'}."
    return VerificationCheck(name=rule_name, passed=passed, detail=detail)


def _check_diff_contains_file(
    rule_name: str,
    rule: dict[str, Any],
    tool_executions: list[ToolExecution],
) -> VerificationCheck:
    """Check that an existing git_diff result contains a target path."""
    diff_output = _find_latest_git_diff_output(tool_executions)
    if diff_output is None:
        return VerificationCheck(name=rule_name, passed=False, detail="No git_diff tool result is available.")

    expected_path = _normalize_relative_path_text(rule.get("path"))
    changed_paths = _extract_diff_paths(diff_output)
    passed = bool(expected_path) and expected_path in changed_paths
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"diff changed files are {changed_paths}; expected `{expected_path or 'unset'}`.",
    )


def _check_diff_text(
    rule_name: str,
    rule: dict[str, Any],
    tool_executions: list[ToolExecution],
    should_contain: bool,
) -> VerificationCheck:
    """Check text inside the latest git_diff output without regenerating diff."""
    diff_output = _find_latest_git_diff_output(tool_executions)
    if diff_output is None:
        return VerificationCheck(name=rule_name, passed=False, detail="No git_diff tool result is available.")

    expected_text = str((rule.get("contains") if should_contain else rule.get("not_contains")) or "").strip()
    diff_text = _extract_diff_text(diff_output)
    if not expected_text:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing diff text assertion.")
    text_found = expected_text in diff_text
    passed = text_found if should_contain else not text_found
    action_text = "contains" if should_contain else "does not contain"
    return VerificationCheck(
        name=rule_name,
        passed=passed,
        detail=f"diff text {action_text} `{expected_text}`; diff length={len(diff_text)}.",
    )


def _check_files_matching_count(
    rule_name: str,
    rule: dict[str, Any],
    repo_root: str,
    mode: str,
) -> VerificationCheck:
    """Count UTF-8 text files under repo root matching glob and content constraints."""
    glob_pattern = str(rule.get("glob", "")).strip().replace("\\", "/")
    if not glob_pattern:
        return VerificationCheck(name=rule_name, passed=False, detail="verify rule missing glob.")
    if Path(glob_pattern).is_absolute() or ".." in Path(glob_pattern).parts:
        return VerificationCheck(name=rule_name, passed=False, detail="glob must stay inside repo root.")

    base_path = Path(repo_root).resolve()
    contains_text = _normalize_optional_rule_text(rule.get("contains"))
    not_contains_text = _normalize_optional_rule_text(rule.get("not_contains"))
    inspected_count = 0
    skipped_count = 0
    matched_paths: list[str] = []

    for candidate_path in sorted(base_path.glob(glob_pattern)):
        resolved_path = candidate_path.resolve()
        try:
            resolved_path.relative_to(base_path)
        except ValueError:
            skipped_count += 1
            continue
        if not resolved_path.is_file():
            continue
        try:
            content = resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped_count += 1
            continue
        inspected_count += 1
        contains_ok = contains_text is None or contains_text in content
        not_contains_ok = not_contains_text is None or not_contains_text not in content
        if contains_ok and not_contains_ok:
            matched_paths.append(resolved_path.relative_to(base_path).as_posix())

    matched_count = len(matched_paths)
    if mode == "at_least":
        threshold = _normalize_int(rule.get("min_count"))
        passed = threshold is not None and matched_count >= threshold
        compare_text = f"at least {threshold if threshold is not None else 'unset'}"
    else:
        threshold = _normalize_int(rule.get("max_count"))
        passed = threshold is not None and matched_count <= threshold
        compare_text = f"at most {threshold if threshold is not None else 'unset'}"

    detail = (
        f"glob `{glob_pattern}` matched={matched_count}, inspected={inspected_count}, "
        f"skipped={skipped_count}; expected {compare_text}. matched_paths={matched_paths}"
    )
    return VerificationCheck(name=rule_name, passed=passed, detail=detail)


def _find_latest_git_diff_output(tool_executions: list[ToolExecution]) -> dict[str, Any] | None:
    """Return the latest git_diff output from already executed tools."""
    for execution in reversed(tool_executions):
        if execution.tool_name == "git_diff" and isinstance(execution.tool_output, dict):
            return execution.tool_output
    return None


def _extract_diff_paths(diff_output: dict[str, Any]) -> list[str]:
    """Extract normalized changed paths from git_diff output."""
    raw_diffs = diff_output.get("diffs", [])
    if not isinstance(raw_diffs, list):
        return []
    paths: list[str] = []
    for item in raw_diffs:
        if not isinstance(item, dict):
            continue
        path_text = _normalize_relative_path_text(item.get("path"))
        if path_text:
            paths.append(path_text)
    return paths


def _extract_diff_text(diff_output: dict[str, Any]) -> str:
    """Extract concatenated diff text from git_diff output."""
    raw_diffs = diff_output.get("diffs", [])
    if not isinstance(raw_diffs, list):
        return ""
    diff_texts: list[str] = []
    for item in raw_diffs:
        if isinstance(item, dict) and isinstance(item.get("diff"), str):
            diff_texts.append(item["diff"])
    return "\n".join(diff_texts)


def _normalize_relative_path_text(raw_value: Any) -> str:
    """Normalize paths to repo-relative slash form."""
    return str(raw_value or "").strip().replace("\\", "/").strip("/")


def _normalize_optional_rule_text(raw_value: Any) -> str | None:
    """Normalize optional text constraints without treating missing values as assertions."""
    if raw_value is None:
        return None
    text = str(raw_value)
    return text if text else None


def _normalize_int(raw_value: Any) -> int | None:
    """Normalize integer thresholds used by verify rules."""
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


def _find_command_result(rule: dict[str, Any], command_results: list[VerifyCommandResult]) -> VerifyCommandResult | None:
    """按 rule 中的 command_index 找到对应 verify 命令结果。"""
    command_index = _get_command_index(rule)
    if command_index < 1 or command_index > len(command_results):
        return None
    return command_results[command_index - 1]


def _get_command_index(rule: dict[str, Any]) -> int:
    """把 rule 里的 command_index 收敛成稳定的一基索引。"""
    raw_index = rule.get("command_index")
    if isinstance(raw_index, int):
        return raw_index
    if isinstance(raw_index, str) and raw_index.strip():
        try:
            return int(raw_index.strip())
        except ValueError:
            return 0
    return 0


def _resolve_rule_file_path(repo_root: str, rule: dict[str, Any]) -> Path | None:
    """把 verify rule 的相对路径解析到 sandbox 内，并阻止越界。"""
    raw_path = str(rule.get("path", "")).strip()
    if not raw_path:
        return None
    base_path = Path(repo_root).resolve()
    candidate_path = (base_path / raw_path).resolve()
    try:
        candidate_path.relative_to(base_path)
    except ValueError:
        return None
    return candidate_path


def _first_line(text: str) -> str:
    """只取命令输出首行，避免验证明细在 summary 里铺太长。"""
    stripped = text.strip()
    if not stripped:
        return "空"
    return stripped.splitlines()[0]
