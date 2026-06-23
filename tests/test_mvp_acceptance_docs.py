from __future__ import annotations

from pathlib import Path


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_readme_links_minimal_usage_and_acceptance_paths() -> None:
    readme = _read_text("README.md")

    for expected in [
        "配置模型 -> 单次 run -> 编写 eval task -> 查看 report -> 运行 eval -> 运行 comparison -> 排障",
        "docs/USAGE_GUIDE.md",
        "docs/MVP_ACCEPTANCE.md",
        ".env.example",
        "DEEPSEEK_API_KEY",
        "eval task schema",
        "report.md",
        "--compare-strategies",
    ]:
        assert expected in readme


def test_usage_guide_covers_core_user_workflows() -> None:
    guide = _read_text("docs/USAGE_GUIDE.md")

    for expected in [
        "DEEPSEEK_API_KEY",
        ".env",
        "verify_commands",
        "verify_rules",
        "report.md",
        "summary.json",
        "summary.md",
        "--compare-strategies",
        "failure_taxonomy_counts_delta",
        "runtime.max_steps = 2",
    ]:
        assert expected in guide


def test_mvp_acceptance_freezes_commands_boundaries_and_backlog() -> None:
    acceptance = _read_text("docs/MVP_ACCEPTANCE.md")

    for expected in [
        "D:\\jt\\ANACONDA\\envs_dirs\\learn-claude-code\\python.exe",
        "-m pytest -q",
        "--eval-task-file eval_tasks\\sample_batch.json",
        "--compare-strategies default,verify_failure_only_reflect",
        "summary.json",
        "summary.md",
        "task_deltas",
        "不支持 `rule_based`",
        "无 API key 会失败为 `model_error`",
        "CLI 单次运行暂不支持直接传入 `verify_commands` / `verify_rules`",
        "下一阶段 Backlog",
    ]:
        assert expected in acceptance


def test_harness_improvement_log_and_run_chain_cover_feedback_evidence() -> None:
    log_text = _read_text("docs/HARNESS_IMPROVEMENT_LOG.md")
    run_chain = _read_text("docs/RUN_CHAIN.html")

    for expected in [
        "Harness 改进文档",
        "问题现象",
        "改进动作",
        "预期改善",
        "实际反馈",
        "是否固化",
        "old_text_not_found",
        "context_snapshot.recent_facts.recent_tool_results",
    ]:
        assert expected in log_text

    for expected in [
        "content_excerpt",
        "failed_old_text_excerpt",
        "old_text_not_found_candidate",
        "候选源码片段",
        "失败的 old_text 摘要",
    ]:
        assert expected in run_chain
