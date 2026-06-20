from __future__ import annotations

import argparse

from task_board.service import (
    build_export_output,
    build_list_output,
    build_owner_digest_output,
    build_priority_digest_output,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(description="Small task board CLI for bugfix experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List tasks.")
    list_parser.add_argument("--owner", default="")
    list_parser.add_argument("--status", choices=["todo", "done"], default="")
    list_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived tasks in the output.",
    )
    export_parser = subparsers.add_parser("export", help="Export tasks.")
    export_parser.add_argument("--owner", default="")
    export_parser.add_argument("--status", choices=["todo", "done"], default="")
    export_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived tasks in the export output.",
    )
    owners_parser = subparsers.add_parser("owners", help="Summarize matching tasks by owner.")
    owners_parser.add_argument("--owner", default="")
    owners_parser.add_argument("--status", choices=["todo", "done"], default="")
    owners_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived tasks in the owner digest.",
    )
    priorities_parser = subparsers.add_parser("priorities", help="Summarize matching tasks by priority.")
    priorities_parser.add_argument("--owner", default="")
    priorities_parser.add_argument("--status", choices=["todo", "done"], default="")
    priorities_parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived tasks in the priority digest.",
    )

    return parser


def main() -> int:
    """Execute the CLI command."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        text = build_list_output(
            owner=args.owner,
            status=args.status,
            include_archived=args.include_archived,
        )
        print(text)
        return 0

    if args.command == "export":
        text = build_export_output(
            owner=args.owner,
            status=args.status,
            include_archived=args.include_archived,
        )
        print(text)
        return 0

    if args.command == "owners":
        text = build_owner_digest_output(
            owner=args.owner,
            status=args.status,
            include_archived=args.include_archived,
        )
        print(text)
        return 0

    if args.command == "priorities":
        text = build_priority_digest_output(
            owner=args.owner,
            status=args.status,
            include_archived=args.include_archived,
        )
        print(text)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
