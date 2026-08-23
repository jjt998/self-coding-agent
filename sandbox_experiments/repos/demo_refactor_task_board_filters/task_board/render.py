from __future__ import annotations

from typing import Any


def render_task_list(tasks: list[dict[str, Any]]) -> str:
    """Render a stable plain-text task list."""
    if not tasks:
        return "No tasks matched."

    lines: list[str] = []
    for task in tasks:
        status = "done" if task.get("done", False) else "todo"
        archived_suffix = " (archived)" if task.get("archived", False) else ""
        lines.append(
            f"{task['id']}. [{status}] {task['title']} | owner={task['owner']} | "
            f"priority={task['priority']}{archived_suffix}"
        )
    return "\n".join(lines)
