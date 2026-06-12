from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    # 统一使用 UTC 时间，后面做 trace 对齐和跨机器排查会更省事。
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class RunSettings:
    task: str
    task_type: str = "ad_hoc"
    repo_root: str = "."
    output_root: str = "runs"
    config_name: str = "default"
    # run_id 里同时带时间和短随机串，既方便人眼排查，也能降低同秒运行时的重名概率。
    run_id: str = field(default_factory=lambda: f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}")
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_settings(
    task: str,
    task_type: str,
    repo_root: str,
    output_root: str,
    config_name: str,
) -> RunSettings:
    # 这里先把 repo_root 规范成绝对路径，后面无论从哪里启动 CLI，trace 里看到的仓库路径都会稳定。
    return RunSettings(
        task=task,
        task_type=task_type,
        repo_root=str(Path(repo_root).resolve()),
        output_root=str(Path(output_root)),
        config_name=config_name,
    )


def load_named_config(config_dir: Path, config_name: str) -> dict[str, Any]:
    config_path = config_dir / f"{config_name}.json"
    # Phase 1 先允许“没配配置也能跑”，这样可以优先把控制面打通。
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))
