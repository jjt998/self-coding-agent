from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import build_settings
from tools import ToolExecution
from verify import build_phase_4_verification


def test_verify_uses_task_verify_commands_when_defined(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Demo\n", encoding="utf-8")

    settings = build_settings(
        task="运行真实 verify 命令",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "print('verify ok')"]],
    )
    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is True
    assert result.summary == "验证通过：任务定义的 verify_commands 与 verify_rules 全部满足。"
    assert result.details["verification_mode"] == "task_verify_commands"
    assert result.details["verify_command_count"] == 1
    assert result.details["verify_rule_count"] == 0
    assert result.details["verify_command_results"][0]["ok"] is True
    assert result.checks[0].name == "verify_command_1"


def test_verify_supports_structured_verify_rules_for_command_and_file_checks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.txt").write_text("status=ok\n", encoding="utf-8")
    (repo_root / "lines.txt").write_text("a\nb\nc\n", encoding="utf-8")

    settings = build_settings(
        task="运行结构化验证",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "import sys; print('verify ok'); sys.stderr.write('all clean\\n')"]],
        verify_rules=[
            {"type": "command_stdout_contains", "name": "命令输出包含成功标记", "command_index": 1, "contains": "verify ok"},
            {"type": "command_stdout_not_contains", "name": "命令输出不含失败标记", "command_index": 1, "not_contains": "FAILED"},
            {"type": "command_stderr_not_contains", "name": "错误输出不含 traceback", "command_index": 1, "not_contains": "Traceback"},
            {"type": "file_exists", "name": "结果文件存在", "path": "result.txt"},
            {"type": "file_contains", "name": "结果文件包含状态", "path": "result.txt", "contains": "status=ok"},
            {"type": "file_not_contains", "name": "结果文件不含失败标记", "path": "result.txt", "not_contains": "status=fail"},
            {"type": "file_not_exists", "name": "临时文件已删除", "path": "temp.txt"},
            {"type": "file_line_count_at_least", "name": "行数至少三行", "path": "lines.txt", "min_line_count": 3},
            {"type": "file_line_count_at_most", "name": "行数不超过四行", "path": "lines.txt", "max_line_count": 4},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is True
    assert result.details["verify_rule_count"] == 9
    assert [check.name for check in result.checks[1:]] == [
        "命令输出包含成功标记",
        "命令输出不含失败标记",
        "错误输出不含 traceback",
        "结果文件存在",
        "结果文件包含状态",
        "结果文件不含失败标记",
        "临时文件已删除",
        "行数至少三行",
        "行数不超过四行",
    ]


def test_verify_fails_when_structured_rule_is_not_satisfied(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.txt").write_text("status=fail\n", encoding="utf-8")

    settings = build_settings(
        task="验证失败收口",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "print('verify ok')"]],
        verify_rules=[
            {"type": "file_not_contains", "name": "结果文件不应包含失败标记", "path": "result.txt", "not_contains": "status=fail"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert result.summary == "验证失败：至少有一条任务级 verify command 或 verify rule 未满足。"
    assert result.checks[1].name == "结果文件不应包含失败标记"
    assert result.checks[1].passed is False


def test_verify_supports_negative_command_output_and_line_count_failures(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "lines.txt").write_text("a\nb\nc\n", encoding="utf-8")

    settings = build_settings(
        task="验证额外规则失败",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "import sys; print('FAILED'); sys.stderr.write('Traceback here\\n')"]],
        verify_rules=[
            {"type": "command_stdout_not_contains", "name": "标准输出不应包含 FAILED", "command_index": 1, "not_contains": "FAILED"},
            {"type": "command_stderr_not_contains", "name": "标准错误不应包含 Traceback", "command_index": 1, "not_contains": "Traceback"},
            {"type": "file_line_count_at_most", "name": "行数不超过两行", "path": "lines.txt", "max_line_count": 2},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.passed for check in result.checks[1:]] == [False, False, False]


def test_verify_falls_back_to_stub_tool_chain_when_no_verify_commands() -> None:
    settings = build_settings(
        task="回退到演示验证",
        task_type="general",
        repo_root=".",
        output_root="runs",
        config_name="default",
    )
    tool_executions = [
        ToolExecution("search_text", {"query": "Agent Notes", "limit": 5}, {"match_count": 0, "matches": []}),
        ToolExecution(
            "apply_patch",
            {"path": "agent_notes.md", "old_text": None, "new_text": "# Agent Notes\n"},
            {"ok": True, "action": "create_or_replace", "bytes_written": 14},
        ),
        ToolExecution("read_file", {"path": "agent_notes.md"}, {"ok": True, "content": "# Agent Notes\n", "line_count": 1}),
        ToolExecution(
            "run_command",
            {"command": ["python", "-c", "print('# Agent Notes')"]},
            {"ok": True, "returncode": 0, "stdout": "# Agent Notes\n", "stderr": ""},
        ),
        ToolExecution("git_diff", {"paths": ["agent_notes.md"]}, {"changed_file_count": 1, "diffs": [{"path": "agent_notes.md", "diff": "demo"}]}),
    ]

    result = build_phase_4_verification(settings=settings, tool_executions=tool_executions)

    assert result.passed is True
    assert result.details["verification_mode"] == "stub_tool_chain"
    assert result.checks[0].name == "工具调用顺序"
