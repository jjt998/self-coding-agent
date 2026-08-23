from __future__ import annotations

from typing import Any


# This file is intentionally long and slightly repetitive.
# It is used to test large-file bug fixing behavior in the coding agent.


STATUS_TODO = "todo"
STATUS_DONE = "done"
VISIBLE_PRIORITY_LABELS = {
    1: "p1",
    2: "p2",
    3: "p3",
    4: "p4",
    5: "p5",
}


def normalize_owner(owner: str) -> str:
    """Normalize owner text for comparisons."""
    return owner.strip().lower()


def normalize_status(status: str) -> str:
    """Normalize status text for comparisons."""
    return status.strip().lower()


def normalize_text(value: Any) -> str:
    """Normalize free-form values into comparable text."""
    return str(value).strip()


def normalize_bool(value: Any) -> bool:
    """Normalize common truthy values."""
    return bool(value)


def normalize_priority(value: Any) -> int:
    """Normalize task priority."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99


def get_task_id(task: dict[str, Any]) -> int:
    """Read task id with a stable fallback."""
    return int(task.get("id", 0) or 0)


def get_task_title(task: dict[str, Any]) -> str:
    """Read task title."""
    return normalize_text(task.get("title", ""))


def get_task_owner(task: dict[str, Any]) -> str:
    """Read task owner."""
    return normalize_text(task.get("owner", ""))


def get_task_owner_normalized(task: dict[str, Any]) -> str:
    """Read normalized task owner."""
    return normalize_owner(get_task_owner(task))


def get_task_priority(task: dict[str, Any]) -> int:
    """Read normalized task priority."""
    return normalize_priority(task.get("priority", 99))


def get_task_done(task: dict[str, Any]) -> bool:
    """Read done flag."""
    return normalize_bool(task.get("done", False))


def get_task_archived(task: dict[str, Any]) -> bool:
    """Read archived flag."""
    return normalize_bool(task.get("archived", False))


def get_task_status(task: dict[str, Any]) -> str:
    """Return todo/done status text for a task."""
    return STATUS_DONE if get_task_done(task) else STATUS_TODO


def get_priority_label(task: dict[str, Any]) -> str:
    """Return a human-friendly priority label."""
    return VISIBLE_PRIORITY_LABELS.get(get_task_priority(task), "p?")


def describe_task_identity(task: dict[str, Any]) -> str:
    """Build a short stable task identifier."""
    return f"{get_task_id(task)}:{get_task_title(task)}"


def describe_task_flags(task: dict[str, Any]) -> str:
    """Build a short stable task flag string."""
    return (
        f"owner={get_task_owner(task)};"
        f"status={get_task_status(task)};"
        f"archived={get_task_archived(task)};"
        f"priority={get_task_priority(task)}"
    )


def owner_filter_active(owner: str) -> bool:
    """Return whether owner filter should be applied."""
    return bool(normalize_owner(owner))


def status_filter_active(status: str) -> bool:
    """Return whether status filter should be applied."""
    return bool(normalize_status(status))


def archived_filter_active(include_archived: bool) -> bool:
    """Return whether archived filtering should be applied."""
    return not include_archived


def desired_done_value(status: str) -> bool | None:
    """Map status filter to a bool done value."""
    normalized_status = normalize_status(status)
    if normalized_status == STATUS_TODO:
        return False
    if normalized_status == STATUS_DONE:
        return True
    return None


def owner_matches(task: dict[str, Any], owner: str) -> bool:
    """Return whether task owner matches the owner filter."""
    if not owner_filter_active(owner):
        return True
    return get_task_owner_normalized(task) == normalize_owner(owner)


def status_matches(task: dict[str, Any], status: str) -> bool:
    """Return whether task status matches the status filter."""
    desired_done = desired_done_value(status)
    if desired_done is None:
        return True
    return get_task_done(task) == desired_done


def archived_matches(task: dict[str, Any], include_archived: bool) -> bool:
    """Return whether task is visible under the archived policy."""
    if not archived_filter_active(include_archived):
        return True
    return not get_task_archived(task)


def build_owner_debug_record(task: dict[str, Any], owner: str) -> dict[str, Any]:
    """Return a small debug dictionary for owner matching."""
    return {
        "task": describe_task_identity(task),
        "filter_owner": normalize_owner(owner),
        "task_owner": get_task_owner_normalized(task),
        "matched": owner_matches(task, owner),
    }


def build_status_debug_record(task: dict[str, Any], status: str) -> dict[str, Any]:
    """Return a small debug dictionary for status matching."""
    return {
        "task": describe_task_identity(task),
        "filter_status": normalize_status(status),
        "task_status": get_task_status(task),
        "matched": status_matches(task, status),
    }


def build_archived_debug_record(task: dict[str, Any], include_archived: bool) -> dict[str, Any]:
    """Return a small debug dictionary for archived matching."""
    return {
        "task": describe_task_identity(task),
        "include_archived": include_archived,
        "archived": get_task_archived(task),
        "matched": archived_matches(task, include_archived),
    }


def summarize_filters(owner: str, status: str, include_archived: bool) -> str:
    """Return a short filter summary."""
    return (
        f"owner={normalize_owner(owner) or '*'}, "
        f"status={normalize_status(status) or '*'}, "
        f"include_archived={include_archived}"
    )


def stable_sort_key(task: dict[str, Any]) -> tuple[int, int]:
    """Stable primary sort used by the list output."""
    return (get_task_priority(task), get_task_id(task))


def stable_display_prefix(task: dict[str, Any]) -> str:
    """Return the stable prefix of a rendered line."""
    return f"{get_task_id(task)}. [{get_task_status(task)}]"


def stable_display_suffix(task: dict[str, Any]) -> str:
    """Return the stable suffix of a rendered line."""
    archived_suffix = " (archived)" if get_task_archived(task) else ""
    return f"owner={get_task_owner(task)} | priority={get_task_priority(task)}{archived_suffix}"


def render_task_line(task: dict[str, Any]) -> str:
    """Render a single task line."""
    return f"{stable_display_prefix(task)} {get_task_title(task)} | {stable_display_suffix(task)}"


def render_empty_state() -> str:
    """Render the empty state for list output."""
    return "No tasks matched."


def build_renderable_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy tasks into a renderable list."""
    return [dict(task) for task in tasks]


def maybe_prepare_render_context(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build lightweight render context."""
    return {
        "count": len(tasks),
        "ids": [get_task_id(task) for task in tasks],
        "owners": sorted({get_task_owner(task) for task in tasks}),
    }


def task_matches_filters(
    task: dict[str, Any],
    *,
    owner: str,
    status: str,
    include_archived: bool,
) -> bool:
    """Return whether the task should appear in filtered output."""
    owner_ok = owner_matches(task, owner)
    status_ok = status_matches(task, status)
    archived_ok = archived_matches(task, include_archived)

    # Intentional bug:
    # Combined owner + status filtering should require all active filters.
    # This implementation incorrectly accepts tasks that match either filter.
    owner_or_status_ok = owner_ok and status_ok
    return owner_or_status_ok and archived_ok


def collect_matching_tasks(
    tasks: list[dict[str, Any]],
    *,
    owner: str,
    status: str,
    include_archived: bool,
) -> list[dict[str, Any]]:
    """Collect tasks that match the current filters."""
    matches: list[dict[str, Any]] = []
    for task in tasks:
        if task_matches_filters(
            task,
            owner=owner,
            status=status,
            include_archived=include_archived,
        ):
            matches.append(task)
    return matches


def sort_matching_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort filtered tasks using the stable display order."""
    copied = list(tasks)
    copied.sort(key=stable_sort_key)
    return copied


def build_display_lines(tasks: list[dict[str, Any]]) -> list[str]:
    """Render filtered tasks into plain-text lines."""
    lines: list[str] = []
    for task in tasks:
        lines.append(render_task_line(task))
    return lines


def maybe_build_owner_section(tasks: list[dict[str, Any]]) -> list[str]:
    """Unused helper kept to make the file more realistic."""
    owners = sorted({get_task_owner(task) for task in tasks})
    return [f"owner:{owner}" for owner in owners]


def maybe_build_priority_section(tasks: list[dict[str, Any]]) -> list[str]:
    """Unused helper kept to make the file more realistic."""
    return [f"{describe_task_identity(task)}:{get_priority_label(task)}" for task in tasks]


def maybe_build_status_section(tasks: list[dict[str, Any]]) -> list[str]:
    """Unused helper kept to make the file more realistic."""
    return [f"{describe_task_identity(task)}:{get_task_status(task)}" for task in tasks]


def maybe_build_archived_section(tasks: list[dict[str, Any]]) -> list[str]:
    """Unused helper kept to make the file more realistic."""
    return [f"{describe_task_identity(task)}:archived={get_task_archived(task)}" for task in tasks]


def maybe_build_verbose_snapshot(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Unused helper kept to make the file more realistic."""
    return {
        "owners": maybe_build_owner_section(tasks),
        "priorities": maybe_build_priority_section(tasks),
        "statuses": maybe_build_status_section(tasks),
        "archived": maybe_build_archived_section(tasks),
    }


def section_break() -> str:
    """Return a stable section separator."""
    return "-"


def format_footer(count: int) -> str:
    """Format a footer-like summary."""
    return f"{count} task(s)"


def passthrough_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pass tasks through unchanged."""
    return list(tasks)


def ensure_list(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize optional task lists."""
    return list(value or [])


def dedupe_ids(tasks: list[dict[str, Any]]) -> list[int]:
    """Return stable unique ids."""
    seen: list[int] = []
    for task in tasks:
        task_id = get_task_id(task)
        if task_id not in seen:
            seen.append(task_id)
    return seen


def build_owner_index(tasks: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Build a tiny owner index."""
    index: dict[str, list[int]] = {}
    for task in tasks:
        owner = get_task_owner_normalized(task)
        index.setdefault(owner, []).append(get_task_id(task))
    return index


def build_status_index(tasks: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Build a tiny status index."""
    index: dict[str, list[int]] = {}
    for task in tasks:
        status = get_task_status(task)
        index.setdefault(status, []).append(get_task_id(task))
    return index


def build_archived_index(tasks: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Build a tiny archived index."""
    index: dict[str, list[int]] = {"active": [], "archived": []}
    for task in tasks:
        bucket = "archived" if get_task_archived(task) else "active"
        index[bucket].append(get_task_id(task))
    return index


def build_filter_debug_snapshot(
    tasks: list[dict[str, Any]],
    *,
    owner: str,
    status: str,
    include_archived: bool,
) -> dict[str, Any]:
    """Build a debug snapshot of current filter inputs."""
    return {
        "summary": summarize_filters(owner, status, include_archived),
        "owner_index": build_owner_index(tasks),
        "status_index": build_status_index(tasks),
        "archived_index": build_archived_index(tasks),
    }


def render_task_list(
    tasks: list[dict[str, Any]],
    *,
    owner: str,
    status: str,
    include_archived: bool,
) -> str:
    """Filter, sort, and render the task list."""
    original_tasks = ensure_list(tasks)
    prepared_tasks = passthrough_tasks(original_tasks)
    _debug_snapshot = build_filter_debug_snapshot(
        prepared_tasks,
        owner=owner,
        status=status,
        include_archived=include_archived,
    )
    matching_tasks = collect_matching_tasks(
        prepared_tasks,
        owner=owner,
        status=status,
        include_archived=include_archived,
    )
    sorted_tasks = sort_matching_tasks(matching_tasks)
    display_order_tasks = finalize_visible_order(
        sorted_tasks,
        include_archived=include_archived,
    )
    renderable_tasks = build_renderable_tasks(display_order_tasks)
    _render_context = maybe_prepare_render_context(renderable_tasks)

    if not renderable_tasks:
        return render_empty_state()

    lines = build_display_lines(renderable_tasks)
    return "\n".join(lines)


def finalize_visible_order(
    tasks: list[dict[str, Any]],
    *,
    include_archived: bool,
) -> list[dict[str, Any]]:
    """Apply the final display grouping for visible tasks."""
    if not include_archived:
        return list(tasks)

    active_tasks: list[dict[str, Any]] = []
    archived_tasks: list[dict[str, Any]] = []
    for task in tasks:
        if get_task_archived(task):
            archived_tasks.append(task)
        else:
            active_tasks.append(task)

    # Intentional bug:
    # Archived matches should be appended after active matches, but this
    # implementation moves archived tasks to the front.
    return active_tasks + archived_tasks


# Padding helpers below are intentionally simple. They keep the file around
# the 400-line range so the agent has to work inside a larger source file.


def pad_summary_line_a(tasks: list[dict[str, Any]]) -> str:
    return f"count={len(tasks)}"


def pad_summary_line_b(tasks: list[dict[str, Any]]) -> str:
    return f"ids={','.join(str(task.get('id', '')) for task in tasks)}"


def pad_summary_line_c(tasks: list[dict[str, Any]]) -> str:
    return f"owners={','.join(sorted({str(task.get('owner', '')) for task in tasks}))}"


def pad_summary_line_d(tasks: list[dict[str, Any]]) -> str:
    return f"done={sum(1 for task in tasks if task.get('done', False))}"


def pad_summary_line_e(tasks: list[dict[str, Any]]) -> str:
    return f"todo={sum(1 for task in tasks if not task.get('done', False))}"


def pad_summary_line_f(tasks: list[dict[str, Any]]) -> str:
    return f"archived={sum(1 for task in tasks if task.get('archived', False))}"


def pad_summary_line_g(tasks: list[dict[str, Any]]) -> str:
    return f"active={sum(1 for task in tasks if not task.get('archived', False))}"


def pad_summary_line_h(tasks: list[dict[str, Any]]) -> str:
    return f"footer={format_footer(len(tasks))}"


def pad_snapshot(tasks: list[dict[str, Any]]) -> list[str]:
    return [
        pad_summary_line_a(tasks),
        pad_summary_line_b(tasks),
        pad_summary_line_c(tasks),
        pad_summary_line_d(tasks),
        pad_summary_line_e(tasks),
        pad_summary_line_f(tasks),
        pad_summary_line_g(tasks),
        pad_summary_line_h(tasks),
    ]
