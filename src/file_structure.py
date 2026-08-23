from __future__ import annotations

from pathlib import Path
import re
from typing import Any


def truncate_structure_line(value: str, limit: int = 240) -> str:
    """截断结构摘要里的单行文本，避免摘要本身过长。"""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def build_structure_summary(
    *,
    path: str,
    content: str,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """按文件类型生成轻量结构摘要，优先暴露可定位的行号。"""
    lines = content.splitlines()
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return _build_python_structure_summary(lines=lines, max_items=max_items)
    return _build_generic_structure_summary(lines=lines, max_items=max_items)


def _build_python_structure_summary(
    *,
    lines: list[str],
    max_items: int | None,
) -> list[dict[str, Any]]:
    """提取 Python `class`/`def` 名称和起始行号。"""
    items: list[dict[str, Any]] = []
    pattern = re.compile(r"^(?P<indent>\s*)(?P<kind>class|def)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
    for line_number, line in enumerate(lines, start=1):
        match = pattern.match(line)
        if not match:
            continue
        items.append(
            {
                "line_number": line_number,
                "kind": match.group("kind"),
                "name": match.group("name"),
                "indent": len(match.group("indent")),
                "line": line.strip(),
            }
        )
        if max_items is not None and len(items) >= max_items:
            break
    return items


def _build_generic_structure_summary(
    *,
    lines: list[str],
    max_items: int | None,
) -> list[dict[str, Any]]:
    """为普通文本提取 heading、分节行和非空行索引。"""
    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        kind = "non_empty"
        if stripped.startswith("#"):
            kind = "heading"
        elif stripped.endswith(":") and len(stripped) <= 120:
            kind = "section"
        items.append(
            {
                "line_number": line_number,
                "kind": kind,
                "line": truncate_structure_line(stripped),
            }
        )
        if max_items is not None and len(items) >= max_items:
            break
    return items
