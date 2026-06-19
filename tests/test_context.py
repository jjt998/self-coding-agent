from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from context import ContextBuilder


def test_context_snapshot_includes_python_structure_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "todo_app.py").write_text(
        "\n".join(
            [
                "class TodoStore:",
                "    pass",
                "",
                "def load_tasks():",
                "    return []",
                "",
                "def complete_task(task_id):",
                "    return task_id",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = ContextBuilder(repo_root=str(repo_root)).build_context_snapshot(
        task="修改 todo_app.py complete_task",
        task_type="feature",
        current_state="analyze",
        completed_states=[],
        step_count=1,
    )

    selected_file = snapshot.to_dict()["repo_context"]["selected_files"][0]
    structure_summary = selected_file["structure_summary"]
    assert selected_file["path"] == "todo_app.py"
    assert structure_summary[0]["kind"] == "class"
    assert structure_summary[0]["name"] == "TodoStore"
    assert {"line_number": 4, "kind": "def", "name": "load_tasks", "indent": 0, "line": "def load_tasks():"} in structure_summary
    assert any(item["name"] == "complete_task" and item["line_number"] == 7 for item in structure_summary)


def test_context_snapshot_includes_text_structure_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\nSetup:\nInstall dependencies.\n\n## Usage\nRun the CLI.\n",
        encoding="utf-8",
    )

    snapshot = ContextBuilder(repo_root=str(repo_root)).build_context_snapshot(
        task="理解 README 使用说明",
        task_type="code_understanding",
        current_state="analyze",
        completed_states=[],
        step_count=1,
    )

    selected_file = snapshot.to_dict()["repo_context"]["selected_files"][0]
    structure_summary = selected_file["structure_summary"]
    kinds = [item["kind"] for item in structure_summary]
    assert selected_file["path"] == "README.md"
    assert "heading" in kinds
    assert "section" in kinds
    assert any(item["line_number"] == 6 and item["kind"] == "heading" for item in structure_summary)
