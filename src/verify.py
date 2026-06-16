from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
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
        return _build_task_command_verification(settings=settings)
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


def _build_task_command_verification(settings: RunSettings) -> VerificationResult:
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
        if rule_type == "command_stderr_contains":
            checks.append(_check_command_output_contains(rule_name, rule, command_results, stream_name="stderr"))
            continue
        if rule_type == "command_stderr_not_contains":
            checks.append(_check_command_output_not_contains(rule_name, rule, command_results, stream_name="stderr"))
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
