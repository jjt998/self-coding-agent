from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def filter_articles(
    articles: Iterable[dict[str, Any]],
    *,
    owner: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    filtered = list(articles)
    if owner:
        filtered = [article for article in filtered if article.get("owner") == owner]
    if status:
        filtered = [article for article in filtered if article.get("status") == status]
    return sorted(filtered, key=lambda article: int(article.get("id", 0)))
