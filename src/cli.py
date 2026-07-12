from __future__ import annotations

import argparse
from pathlib import Path
import sys


def _prefer_local_src_modules() -> None:
    """优先从当前 src 目录加载本项目模块，避免 trace 等文件名撞上标准库。"""
    src_dir = str(Path(__file__).resolve().parent)
    if sys.path[0] != src_dir:
        sys.path.insert(0, src_dir)


_prefer_local_src_modules()

from config import build_settings, load_named_config
from env_loader import load_dotenv
from eval_runner import load_strategy_specs, run_eval_batch, run_strategy_comparison
from experiment_runner import run_experiment_suite
from runner import execute_initial_run, execute_resume_run


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器，统一管理单次运行、批量评测和策略对比入口。"""
    # 这里把三类入口都集中在同一个 parser 里，后面扩展运行模式时不容易散到多处。
    parser = argparse.ArgumentParser(
        prog="self-coding-agent",
        description="运行 self-coding-agent 的最小实验流程。",
    )
    parser.add_argument("--task", help="本次 run 的任务描述。")
    parser.add_argument("--task-type", default="general", help="任务类型标签。")
    parser.add_argument("--repo-root", default=".", help="目标仓库根目录。")
    parser.add_argument("--output-root", default="runs", help="运行产物输出目录。")
    parser.add_argument("--config-name", default="default", help="configs 目录下使用的配置名。")
    parser.add_argument(
        "--interaction-mode",
        choices=["tasks", "headless_hitl", "interactive"],
        help="本次 run 的交互模式：tasks 自动运行，headless_hitl 通过 JSON 文件处理人工审批，interactive 暂未实现。",
    )
    parser.add_argument("--resume-run", help="恢复一个正在等待人工输入的 run 目录。")
    parser.add_argument("--human-response", help="headless_hitl 恢复时使用的人工响应 JSON 文件。")
    parser.add_argument("--eval-task-file", help="批量评测任务文件路径。")
    parser.add_argument("--experiment-suite-file", help="实验套件文件路径，用于一键执行一组策略对比。")
    parser.add_argument(
        "--compare-strategies",
        help="按逗号分隔的 config 名列表；提供后会对同一批任务执行策略对比。",
    )
    return parser


def main() -> int:
    """解析命令行参数，并按用户选择进入单次 run、eval 或策略对比流程。"""
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    config_dir = Path("configs")

    if args.interaction_mode == "interactive":
        parser.error("interactive 模式暂未实现，请使用 tasks 或 headless_hitl。")

    if args.resume_run:
        if not args.human_response:
            parser.error("使用 --resume-run 时必须同时提供 --human-response。")
        config_data = load_named_config(config_dir=config_dir, config_name=args.config_name)
        run_dir = execute_resume_run(
            run_dir=Path(args.resume_run),
            human_response_path=Path(args.human_response),
            config_data=config_data,
        )
        print(f"已恢复 headless_hitl run，产物目录：{run_dir}")
        return 0

    if args.experiment_suite_file:
        # 实验套件入口用于执行一组固定实验，避免每次都手工拼三四条 comparison 命令。
        suite_dir = run_experiment_suite(
            suite_file=Path(args.experiment_suite_file),
            repo_root=args.repo_root,
            output_root=args.output_root,
        )
        print(f"已完成实验套件运行，产物目录：{suite_dir}")
        return 0

    if args.eval_task_file:
        if args.compare_strategies:
            # 先把用户输入的策略名收敛成结构化配置，再交给 comparison runner 统一执行。
            strategy_specs = load_strategy_specs(args.compare_strategies.split(","))
            comparison_dir = run_strategy_comparison(
                task_file=Path(args.eval_task_file),
                repo_root=args.repo_root,
                output_root=args.output_root,
                strategy_specs=strategy_specs,
            )
            print(f"已完成最小 strategy comparison，产物目录：{comparison_dir}")
            return 0

        # 没有比较策略时，就走普通的 eval batch 入口。
        eval_dir = run_eval_batch(
            task_file=Path(args.eval_task_file),
            repo_root=args.repo_root,
            output_root=args.output_root,
            config_name=args.config_name,
            interaction_mode_override=args.interaction_mode or "",
        )
        print(f"已完成最小 eval 运行，产物目录：{eval_dir}")
        return 0

    if not args.task:
        parser.error("未提供 --task 时，必须提供 --eval-task-file 或 --experiment-suite-file。")

    # 先把 CLI 输入整理成统一 settings，避免单次 run 入口和后续调用层耦合得过深。
    config_data = load_named_config(config_dir=config_dir, config_name=args.config_name)
    interaction_mode = _resolve_interaction_mode(cli_value=args.interaction_mode, config_data=config_data)
    settings = build_settings(
        task=args.task,
        task_type=args.task_type,
        repo_root=args.repo_root,
        output_root=args.output_root,
        config_name=args.config_name,
        interaction_mode=interaction_mode,
    )
    run_dir = execute_initial_run(settings=settings, config_data=config_data)

    # 这里只回显最关键的产物目录，方便人直接去看 trace 和 report。
    print(f"已完成最小 loop 运行，产物目录：{run_dir}")
    return 0


def _resolve_interaction_mode(cli_value: str | None, config_data: dict) -> str:
    """按 CLI > config > tasks 的优先级决定交互模式。"""
    if cli_value:
        return cli_value
    runtime_config = config_data.get("runtime", {})
    if isinstance(runtime_config, dict):
        configured = str(runtime_config.get("interaction_mode", "")).strip()
        if configured:
            return configured
    return "tasks"


if __name__ == "__main__":
    raise SystemExit(main())
