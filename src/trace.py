from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """返回 trace 事件统一使用的 UTC ISO 时间字符串。"""
    # trace 事件和 run 配置都使用同一套时间格式，后面做排序和比对更直接。
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class TraceEvent:
    """表示一条可追加到 JSONL trace 的结构化事件。"""

    event_type: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def to_json(self) -> str:
        """把当前事件序列化成单行 JSON 文本。"""
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceWriter:
    """负责初始化 run 产物并持续写入 trace 与 report。"""

    def __init__(self, run_dir: Path) -> None:
        """为指定 run 目录准备各类输出文件路径。"""
        self.run_dir = run_dir
        self.trace_path = run_dir / "trace.jsonl"
        self.report_path = run_dir / "report.md"
        self.config_snapshot_path = run_dir / "config_snapshot.json"

    def initialize(self, config_snapshot: dict[str, Any]) -> None:
        """初始化本次 run 的目录、配置快照、trace 文件和报告文件。"""
        # 初始化时把 run 目录的一组基础产物一次性落齐，后面每次运行都能保持同样的目录形态。
        # Phase 9 开始后，sandbox 工作区可能会先于 trace 初始化被准备出来，因此这里改成
        # “目录存在也可继续初始化”，但仍然保持配置快照、trace 和报告文件由这里统一落盘。
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_snapshot_path.write_text(
            json.dumps(config_snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # 先创建空 trace 文件，保证后续状态事件都从同一个文件追加。
        self.trace_path.write_text("", encoding="utf-8")
        # 初始化报告会在 run 结束时被正式报告覆盖；失败较早时也能保留基本任务信息。
        self.report_path.write_text(self._build_initial_report(config_snapshot), encoding="utf-8")

    def write_event(self, event: TraceEvent) -> None:
        """按 JSONL 方式追加写入一条 trace 事件。"""
        # JSONL 方便后面按事件流追加，也方便用脚本逐行分析。
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")

    def write_report(self, content: str) -> None:
        """覆盖写入当前 run 的 Markdown 报告。"""
        self.report_path.write_text(content, encoding="utf-8")

    def _build_initial_report(self, config_snapshot: dict[str, Any]) -> str:
        """生成 run 刚初始化时的最小报告内容。"""
        task = config_snapshot.get("task", "")
        task_type = config_snapshot.get("task_type", "")
        run_id = config_snapshot.get("run_id", "")
        # 这里先保留最小报告骨架，最终报告由 runner 在收尾阶段覆盖写入。
        return (
            f"# 运行报告\n\n"
            f"- Run ID：`{run_id}`\n"
            f"- 任务类型：`{task_type}`\n"
            f"- 任务内容：{task}\n\n"
            f"## 当前状态\n\n"
            f"`initialized`\n\n"
            f"## 说明\n\n"
            f"- run 已初始化，后续状态执行完成后会写入完整报告。\n"
        )
