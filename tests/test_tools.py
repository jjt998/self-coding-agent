from __future__ import annotations

from pathlib import Path

from tools import CoreToolRunner


def test_run_command_accepts_shell_string_command(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "hello.txt").write_text("hello\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.run_command("type hello.txt")

    assert result.tool_name == "run_command"
    assert result.tool_input == {"command": "type hello.txt"}
    assert result.tool_output["ok"] is True
    assert result.tool_output["returncode"] == 0
    assert "hello" in result.tool_output["stdout"]


def test_run_command_returns_failed_tool_result_when_process_cannot_start(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.run_command(["definitely_missing_command_for_self_coding_agent"])

    assert result.tool_name == "run_command"
    assert result.tool_output["ok"] is False
    assert result.tool_output["returncode"] is None
    assert result.tool_output["error_type"] == "FileNotFoundError"


def test_apply_patch_returns_failed_tool_result_for_invalid_input(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.apply_patch(path="README.md", old_text=None, new_text=None)  # type: ignore[arg-type]

    assert result.tool_name == "apply_patch"
    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "invalid_tool_input"
