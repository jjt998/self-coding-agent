from __future__ import annotations

from task_board.storage import load_tasks
from task_board.query_engine import render_export_list, render_owner_digest, render_task_list


def build_list_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the list command output."""
    tasks = load_tasks()
    return render_task_list(
        tasks,
        owner=owner,
        status=status,
        include_archived=include_archived,
    )


def build_export_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the export command output."""
    tasks = load_tasks()
    return render_export_list(
        tasks,
        owner=owner,
        status=status,
        include_archived=include_archived,
    )


def build_owner_digest_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the owner digest output."""
    tasks = load_tasks()
    return render_owner_digest(
        tasks,
        owner=owner,
        status=status,
        include_archived=include_archived,
    )
