from __future__ import annotations

from typing import Any

from task_board.storage import load_tasks
from task_board.query_engine import (
    render_export_list,
    render_owner_digest,
    render_priority_digest,
    render_task_list,
)


def sanitize_owner(owner: str) -> str:
    """Normalize service-layer owner input."""
    return owner.strip()


def sanitize_status(status: str) -> str:
    """Normalize service-layer status input."""
    return status.strip()


def sanitize_include_archived(include_archived: bool) -> bool:
    """Normalize archived flag."""
    return bool(include_archived)


def copy_loaded_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy tasks before passing them into render functions."""
    return [dict(task) for task in tasks]


def build_list_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the list command output."""
    loaded_tasks = load_tasks()
    tasks = copy_loaded_tasks(loaded_tasks)
    normalized_owner = sanitize_owner(owner)
    normalized_status = sanitize_status(status)
    include_archived_flag = sanitize_include_archived(include_archived)
    _service_request = {
        "owner": normalized_owner,
        "status": normalized_status,
        "include_archived": include_archived_flag,
        "task_count": len(tasks),
    }
    return render_task_list(
        tasks,
        owner=normalized_owner,
        status=normalized_status,
        include_archived=include_archived_flag,
    )


def build_export_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the export command output."""
    loaded_tasks = load_tasks()
    tasks = copy_loaded_tasks(loaded_tasks)
    normalized_owner = sanitize_owner(owner)
    normalized_status = sanitize_status(status)
    include_archived_flag = sanitize_include_archived(include_archived)
    _service_request = {
        "owner": normalized_owner,
        "status": normalized_status,
        "include_archived": include_archived_flag,
        "task_count": len(tasks),
    }
    return render_export_list(
        tasks,
        owner=normalized_owner,
        status=normalized_status,
        include_archived=include_archived_flag,
    )


def build_owner_digest_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the owner digest output."""
    loaded_tasks = load_tasks()
    tasks = copy_loaded_tasks(loaded_tasks)
    normalized_owner = sanitize_owner(owner)
    normalized_status = sanitize_status(status)
    include_archived_flag = sanitize_include_archived(include_archived)
    _service_request = {
        "owner": normalized_owner,
        "status": normalized_status,
        "include_archived": include_archived_flag,
        "task_count": len(tasks),
    }
    return render_owner_digest(
        tasks,
        owner=normalized_owner,
        status=normalized_status,
        include_archived=include_archived_flag,
    )


def build_priority_digest_output(*, owner: str, status: str, include_archived: bool) -> str:
    """Build the priority digest output."""
    loaded_tasks = load_tasks()
    tasks = copy_loaded_tasks(loaded_tasks)
    normalized_owner = sanitize_owner(owner)
    normalized_status = sanitize_status(status)
    include_archived_flag = sanitize_include_archived(include_archived)
    _service_request = {
        "owner": normalized_owner,
        "status": normalized_status,
        "include_archived": include_archived_flag,
        "task_count": len(tasks),
    }
    return render_priority_digest(
        tasks,
        owner=normalized_owner,
        status=normalized_status,
        include_archived=include_archived_flag,
    )
