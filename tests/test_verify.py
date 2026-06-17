from __future__ import annotations

import json
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


def test_verify_rules_can_run_without_verify_commands(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.txt").write_text("status=ok\n", encoding="utf-8")

    settings = build_settings(
        task="仅使用结构化规则验证",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[
            {"type": "file_exists", "name": "结果文件存在", "path": "result.txt"},
            {"type": "file_contains", "name": "结果文件包含成功状态", "path": "result.txt", "contains": "status=ok"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is True
    assert result.details["verification_mode"] == "task_verify_commands"
    assert result.details["verify_command_count"] == 0
    assert result.details["verify_rule_count"] == 2
    assert result.details["verify_command_results"] == []
    assert [check.name for check in result.checks] == ["结果文件存在", "结果文件包含成功状态"]


def test_verify_rules_without_verify_commands_can_fail(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.txt").write_text("status=fail\n", encoding="utf-8")

    settings = build_settings(
        task="仅使用结构化规则验证失败",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_rules=[
            {"type": "file_not_contains", "name": "结果文件不应包含失败状态", "path": "result.txt", "not_contains": "status=fail"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert result.details["verification_mode"] == "task_verify_commands"
    assert result.details["verify_command_count"] == 0
    assert result.details["verify_rule_count"] == 1
    assert result.checks[0].name == "结果文件不应包含失败状态"
    assert result.checks[0].passed is False


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


def test_verify_supports_command_output_regex_rules(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings = build_settings(
        task="verify regex",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[
            [sys.executable, "-c", "import sys; print('version=12.4.0'); sys.stderr.write('warning: E42\\n')"]
        ],
        verify_rules=[
            {"type": "command_stdout_matches_regex", "name": "stdout regex", "command_index": 1, "regex": r"version=\d+\.\d+\.\d+"},
            {"type": "command_stderr_matches_regex", "name": "stderr regex", "command_index": 1, "regex": r"E\d+"},
            {"type": "command_stdout_matches_regex", "name": "stdout mismatch", "command_index": 1, "regex": r"status=ok"},
            {"type": "command_stdout_matches_regex", "name": "invalid regex", "command_index": 1, "regex": r"["},
            {"type": "command_stdout_matches_regex", "name": "missing command", "command_index": 9, "regex": r"version"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.passed for check in result.checks[1:]] == [True, True, False, False, False]
    assert "invalid regex" in result.checks[4].detail


def test_verify_supports_json_file_value_equals(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.json").write_text(
        json.dumps({"status": "ok", "items": [{"name": "alpha", "count": 2}], "enabled": True}),
        encoding="utf-8",
    )

    settings = build_settings(
        task="verify json",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "json_file_value_equals", "name": "json status", "path": "result.json", "json_path": "status", "expected_value": "ok"},
            {"type": "json_file_value_equals", "name": "json nested number", "path": "result.json", "json_path": "items.0.count", "expected_value": 2},
            {"type": "json_file_value_equals", "name": "json bool", "path": "result.json", "json_path": "enabled", "expected_value": True},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is True
    assert [check.passed for check in result.checks[1:]] == [True, True, True]


def test_verify_json_file_value_equals_failures(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "invalid.json").write_text("{invalid", encoding="utf-8")
    (repo_root / "result.json").write_text(json.dumps({"status": "fail", "items": []}), encoding="utf-8")

    settings = build_settings(
        task="verify json failures",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "json_file_value_equals", "name": "missing file", "path": "missing.json", "json_path": "status", "expected_value": "ok"},
            {"type": "json_file_value_equals", "name": "invalid json", "path": "invalid.json", "json_path": "status", "expected_value": "ok"},
            {"type": "json_file_value_equals", "name": "missing path", "path": "result.json", "json_path": "items.0.name", "expected_value": "alpha"},
            {"type": "json_file_value_equals", "name": "value mismatch", "path": "result.json", "json_path": "status", "expected_value": "ok"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.name for check in result.checks[1:]] == ["missing file", "invalid json", "missing path", "value mismatch"]
    assert [check.passed for check in result.checks[1:]] == [False, False, False, False]


def test_verify_supports_json_path_exists_length_and_object_key_rules(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "result.json").write_text(
        json.dumps(
            {
                "items": [{"name": "alpha"}, {"name": "beta"}],
                "metadata": {"status": "ok"},
                "empty": [],
            }
        ),
        encoding="utf-8",
    )

    settings = build_settings(
        task="verify json structure",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "json_path_exists", "name": "path exists", "path": "result.json", "json_path": "items.0.name"},
            {"type": "json_array_length_equals", "name": "length equals", "path": "result.json", "json_path": "items", "expected_length": 2},
            {"type": "json_array_length_at_least", "name": "length min", "path": "result.json", "json_path": "items", "min_length": 2},
            {"type": "json_array_length_at_most", "name": "length max", "path": "result.json", "json_path": "items", "max_length": 3},
            {"type": "json_object_key_exists", "name": "object key exists", "path": "result.json", "json_path": "metadata", "key": "status"},
            {"type": "json_path_exists", "name": "path missing", "path": "result.json", "json_path": "items.3.name"},
            {"type": "json_array_length_equals", "name": "not array", "path": "result.json", "json_path": "metadata", "expected_length": 1},
            {"type": "json_object_key_exists", "name": "key missing", "path": "result.json", "json_path": "metadata", "key": "missing"},
            {"type": "json_object_key_exists", "name": "not object", "path": "result.json", "json_path": "items", "key": "status"},
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.passed for check in result.checks[1:]] == [
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_verify_supports_diff_rules_from_existing_git_diff_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings = build_settings(
        task="verify diff",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "diff_changed_file_count_at_least", "name": "diff min", "min_count": 2},
            {"type": "diff_changed_file_count_at_most", "name": "diff max", "max_count": 3},
            {"type": "diff_contains_file", "name": "diff contains", "path": "src/app.py"},
        ],
    )
    tool_executions = [
        ToolExecution(
            "git_diff",
            {"paths": None},
            {
                "changed_file_count": 2,
                "diffs": [
                    {"path": "src/app.py", "diff": "demo"},
                    {"path": "tests/test_app.py", "diff": "demo"},
                ],
            },
        )
    ]

    result = build_phase_4_verification(settings=settings, tool_executions=tool_executions)

    assert result.passed is True
    assert [check.passed for check in result.checks[1:]] == [True, True, True]


def test_verify_diff_rules_fail_without_matching_git_diff_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings = build_settings(
        task="verify diff failures",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "diff_changed_file_count_at_least", "name": "no diff", "min_count": 1},
            {"type": "diff_changed_file_count_at_most", "name": "too many", "max_count": 1},
            {"type": "diff_contains_file", "name": "missing file", "path": "src/app.py"},
        ],
    )

    result_without_diff = build_phase_4_verification(settings=settings, tool_executions=[])
    result_with_diff = build_phase_4_verification(
        settings=settings,
        tool_executions=[
            ToolExecution(
                "git_diff",
                {"paths": None},
                {"changed_file_count": 2, "diffs": [{"path": "README.md", "diff": "demo"}]},
            )
        ],
    )

    assert result_without_diff.passed is False
    assert [check.passed for check in result_without_diff.checks[1:]] == [False, False, False]
    assert result_with_diff.passed is False
    assert [check.passed for check in result_with_diff.checks[1:]] == [True, False, False]


def test_verify_supports_diff_text_rules_from_existing_git_diff_result(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    settings = build_settings(
        task="verify diff text",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {"type": "diff_contains_text", "name": "diff contains added text", "contains": "+    return data"},
            {"type": "diff_not_contains_text", "name": "diff excludes debug", "not_contains": "console.log"},
            {"type": "diff_contains_text", "name": "diff missing text", "contains": "not present"},
            {"type": "diff_not_contains_text", "name": "diff forbidden text", "not_contains": "-    pass"},
        ],
    )
    tool_executions = [
        ToolExecution(
            "git_diff",
            {"paths": None},
            {
                "changed_file_count": 1,
                "diffs": [
                    {
                        "path": "src/app.py",
                        "diff": "--- a/src/app.py\n+++ b/src/app.py\n-    pass\n+    return data",
                    }
                ],
            },
        )
    ]

    result = build_phase_4_verification(settings=settings, tool_executions=tool_executions)
    result_without_diff = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.passed for check in result.checks[1:]] == [True, True, False, False]
    assert result_without_diff.passed is False
    assert [check.passed for check in result_without_diff.checks[1:]] == [False, False, False, False]


def test_verify_supports_files_matching_count_rules(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.md").write_text("status=ok\n", encoding="utf-8")
    (docs_dir / "b.md").write_text("status=ok\n", encoding="utf-8")
    (docs_dir / "debug.md").write_text("status=ok\nDEBUG\n", encoding="utf-8")
    (docs_dir / "binary.md").write_bytes(b"\xff\xfe\x00")

    settings = build_settings(
        task="verify file aggregation",
        task_type="general",
        repo_root=str(repo_root),
        output_root=str(tmp_path / "runs"),
        config_name="default",
        verify_commands=[[sys.executable, "-c", "pass"]],
        verify_rules=[
            {
                "type": "files_matching_count_at_least",
                "name": "ok docs min",
                "glob": "docs/*.md",
                "contains": "status=ok",
                "not_contains": "DEBUG",
                "min_count": 2,
            },
            {
                "type": "files_matching_count_at_most",
                "name": "ok docs max",
                "glob": "docs/*.md",
                "contains": "status=ok",
                "not_contains": "DEBUG",
                "max_count": 1,
            },
        ],
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert [check.passed for check in result.checks[1:]] == [True, False]
    assert "skipped=1" in result.checks[1].detail


def test_verify_fails_when_no_task_verification_is_configured() -> None:
    settings = build_settings(
        task="缺少任务级验证配置",
        task_type="general",
        repo_root=".",
        output_root="runs",
        config_name="default",
    )

    result = build_phase_4_verification(settings=settings, tool_executions=[])

    assert result.passed is False
    assert result.summary == "验证失败：未配置任务级验证，无法判断任务是否完成。"
    assert result.details["verification_mode"] == "missing_task_verification"
    assert result.details["verify_command_count"] == 0
    assert result.details["verify_rule_count"] == 0
    assert result.details["verify_command_results"] == []
    assert result.checks[0].name == "task_verification_configured"
    assert result.checks[0].passed is False
