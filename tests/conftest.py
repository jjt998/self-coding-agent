from __future__ import annotations

import json
import sys

import pytest


def _fake_model_response() -> str:
    """提供 subprocess 测试可继承的假模型响应，避免回归测试访问外网。"""
    decision = {
        "summary": "已生成测试模型决策。",
        "rationale": "测试环境固定返回旧工具链等价计划。",
        "planned_actions": ["执行测试工具计划"],
        "tool_calls": [
            {"tool_name": "search_text", "tool_input": {"query": "Agent Notes", "limit": 5}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "path": "agent_notes.md",
                    "old_text": None,
                    "new_text": "# Agent Notes\n\n- 任务：测试任务\n- 当前情况：已记录到 Phase 3 工具闭环。\n",
                },
            },
            {"tool_name": "read_file", "tool_input": {"path": "agent_notes.md"}},
            {
                "tool_name": "run_command",
                "tool_input": {
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; print(Path('agent_notes.md').read_text(encoding='utf-8').splitlines()[0])",
                    ]
                },
            },
            {"tool_name": "git_diff", "tool_input": {"paths": ["agent_notes.md"]}},
        ],
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(decision, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )


@pytest.fixture(autouse=True)
def fake_model_environment(monkeypatch) -> None:
    """默认让测试使用可审计的假模型响应；功能代码仍要求 API key 存在。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", _fake_model_response())
