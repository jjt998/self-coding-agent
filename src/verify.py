from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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


def build_phase_4_verification(tool_executions: list[ToolExecution]) -> VerificationResult:
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
            "tool_call_count": len(tool_executions),
            "called_tools": called_tools,
            "changed_file_count": diff_count,
        },
    )
