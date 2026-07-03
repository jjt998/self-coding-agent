from __future__ import annotations

from typing import Any


def render_article_list(articles: list[dict[str, Any]]) -> str:
    if not articles:
        return "No articles found."
    lines = []
    for article in articles:
        lines.append(
            f"{article['id']}. {article['title']} | owner={article['owner']} | status={article['status']}"
        )
    return "\n".join(lines)


def render_article(article: dict[str, Any]) -> str:
    tags = ", ".join(article.get("tags", []))
    return "\n".join(
        [
            f"# {article['title']}",
            f"Owner: {article['owner']}",
            f"Status: {article['status']}",
            f"Tags: {tags}",
            "",
            str(article.get("body", "")),
        ]
    )
