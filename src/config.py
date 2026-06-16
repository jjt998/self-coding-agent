from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    """返回统一格式的 UTC ISO 时间字符串。"""
    # 统一使用 UTC 时间，后面做 trace 对齐和跨机器排查会更省事。
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class RunSettings:
    """承载单次 run 所需的基础配置。"""

    task: str
    task_type: str = "general"
    repo_root: str = "."
    source_repo_root: str = "."
    output_root: str = "runs"
    config_name: str = "default"
    workspace_mode: str = "in_place"
    sandbox_dir: str = ""
    sandbox_retention: str = "delete_on_success"
    setup_commands: list[list[str]] = field(default_factory=list)
    verify_commands: list[list[str]] = field(default_factory=list)
    verify_rules: list[dict[str, Any]] = field(default_factory=list)
    # run_id 里同时带时间和短随机串，既方便人眼排查，也能降低同秒运行时的重名概率。
    run_id: str = field(default_factory=lambda: f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """把运行配置转换成可写入快照的字典。"""
        return asdict(self)


def build_settings(
    task: str,
    task_type: str,
    repo_root: str,
    output_root: str,
    config_name: str,
    source_repo_root: str | None = None,
    workspace_mode: str = "in_place",
    sandbox_retention: str = "delete_on_success",
    setup_commands: list[list[str]] | None = None,
    verify_commands: list[list[str]] | None = None,
    verify_rules: list[dict[str, Any]] | None = None,
) -> RunSettings:
    """根据 CLI 输入构建标准化后的运行配置。"""
    # 这里先把 repo_root 和 source_repo_root 都规范成绝对路径，后面看 trace 时就能同时知道
    # “原始仓库在哪”和“这次真正执行时所在目录在哪”。
    normalized_repo_root = str(Path(repo_root).resolve())
    normalized_source_repo_root = str(Path(source_repo_root or repo_root).resolve())
    return RunSettings(
        task=task,
        task_type=task_type,
        repo_root=normalized_repo_root,
        source_repo_root=normalized_source_repo_root,
        output_root=str(Path(output_root)),
        config_name=config_name,
        workspace_mode=workspace_mode,
        sandbox_retention=sandbox_retention,
        setup_commands=list(setup_commands or []),
        verify_commands=list(verify_commands or []),
        verify_rules=list(verify_rules or []),
    )


def load_named_config(config_dir: Path, config_name: str) -> dict[str, Any]:
    """从 configs 目录加载指定名称的 JSON 配置。"""
    config_path = config_dir / f"{config_name}.json"
    # Phase 1 先允许“没配配置也能跑”，这样可以优先把控制面打通。
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))
