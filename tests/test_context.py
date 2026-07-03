from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from context import ContextBuilder


def test_initial_guide_includes_python_structure_summary(tmp_path: Path) -> None:
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

    guide = ContextBuilder(repo_root=str(repo_root)).build_initial_guide(
        task="修改 todo_app.py complete_task",
        task_type="feature",
    )

    selected_file = guide.to_dict()["repo_guide"]["selected_files"][0]
    structure_summary = selected_file["structure_summary"]
    assert selected_file["path"] == "todo_app.py"
    assert structure_summary[0]["kind"] == "class"
    assert structure_summary[0]["name"] == "TodoStore"
    assert {"line_number": 4, "kind": "def", "name": "load_tasks", "indent": 0, "line": "def load_tasks():"} in structure_summary
    assert any(item["name"] == "complete_task" and item["line_number"] == 7 for item in structure_summary)


def test_initial_guide_includes_text_structure_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\nSetup:\nInstall dependencies.\n\n## Usage\nRun the CLI.\n",
        encoding="utf-8",
    )

    guide = ContextBuilder(repo_root=str(repo_root)).build_initial_guide(
        task="理解 README 使用说明",
        task_type="code_understanding",
    )

    selected_file = guide.to_dict()["repo_guide"]["selected_files"][0]
    structure_summary = selected_file["structure_summary"]
    kinds = [item["kind"] for item in structure_summary]
    assert selected_file["path"] == "README.md"
    assert "heading" in kinds
    assert "section" in kinds
    assert any(item["line_number"] == 6 and item["kind"] == "heading" for item in structure_summary)


def test_context_snapshot_injects_last_rational_into_working_memory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    runtime_state = SimpleNamespace(
        task="继续修复 README",
        task_type="bug_fix",
        current_iteration=2,
        initial_guide=None,
        working_memory={
            "confirmed_facts": ["README 已被读取"],
            "invalidated_beliefs": [],
            "completed_actions": ["已读取 README.md"],
            "next_risks": ["还没验证最终 diff"],
        },
        model_decision=SimpleNamespace(rationale="上一轮判断应先确认 README 当前内容。  "),
        observe_content={},
        file_context_cache={},
        latest_diff_snapshot=None,
        latest_command_result=None,
    )

    snapshot = ContextBuilder(repo_root=str(repo_root)).build_context_snapshot(runtime_state=runtime_state)
    working_memory = snapshot.to_dict()["working_memory"]

    assert working_memory["confirmed_facts"] == ["README 已被读取"]
    assert working_memory["last_rational"] == "上一轮判断应先确认 README 当前内容。"

