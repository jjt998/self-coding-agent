from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TASKS_FILE = Path(__file__).resolve().parents[1] / "tasks.json"


def load_tasks() -> list[dict[str, Any]]:
    """Load tasks from the JSON file."""
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
