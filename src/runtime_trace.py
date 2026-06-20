from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return the UTC ISO timestamp used by trace events."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class TraceEvent:
    """A structured event appended to the JSONL trace."""

    event_type: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def to_json(self) -> str:
        """Serialize the event into a single JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceWriter:
    """Create and update the run trace, report, and related artifacts."""

    def __init__(self, run_dir: Path) -> None:
        """Prepare artifact paths under the given run directory."""
        self.run_dir = run_dir
        self.trace_path = run_dir / "trace.jsonl"
        self.report_path = run_dir / "report.md"
        self.trace_view_path = run_dir / "trace_view.html"
        self.config_snapshot_path = run_dir / "config_snapshot.json"

    def initialize(self, config_snapshot: dict[str, Any]) -> None:
        """Initialize the run directory, config snapshot, trace, and report."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_snapshot_path.write_text(
            json.dumps(config_snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.trace_path.write_text("", encoding="utf-8")
        self.report_path.write_text(self._build_initial_report(config_snapshot), encoding="utf-8")

    def write_event(self, event: TraceEvent) -> None:
        """Append one event to the JSONL trace."""
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")

    def write_report(self, content: str) -> None:
        """Overwrite the current Markdown run report."""
        self.report_path.write_text(content, encoding="utf-8")

    def write_trace_view(self, content: str) -> None:
        """Write the current run's HTML trace view."""
        self.trace_view_path.write_text(content, encoding="utf-8")

    def _build_initial_report(self, config_snapshot: dict[str, Any]) -> str:
        """Build the minimal report skeleton written at initialization time."""
        task = config_snapshot.get("task", "")
        task_type = config_snapshot.get("task_type", "")
        run_id = config_snapshot.get("run_id", "")
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
