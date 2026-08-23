from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TASKS_FILE = Path(__file__).with_name("tasks.json")


def load_tasks() -> list[dict[str, Any]]:
    """读取本地任务列表。"""
    if TASKS_FILE.exists():
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    """保存任务列表到本地文件。"""
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def list_tasks() -> int:
    """列出所有任务。"""
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
    print(f"✅ 已新增任务 #{next_id}: {title}")
    return next_id


def complete_task(task_id: int) -> None:
    """标记指定 ID 的任务为已完成。"""
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["done"] = True
            save_tasks(tasks)
            print(f"Completed task #{task_id}: {task['title']}")
            return
    print(f"Error: task #{task_id} not found", file=__import__("sys").stderr)
    __import__("sys").exit(1)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    subparsers.add_parser("list", help="列出所有任务")

    # add
    add_parser = subparsers.add_parser("add", help="新增任务")
    add_parser.add_argument("title", type=str, help="任务标题")
    add_parser.add_argument("--description", "-d", type=str, default="", help="任务描述")

    # complete
    complete_parser = subparsers.add_parser("complete", help="标记任务为已完成")
    complete_parser.add_argument("id", type=int, help="任务 ID")

    args = parser.parse_args()

    if args.command == "list":
        list_tasks()
    elif args.command == "add":
        add_task(args.title, args.description)
    elif args.command == "complete":
        complete_task(args.id)


if __name__ == "__main__":
    main()
