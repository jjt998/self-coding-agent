from __future__ import annotations

from typing import Any


def filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    owner: str,
    status: str,
    include_archived: bool,
) -> list[dict[str, Any]]:
    """Filter tasks for the list command."""
    normalized_owner = owner.strip().lower()
    normalized_status = status.strip().lower()
    desired_done = None
    if normalized_status == "todo":
        desired_done = False
    elif normalized_status == "done":
        desired_done = True

    filtered: list[dict[str, Any]] = []
    for task in tasks:
        if not include_archived and task.get("archived", False):
            continue

        matches_owner = True
        if normalized_owner:
            matches_owner = str(task.get("owner", "")).strip().lower() == normalized_owner

        matches_status = True
        if desired_done is not None:
            matches_status = bool(task.get("done", False)) == desired_done

        if matches_owner or matches_status:
            filtered.append(task)

    return filtered
