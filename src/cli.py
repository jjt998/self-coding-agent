from __future__ import annotations

import argparse
from pathlib import Path

from config import build_settings, load_named_config
from eval_runner import load_strategy_specs, run_eval_batch, run_strategy_comparison
from runner import execute_initial_run


def build_parser() -> argparse.ArgumentParser:
    """构建 self-coding-agent 的命令行参数解析器。"""
    # CLI 继续保持最小入口，但现在会跑过一条 Phase 2 的 stub 状态机链路。
    parser = argparse.ArgumentParser(
        prog="self-coding-agent",
        description="运行 self-coding-agent 的最小状态机实验流程。",
    )
    parser.add_argument("--task", help="本次 run 的任务描述。")
    parser.add_argument("--task-type", default="general", help="任务类型标签。")
    parser.add_argument("--repo-root", default=".", help="目标仓库根目录。")
    parser.add_argument("--output-root", default="runs", help="run 产物输出目录。")
    parser.add_argument("--config-name", default="default", help="configs 目录下使用的配置名。")
    parser.add_argument("--eval-task-file", help="批量评测任务文件路径。")
    parser.add_argument(
        "--compare-strategies",
        help="按逗号分隔的 config 名列表；提供后会对同一批任务执行策略对比。",
    )
    return parser


def main() -> int:
    """解析命令行参数并启动一次最小 agent run。"""
    parser = build_parser()
    args = parser.parse_args()
    config_dir = Path("configs")

    if args.eval_task_file:
        if args.compare_strategies:
            strategy_specs = load_strategy_specs(args.compare_strategies.split(","))
            comparison_dir = run_strategy_comparison(
                task_file=Path(args.eval_task_file),
                repo_root=args.repo_root,
                output_root=args.output_root,
                strategy_specs=strategy_specs,
            )
            print(f"已完成最小 strategy comparison，产物目录：{comparison_dir}")
            return 0

        eval_dir = run_eval_batch(
            task_file=Path(args.eval_task_file),
            repo_root=args.repo_root,
            output_root=args.output_root,
            config_name=args.config_name,
        )
        print(f"已完成最小 eval 运行，产物目录：{eval_dir}")
        return 0

    if not args.task:
        parser.error("未提供 --task 时，必须提供 --eval-task-file。")

    # 先把命令行参数整理成结构化 settings，后面扩展字段时可以少改调用链。
    settings = build_settings(
        task=args.task,
        task_type=args.task_type,
        repo_root=args.repo_root,
        output_root=args.output_root,
        config_name=args.config_name,
    )
    config_data = load_named_config(config_dir=config_dir, config_name=args.config_name)
    run_dir = execute_initial_run(settings=settings, config_data=config_data)

    # 这里继续返回最关键的产物位置，方便手工检查本次 run 的 trace 和报告。
    print(f"已完成最小 loop 运行，产物目录：{run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
