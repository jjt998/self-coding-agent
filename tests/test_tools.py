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


def test_read_file_returns_full_content_for_small_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file("app.py")

    assert result.tool_output["ok"] is True
    assert result.tool_output["content_mode"] == "full"
    assert result.tool_output["content_truncated"] is False
    assert result.tool_output["read_coverage"] == "1-2"
    assert result.tool_output["content"] == "def main():\n    return 1\n"


def test_read_file_returns_structure_summary_for_large_python_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    lines = ["class Service:", "    pass", ""]
    lines.extend(f"def function_{index}():  # {'x' * 80}" for index in range(1, 210))
    (repo_root / "large.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file("large.py")

    assert result.tool_output["ok"] is True
    assert result.tool_output["content_mode"] == "structure_summary"
    assert result.tool_output["content_truncated"] is True
    assert "content" not in result.tool_output
    assert "content_excerpt" not in result.tool_output
    assert result.tool_output["line_count"] > 200
    assert "read_coverage" not in result.tool_output
    assert result.tool_output["structure_summary"][0]["kind"] == "class"
    assert result.tool_output["structure_summary"][0]["name"] == "Service"
    assert any(item["kind"] == "def" for item in result.tool_output["structure_summary"])


def test_read_file_returns_full_content_for_medium_file_below_tool_threshold(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    lines = ["def main():"]
    lines.extend(f"    value_{index} = '{'x' * 40}'" for index in range(1, 45))
    (repo_root / "medium.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file("medium.py")

    assert result.tool_output["ok"] is True
    assert result.tool_output["content_mode"] == "full"
    assert result.tool_output["content_truncated"] is False
    assert result.tool_output["read_coverage"] == "1-45"
    assert result.tool_output["content"].startswith("def main():")


def test_read_file_returns_structure_summary_for_large_text_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    lines = ["# Title", "", "Section:", "detail"]
    lines.extend(f"item {index} {'x' * 80}" for index in range(210))
    (repo_root / "notes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file("notes.md")

    assert result.tool_output["content_mode"] == "structure_summary"
    kinds = [item["kind"] for item in result.tool_output["structure_summary"]]
    assert "heading" in kinds
    assert "section" in kinds
    assert "non_empty" in kinds


def test_read_file_range_reads_requested_closed_range(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file_range("app.py", 2, 3)

    assert result.tool_name == "read_file_range"
    assert result.tool_output["ok"] is True
    assert result.tool_output["content_mode"] == "range"
    assert result.tool_output["content_excerpt"] == "two\nthree"
    assert result.tool_output["read_coverage"] == "2-3"
    assert result.tool_output["line_count"] == 4


def test_read_file_range_allows_at_most_forty_lines(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("\n".join(f"line {index}" for index in range(1, 45)) + "\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    allowed = runner.read_file_range("app.py", 1, 40)
    rejected = runner.read_file_range("app.py", 1, 41)

    assert allowed.tool_output["ok"] is True
    assert allowed.tool_output["read_coverage"] == "1-40"
    assert rejected.tool_output["ok"] is False
    assert rejected.tool_output["error"] == "range_too_large"
    assert "最多一次读取 40 行" in rejected.tool_output["detail"]


def test_read_file_range_returns_failed_tool_result_for_invalid_range(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("one\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file_range("app.py", 3, 2)

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "invalid_line_range"


def test_read_file_range_rejects_path_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file_range(str(outside), 1, 1)

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "path_outside_repo"


def test_read_file_range_rejects_non_utf8_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "binary.txt").write_bytes(b"\xff\xfe\x00")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.read_file_range("binary.txt", 1, 1)

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "non_utf8_text_file"


def test_replace_lines_replaces_closed_range(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = repo_root / "app.py"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.replace_lines("app.py", 2, 3, "TWO\nTHREE")

    assert result.tool_name == "replace_lines"
    assert result.tool_output["ok"] is True
    assert result.tool_output["action"] == "replace_lines"
    assert result.tool_output["line_count_before"] == 4
    assert result.tool_output["line_count_after"] == 4
    assert target.read_text(encoding="utf-8") == "one\nTWO\nTHREE\nfour\n"


def test_replace_lines_rejects_invalid_range(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("one\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.replace_lines("app.py", 2, 2, "two")

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "line_range_out_of_bounds"


def test_replace_lines_rejects_path_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.replace_lines(str(outside), 1, 1, "updated")

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "path_outside_repo"


def test_replace_lines_rejects_non_utf8_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "binary.txt").write_bytes(b"\xff\xfe\x00")
    runner = CoreToolRunner(repo_root=str(repo_root))

    result = runner.replace_lines("binary.txt", 1, 1, "updated")

    assert result.tool_output["ok"] is False
    assert result.tool_output["error"] == "non_utf8_text_file"
