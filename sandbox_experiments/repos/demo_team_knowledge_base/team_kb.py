from __future__ import annotations

import argparse
from pathlib import Path

from team_kb.filters import filter_articles
from team_kb.render import render_article, render_article_list
from team_kb.storage import load_articles


DATA_PATH = Path(__file__).parent / "data" / "articles.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse team knowledge base articles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List knowledge base articles.")
    list_parser.add_argument("--owner", default="", help="Only show articles owned by this person.")
    list_parser.add_argument("--status", default="", help="Only show articles with this status.")

    show_parser = subparsers.add_parser("show", help="Show one article.")
    show_parser.add_argument("article_id", type=int)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    articles = load_articles(DATA_PATH)

    if args.command == "list":
        filtered = filter_articles(articles, owner=args.owner, status=args.status)
        print(render_article_list(filtered))
        return 0

    if args.command == "show":
        for article in articles:
            if article.get("id") == args.article_id:
                print(render_article(article))
                return 0
        print(f"Article {args.article_id} not found")
        return 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
