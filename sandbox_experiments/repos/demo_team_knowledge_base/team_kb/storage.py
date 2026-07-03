from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_articles(path: Path) -> list[dict[str, Any]]:
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, list):
        raise ValueError("articles data must be a list")
    return [item for item in raw_data if isinstance(item, dict)]


def save_articles(path: Path, articles: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(articles, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
