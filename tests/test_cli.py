from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run


def test_cli_creates_run_artifacts(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    # 先放一个和任务相关的说明文件，方便验证 Phase 5 的文件召回是否真的选中了它。
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这个仓库用于创建脚手架和验证最小 agent 流程。\n",
        encoding="utf-8",
    )
    long_lines = ["# 长说明"] + [f"第{i}行：这里继续讨论创建脚手架的实现细节。" for i in range(1, 55)]
    (repo_root / "LONG_GUIDE.md").write_text("\n".join(long_lines) + "\n", encoding="utf-8")
    (repo_root / "DIRECTORY_GUIDE.md").write_text(
        "# 目录说明\n\n这个文件主要介绍目录结构。\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "创建脚手架",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    # 这里显式补 PYTHONPATH，是为了让测试在 src 布局下直接按模块方式启动 CLI。
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    # Phase 1 的验收重点就是：一次 CLI 调用后，run 目录和三类基础产物都要落下来。
    run_dirs = list(output_root.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.md").exists()
    snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["task"] == "创建脚手架"

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    transition_targets = [
        event["payload"]["to_state"]
        for event in trace_events
        if event["event_type"] == "state_transitioned"
    ]
    assert transition_targets == [
        "ingest",
        "analyze",
        "plan",
        "act",
        "observe",
        "reflect",
        "verify",
        "finalize",
    ]

    tool_called_names = [
        event["payload"]["tool_name"]
        for event in trace_events
        if event["event_type"] == "tool_called"
    ]
    assert tool_called_names == [
        "search_text",
        "apply_patch",
        "read_file",
        "run_command",
        "git_diff",
    ]

    tool_results = [event["payload"] for event in trace_events if event["event_type"] == "tool_result"]
    assert len(tool_results) == 5
    assert tool_results[1]["tool_output"]["ok"] is True
    assert tool_results[2]["tool_output"]["content"].startswith("# Agent Notes")
    assert tool_results[3]["tool_output"]["stdout"].strip() == "# Agent Notes"
    assert tool_results[4]["tool_output"]["changed_file_count"] == 1
    assert "agent_notes.md" in tool_results[4]["tool_output"]["diffs"][0]["path"]

    verification_events = [event["payload"] for event in trace_events if event["event_type"] == "verification_result"]
    assert len(verification_events) == 1
    assert verification_events[0]["passed"] is True
    assert verification_events[0]["checks"][0]["name"] == "工具调用顺序"

    memory_write_events = [event["payload"] for event in trace_events if event["event_type"] == "memory_write_result"]
    assert len(memory_write_events) == 1
    assert memory_write_events[0]["written"] is True
    assert memory_write_events[0]["store_path"].endswith(".agent_memory\\long_term_memory.jsonl")

    context_events = [event["payload"] for event in trace_events if event["event_type"] == "context_snapshot"]
    assert len(context_events) == 1
    assert context_events[0]["task_context"]["task"] == "创建脚手架"
    assert context_events[0]["repo_context"]["candidate_file_count"] >= 3
    assert context_events[0]["repo_context"]["selected_file_count"] == 3
    assert context_events[0]["repo_context"]["clipped_file_count"] >= 1
    assert context_events[0]["repo_context"]["total_original_lines"] >= context_events[0]["repo_context"]["total_selected_lines"]
    assert context_events[0]["memory_context"]["enabled"] is True
    assert context_events[0]["memory_context"]["query"] == "general:创建脚手架"
    assert context_events[0]["memory_context"]["source"] == "runtime_memory_manager"
    assert len(context_events[0]["memory_context"]["matched_entries"]) >= 1
    assert len(context_events[0]["memory_context"]["runtime_rule_entries"]) >= 1
    assert context_events[0]["memory_context"]["long_term_entries"] == []
    assert context_events[0]["memory_context"]["conflict_evidence"] == []
    selected_files = context_events[0]["repo_context"]["selected_files"]
    selected_by_path = {item["path"]: item for item in selected_files}
    assert selected_by_path["README.md"]["injection_mode"] == "original"
    assert selected_by_path["README.md"]["included_line_count"] >= 1
    assert selected_by_path["README.md"]["was_clipped"] is False
    assert "# 项目说明" in selected_by_path["README.md"]["injection_content"]
    assert selected_by_path["LONG_GUIDE.md"]["injection_mode"] == "summary"
    assert selected_by_path["LONG_GUIDE.md"]["was_clipped"] is True
    assert "内容摘要：" in selected_by_path["LONG_GUIDE.md"]["injection_content"]
    assert selected_by_path["LONG_GUIDE.md"]["included_line_count"] == 8
    assert selected_by_path["DIRECTORY_GUIDE.md"]["injection_mode"] == "index"
    assert "索引提示：" in selected_by_path["DIRECTORY_GUIDE.md"]["injection_content"]

    notes_path = repo_root / "agent_notes.md"
    assert notes_path.exists()
    assert "当前情况：已记录到 Phase 3 工具闭环。" in notes_path.read_text(encoding="utf-8")

    memory_store_path = repo_root / ".agent_memory" / "long_term_memory.jsonl"
    assert memory_store_path.exists()
    memory_entries = [
        json.loads(line)
        for line in memory_store_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(memory_entries) == 1
    assert memory_entries[0]["task"] == "创建脚手架"
    assert memory_entries[0]["task_type"] == "general"
    assert memory_entries[0]["tags"] == ["general", "verified", "mvp"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "`finalize`" in report_text
    assert "reflect：已触发" in report_text
    assert "## 上下文摘要" in report_text
    assert "`README.md`" in report_text
    assert "`LONG_GUIDE.md`" in report_text
    assert "是否裁剪：是" in report_text
    assert "选中文件数：`3`" in report_text
    assert "memory：已启用" in report_text
    assert "长期 memory `0` 条" in report_text
    assert "## 工具调用摘要" in report_text
    assert "## 验证结果" in report_text
    assert "## Memory 写入" in report_text
    assert "写入状态：已写入" in report_text
    assert "验证状态：通过" in report_text
    assert "`apply_patch`：成功" in report_text


def test_cli_uses_task_type_specific_recall_strategy_for_bug_fix(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里主要介绍仓库背景。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    assert context_payload["task_context"]["task_type"] == "bug_fix"
    assert context_payload["repo_context"]["recall_strategy"] == "优先测试文件和相关代码文件"
    assert context_payload["memory_context"]["query"] == "bug_fix:修复 fail 错误"
    assert context_payload["memory_context"]["source"] == "runtime_memory_manager"
    assert len(context_payload["memory_context"]["matched_entries"]) >= 2
    assert len(context_payload["memory_context"]["runtime_rule_entries"]) >= 2
    assert context_payload["memory_context"]["long_term_entries"] == []
    assert context_payload["memory_context"]["conflict_evidence"] == []

    selected_files = context_payload["repo_context"]["selected_files"]
    selected_paths = [item["path"] for item in selected_files]
    assert "tests/test_app.py" in selected_paths
    assert "app.py" in selected_paths

    selected_by_path = {item["path"]: item for item in selected_files}
    assert "当前任务像修 bug" in selected_by_path["tests/test_app.py"]["reason"]
    assert "当前任务像修 bug" in selected_by_path["app.py"]["reason"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "召回倾向：优先测试文件和相关代码文件" in report_text
    assert "memory：已启用" in report_text
    assert "写入状态：已写入" in report_text


def test_cli_reads_long_term_memory_with_task_type_keyword_and_path_filters(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# 项目说明\n\n这里记录 app fail 问题和处理方式。\n",
        encoding="utf-8",
    )
    (repo_root / "app.py").write_text(
        "def broken_logic():\n    raise ValueError('fail to load data')\n",
        encoding="utf-8",
    )
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_broken_logic_error_message():\n    assert 'fail' in 'fail to load data'\n",
        encoding="utf-8",
    )

    memory_dir = repo_root / ".agent_memory"
    memory_dir.mkdir()
    memory_store_path = memory_dir / "long_term_memory.jsonl"
    memory_store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-memory-match",
                        "task": "修复 app fail 错误",
                        "task_type": "bug_fix",
                        "summary": "之前通过先看 test_app.py 和 app.py 很快定位了 fail 原因。",
                        "tags": ["bug_fix", "verified", "mvp"],
                        "evidence": {
                            "selected_context_files": ["app.py", "tests/test_app.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "run_id": "run-memory-ignore",
                        "task": "重构 utils helper",
                        "task_type": "refactor",
                        "summary": "这条经验和当前 bug 修复无关。",
                        "tags": ["refactor", "verified"],
                        "evidence": {
                            "selected_context_files": ["utils.py"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cli",
        "--task",
        "修复 app fail 错误",
        "--task-type",
        "bug_fix",
        "--repo-root",
        str(repo_root),
        "--output-root",
        str(output_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = run(command, capture_output=True, text=True, check=False, env=env)

    assert result.returncode == 0, result.stderr

    run_dir = list(output_root.iterdir())[0]
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_payload = next(event["payload"] for event in trace_events if event["event_type"] == "context_snapshot")
    memory_context = context_payload["memory_context"]
    assert memory_context["enabled"] is True
    assert len(memory_context["runtime_rule_entries"]) >= 2
    assert len(memory_context["long_term_entries"]) == 1
    assert len(memory_context["matched_entries"]) >= 3
    assert memory_context["conflict_evidence"] == []

    long_term_entry = memory_context["long_term_entries"][0]
    assert long_term_entry["source"] == "long_term_memory"
    assert long_term_entry["evidence"]["run_id"] == "run-memory-match"
    assert long_term_entry["evidence"]["matched_on"]["task_type"] == "bug_fix"
    assert "bug_fix" in long_term_entry["evidence"]["matched_on"]["tags"]
    assert "fail" in long_term_entry["evidence"]["matched_on"]["keywords"]
    assert "app.py" in long_term_entry["evidence"]["matched_on"]["file_paths"]
    assert "tests/test_app.py" in long_term_entry["evidence"]["matched_on"]["file_paths"]

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "长期 memory `1` 条" in report_text
