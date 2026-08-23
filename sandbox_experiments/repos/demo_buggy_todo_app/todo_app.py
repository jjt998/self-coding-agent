from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TASKS_FILE = Path(__file__).with_name("tasks.json")


def load_tasks() -> list[dict[str, Any]]:
    """读取本地任务列表。"""
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    """保存任务列表，保持 JSON 便于验证。"""
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_tasks() -> int:
    """输出当前所有任务。"""
    tasks = load_tasks()
    if not tasks:
        print("No tasks.")
        return 0

    for task in tasks:
        status = "todo" if task.get("done") else "done"
        print(f"{task['id']}. [{status}] {task['title']} - {task.get('description', '')}")
    return 0


def add_task(title: str, description: str) -> int:
    """新增一条任务。"""
    tasks = load_tasks()
    next_id = max((int(task.get("id", 0)) for task in tasks), default=0) + 1
    tasks.append(
        {
            "id": next_id,
            "title": title,
            "description": description,
            "done": False,
        }
    )
    save_tasks(tasks)
    print(f"Added task #{next_id}: {title}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Small TODO CLI for bugfix experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all tasks.")

    add_parser = subparsers.add_parser("add", help="Add a task.")
    add_parser.add_argument("title")
    add_parser.add_argument("--description", default="")

    return parser


def main() -> int:
    """执行 CLI 命令。"""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        return list_tasks()
    if args.command == "add":
        return add_task(title=args.title, description=args.description)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
