from __future__ import annotations

import json
import sys

import pytest


def _fake_model_response() -> str:
    """提供 subprocess 测试可继承的假模型响应，避免回归测试访问外网。"""
    decision = {
        "summary": "已生成测试模型决策。",
        "rationale": (
            "测试环境固定返回真实 loop 测试计划；如存在 observe 反馈，则回应 "
            "verification_failed、missing_task_verification、task_verification_configured、"
            "verify_command_1、no_progress_after_observe、produce_observable_file_change、"
            "fix_failing_verification_checks；再次重复相同工具序列是因为 subprocess "
            "假模型响应不能按轮次动态变化。"
        ),
        "planned_actions": [
            "执行测试工具计划，并覆盖 verification_failed / missing_task_verification / "
            "task_verification_configured / verify_command_1 / no_progress_after_observe / "
            "produce_observable_file_change / fix_failing_verification_checks"
        ],
        "working_memory": {
            "confirmed_facts": [],
            "invalidated_beliefs": [],
            "completed_actions": ["已准备执行测试工具计划"],
            "next_risks": [],
        },
        "tool_calls": [
            {"tool_name": "search_text", "tool_input": {"query": "Run Evidence", "limit": 5}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "path": "run_evidence.md",
                    "old_text": None,
                    "new_text": "# Run Evidence\n\n- 任务：测试任务\n- 当前情况：已记录到 真实 loop 运行证据。\n",
                },
            },
            {"tool_name": "read_file", "tool_input": {"path": "run_evidence.md"}},
            {
                "tool_name": "run_command",
                "tool_input": {
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; print(Path('run_evidence.md').read_text(encoding='utf-8').splitlines()[0])",
                    ]
                },
            },
            {"tool_name": "git_diff", "tool_input": {"paths": ["run_evidence.md"]}},
        ],
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )


@pytest.fixture(autouse=True)
def fake_model_environment(monkeypatch) -> None:
    """默认让测试使用可审计的假模型响应；功能代码仍要求 API key 存在。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", _fake_model_response())

