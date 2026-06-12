from __future__ import annotations

import argparse
from pathlib import Path

from .config import build_settings, load_named_config
from .runner import execute_initial_run


def build_parser() -> argparse.ArgumentParser:
    # 这个 CLI 目前只是 Phase 1 的最小入口，先把 run 初始化流程跑通，再逐步接入真实 loop。
    parser = argparse.ArgumentParser(
        prog="self-coding-agent",
        description="运行 self-coding-agent 的 Phase 1 脚手架初始化流程。",
    )
    parser.add_argument("--task", required=True, help="本次 run 的任务描述。")
    parser.add_argument("--task-type", default="ad_hoc", help="任务类型标签。")
    parser.add_argument("--repo-root", default=".", help="目标仓库根目录。")
    parser.add_argument("--output-root", default="runs", help="run 产物输出目录。")
    parser.add_argument("--config-name", default="default", help="configs 目录下使用的配置名。")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # 先把命令行参数整理成结构化 settings，后面扩展字段时可以少改调用链。
    settings = build_settings(
        task=args.task,
        task_type=args.task_type,
        repo_root=args.repo_root,
        output_root=args.output_root,
        config_name=args.config_name,
    )
    config_dir = Path("configs")
    config_data = load_named_config(config_dir=config_dir, config_name=args.config_name)
    run_dir = execute_initial_run(settings=settings, config_data=config_data)

    # 这里先返回最关键的产物位置，方便手工检查当前 run 的输出。
    print(f"已初始化 run 目录：{run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
