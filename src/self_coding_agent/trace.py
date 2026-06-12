from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    # trace 事件和 run 配置都使用同一套时间格式，后面做排序和比对更直接。
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class TraceEvent:
    event_type: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceWriter:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.trace_path = run_dir / "trace.jsonl"
        self.report_path = run_dir / "report.md"
        self.config_snapshot_path = run_dir / "config_snapshot.json"

    def initialize(self, config_snapshot: dict[str, Any]) -> None:
        # 初始化时把 run 目录的一组基础产物一次性落齐，后面每次运行都能保持同样的目录形态。
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.config_snapshot_path.write_text(
            json.dumps(config_snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # 先创建空 trace 文件，后续即使还没有真实 agent loop，也能保证 run 产物完整。
        self.trace_path.write_text("", encoding="utf-8")
        # report 先写一个占位版本，保证每次 run 从第一步开始就有可读输出。
        self.report_path.write_text(self._build_report_stub(config_snapshot), encoding="utf-8")

    def write_event(self, event: TraceEvent) -> None:
        # JSONL 方便后面按事件流追加，也方便用脚本逐行分析。
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")

    def write_report(self, content: str) -> None:
        self.report_path.write_text(content, encoding="utf-8")

    def _build_report_stub(self, config_snapshot: dict[str, Any]) -> str:
        task = config_snapshot.get("task", "")
        task_type = config_snapshot.get("task_type", "")
        run_id = config_snapshot.get("run_id", "")
        # 这里先保留最小报告骨架，等 Phase 4 再替换成正式报告结构。
        return (
            f"# 运行报告\n\n"
            f"- Run ID：`{run_id}`\n"
            f"- 任务类型：`{task_type}`\n"
            f"- 任务内容：{task}\n\n"
            f"## 当前状态\n\n"
            f"`initialized`\n\n"
            f"## 说明\n\n"
            f"- 这是在 Phase 1 脚手架阶段生成的占位报告。\n"
        )
