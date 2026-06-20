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
    """保存任务列表，保持 JSON 便于 verify_rules 检查。"""
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_tasks() -> int:
    """输出当前所有任务。"""
    tasks = load_tasks()
    if not tasks:
        print("No tasks.")
        return 0

    for task in tasks:
        status = "done" if task.get("done") else "todo"
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


def complete_task(task_id: int) -> int:
    """标记指定 id 的任务为已完成。"""
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["done"] = True
            save_tasks(tasks)
            print(f"Completed task #{task_id}")
            return 0
    print(f"Task #{task_id} not found.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Small TODO CLI for agent experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all tasks.")

    add_parser = subparsers.add_parser("add", help="Add a task.")
    add_parser.add_argument("title")
    add_parser.add_argument("--description", default="")

    complete_parser = subparsers.add_parser("complete", help="Mark a task as completed.")
    complete_parser.add_argument("id", type=int, help="Task ID")

    return parser


def main() -> int:
    """执行 CLI 命令。"""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        return list_tasks()
    if args.command == "add":
        return add_task(title=args.title, description=args.description)
    if args.command == "complete":
        return complete_task(task_id=args.id)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
