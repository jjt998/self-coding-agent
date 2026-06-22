from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from context import ContextBuilder
from memory import RuntimeMemoryManager
import model as model_module
from model import (
    ModelConfigError,
    ModelRequestError,
    ModelResponseError,
    OpenAICompatibleModelAdapter,
    build_model_adapter,
)


def _openai_response(decision: dict, usage: dict | None = None) -> dict:
    response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(decision, ensure_ascii=False),
                }
            }
        ]
    }
    if usage is not None:
        response["usage"] = usage
    return response


def _working_memory(
    *,
    confirmed_facts: str | list[str] = "",
    invalidated_beliefs: str | list[str] = "",
    completed_actions: str | list[str] = "",
    next_risks: str | list[str] = "",
) -> dict:
    return {
        "confirmed_facts": confirmed_facts,
        "invalidated_beliefs": invalidated_beliefs,
        "completed_actions": completed_actions,
        "next_risks": next_risks,
    }


def _valid_decision() -> dict:
    return {
        "summary": "已生成真实模型决策。",
        "rationale": "先搜索任务相关文本。",
        "planned_actions": ["搜索相关文件"],
        "working_memory": _working_memory(
            confirmed_facts=["任务需要定位 Demo 相关代码"],
            completed_actions=["已搜索任务相关文本"],
            next_risks=["还未读取源码片段"],
        ),
        "tool_calls": [
            {
                "tool_name": "search_text",
                "tool_input": {"query": "Demo", "limit": 5},
            }
        ],
    }


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_build_model_adapter_rejects_missing_or_unsupported_provider() -> None:
    try:
        build_model_adapter({})
    except ModelConfigError as error:
        assert error.details["field_path"] == "model"
    else:
        raise AssertionError("missing model config should fail")

    try:
        build_model_adapter({"model": {"provider": "rule_based", "name": "demo"}})
    except ModelConfigError as error:
        assert error.details["field_path"] == "model.provider"
        assert error.details["provider"] == "rule_based"
    else:
        raise AssertionError("unsupported provider should fail")

def test_build_model_adapter_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    try:
        build_model_adapter({"model": {"provider": "openai_compatible", "name": "demo"}})
    except ModelConfigError as error:
        assert "DEEPSEEK_API_KEY" in str(error)
        assert error.provider == "openai_compatible"
        assert error.model_name == "demo"
        assert error.details["api_key_env"] == "DEEPSEEK_API_KEY"
        assert "test-key" not in json.dumps(error.details, ensure_ascii=False)
    else:
        raise AssertionError("missing API key should fail")


def test_build_model_adapter_rejects_invalid_base_url(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    try:
        build_model_adapter(
            {"model": {"provider": "openai_compatible", "name": "demo", "base_url": "api.example.test/v1"}}
        )
    except ModelConfigError as error:
        assert error.details["field_path"] == "model.base_url"
        assert error.details["base_url"] == "api.example.test/v1"
    else:
        raise AssertionError("invalid base_url should fail")


def test_openai_compatible_adapter_parses_valid_http_response(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        return _FakeHttpResponse(_openai_response(_valid_decision()))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)

    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    decision = adapter.decide(
        task="检查 Demo",
        task_type="general",
        context_snapshot=None,
        config_data={},
    )

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "demo-model"
    assert adapter.get_last_request_payload()["model"] == "demo-model"
    assert adapter.get_last_request_payload()["messages"] == captured["body"]["messages"]
    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {}
    assert user_payload["tool_schema"]["read_file"]["required"] == ["path"]
    assert user_payload["tool_schema"]["read_file"]["optional"] == []
    assert user_payload["tool_schema"]["read_file_structure_summary"]["required"] == ["path"]
    assert user_payload["tool_schema"]["read_file_range"]["required"] == ["path", "start_line", "end_line"]
    assert user_payload["tool_schema"]["read_file_range"]["max_lines"] == 80
    assert user_payload["tool_schema"]["replace_lines"]["required"] == ["path", "start_line", "end_line", "new_text"]
    assert user_payload["tool_schema"]["replace_lines"]["properties"]["new_text"]["type"] == "string"
    assert user_payload["tool_schema"]["search_text"]["optional"] == ["limit"]
    assert "working_memory" in user_payload["decision_schema"]
    assert "本轮 tool_calls" in user_payload["decision_schema"]["planned_actions"][0]
    assert decision.provider == "openai_compatible"
    assert decision.model_name == "demo-model"
    assert decision.planned_actions == ["搜索相关文件"]
    assert decision.working_memory["completed_actions"] == ["已搜索任务相关文本"]
    assert decision.tool_calls[0].tool_name == "search_text"
    assert decision.tool_calls[0].tool_input == {"query": "Demo", "limit": 5}
    assert decision.token_usage.available is False
    assert json.loads(decision.raw_response_content)["summary"] == "已生成真实模型决策。"
    assert "raw_response_content" not in decision.to_dict()


def test_openai_compatible_adapter_extracts_token_usage_when_provider_returns_usage(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                _valid_decision(),
                usage={"prompt_tokens": 101, "completion_tokens": 19, "total_tokens": 120},
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    decision = adapter.decide(task="检查 Demo", task_type="general", context_snapshot=None, config_data={})

    assert decision.token_usage.available is True
    assert decision.token_usage.prompt_tokens == 101
    assert decision.token_usage.completion_tokens == 19
    assert decision.token_usage.total_tokens == 120
    assert decision.to_dict()["token_usage"]["total_tokens"] == 120


def test_openai_compatible_adapter_includes_runtime_feedback(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(_openai_response(_valid_decision()))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    adapter.decide(
        task="检查 Demo",
        task_type="general",
        context_snapshot=None,
        config_data={},
        runtime_feedback={
            "current_iteration": 2,
            "previous_rationale": "上一轮先读 README，再确认修改点。",
            "working_memory": _working_memory(completed_actions=["已读取 README.md"]),
        },
    )

    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {
        "current_iteration": 2,
        "previous_rationale": "上一轮先读 README，再确认修改点。",
        "working_memory": _working_memory(completed_actions=["已读取 README.md"]),
    }
    assert "tool_schema" in user_payload


def test_openai_compatible_adapter_includes_factual_reflect_feedback(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(_openai_response(_valid_decision()))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    runtime_feedback = {
        "previous_reflect": {
            "trigger": "after_act",
            "signals": ["failed_tool_observed"],
            "failed_tools": [{"tool_name": "apply_patch", "error": "old_text_not_found"}],
        },
        "working_memory": _working_memory(
            completed_actions=["已修复失败 patch", "已运行验证命令"],
            next_risks="还未重新验证新 patch。",
        ),
    }
    adapter.decide(
        task="Demo",
        task_type="general",
        context_snapshot=None,
        config_data={},
        runtime_feedback=runtime_feedback,
    )

    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == runtime_feedback
    prompt_text = "\n".join(message["content"] for message in captured["body"]["messages"] if message["role"] == "system")
    assert "runtime_feedback.previous_reflect" in prompt_text
    assert "runtime_feedback.previous_rationale" in prompt_text
    assert "file_context_cache" in prompt_text
    assert "最近五次读取结果" in prompt_text
    assert "cache_status=stale" in prompt_text
    assert "stale_file_paths 只列出当前仍然 stale 的文件" in prompt_text
    assert "reread_fresh_ranges" in prompt_text
    assert "safe_to_rely_ranges" in prompt_text
    assert "runtime_feedback.current_iteration" in prompt_text
    assert "当前正处于第几轮求解" in prompt_text
    assert "不会提供最大轮数、剩余轮数或任何预算信息" in prompt_text
    assert "runtime_feedback.working_memory" in prompt_text
    assert "working_memory" in prompt_text
    assert "任务描述描述的是待修复现象，不保证与当前轮已修改后的文件内容一致" in prompt_text
    assert "优先相信当前轮可验证的运行时证据" in prompt_text
    assert "如果关键目标函数已经处于 fresh 状态" in prompt_text
    assert "不要仅因为任务描述与当前代码冲突，就立刻扩展读取外围 helper" in prompt_text
    assert "并优先运行核心命令校验当前代码行为" in prompt_text
    assert "凡是被当前轮代码读取结果、命令输出或 diff 直接否定的旧怀疑" in prompt_text
    assert "必须写入 invalidated_beliefs" in prompt_text
    assert "working_memory 不再保留专门的 open_questions 字段" in prompt_text
    assert "由 harness 根据本轮 tool_calls 是否为空来决定" in prompt_text
    assert "bug_fix 收口规则" in prompt_text
    assert "当前 diff 已经命中任务目标修改点" in prompt_text
    assert "核心验证命令已经符合预期" in prompt_text
    assert "继续扩展读取外围函数" in prompt_text
    assert "不要再输出 loop_end" not in prompt_text
    assert "tool_calls" in prompt_text
    assert "confirmed_facts" in prompt_text
    assert "completed_actions" in prompt_text
    assert "不要依赖 harness 帮你 merge" in prompt_text
    assert "planned_actions" in prompt_text
    assert "ASCII stdout/stderr" in prompt_text
    assert "content_mode=\"full\"" in prompt_text
    assert "content_mode=\"structure_summary\"" in prompt_text
    assert "read_file_structure_summary" in prompt_text
    assert "read_file_range" in prompt_text
    assert "1 到 80 行" in prompt_text
    assert "不要用它读取整个文件" in prompt_text
    assert "replace_lines" in prompt_text
    assert "默认先使用 apply_patch" in prompt_text
    assert "不要一开始就把 replace_lines 当成主编辑方式" in prompt_text
    assert "apply_patch 连续失败" in prompt_text
    assert "old_text_not_found" in prompt_text
    assert "重新读取目标范围并确认最新行号" in prompt_text
    assert "stale_reread_guidance" in prompt_text
    assert "recommended_sequence" in prompt_text
    assert "read_file_structure_summary -> read_file_range" in prompt_text
    assert "不要仅因为文件曾经 stale 过就重复读取同一函数" in prompt_text
    assert "previous_reflect_feedback" not in prompt_text
    assert "replan_constraints" not in prompt_text
    assert "avoid_exact_tool_sequence" not in prompt_text


def test_openai_compatible_adapter_includes_refactor_runtime_rule_in_context_snapshot(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeHttpResponse(_openai_response(_valid_decision()))

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "task_board.py").write_text("from task_board.query_engine import render_task_list\n", encoding="utf-8")
    package_dir = repo_root / "task_board"
    package_dir.mkdir()
    (package_dir / "query_engine.py").write_text(
        "\n".join(
            [
                "from typing import Any",
                "",
                "def collect_matching_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:",
                "    return list(tasks)",
                "",
                "def collect_export_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:",
                "    return list(tasks)",
                "",
                "def render_task_list(tasks: list[dict[str, Any]]) -> str:",
                "    return str(len(tasks))",
                "",
                "def render_export_list(tasks: list[dict[str, Any]]) -> str:",
                "    return str(len(tasks))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    memory_manager = RuntimeMemoryManager(repo_root=str(repo_root))
    memory_search = memory_manager.search(
        task="重构 task_board/query_engine.py，共享 filter-and-sort helper",
        task_type="refactor",
    )
    snapshot = ContextBuilder(repo_root=str(repo_root)).build_context_snapshot(
        task="重构 task_board/query_engine.py，共享 filter-and-sort helper",
        task_type="refactor",
        current_state="analyze",
        completed_states=[],
        step_count=1,
        memory_query=memory_manager.build_query(
            task="重构 task_board/query_engine.py，共享 filter-and-sort helper",
            task_type="refactor",
        ),
        matched_memory_entries=[entry.to_dict() for entry in memory_search.all_entries()],
        runtime_rule_entries=[entry.to_dict() for entry in memory_search.runtime_rule_entries],
        long_term_memory_entries=[entry.to_dict() for entry in memory_search.long_term_entries],
        suppressed_long_term_entries=list(memory_search.suppressed_long_term_entries),
        memory_conflict_evidence=list(memory_search.conflict_evidence),
        memory_diagnostic_labels=list(memory_search.diagnostic_labels),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    adapter.decide(
        task="重构 task_board/query_engine.py，共享 filter-and-sort helper",
        task_type="refactor",
        context_snapshot=snapshot,
        config_data={},
    )

    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    runtime_rule_entries = user_payload["context_snapshot"]["memory_context"]["runtime_rule_entries"]
    compat_rule = next(item for item in runtime_rule_entries if item["title"] == "兼容式重构优先原则")
    assert "未验证通过前不要删除旧函数" in compat_rule["summary"]
    assert "默认允许保留旧函数" in compat_rule["summary"]


def test_openai_compatible_adapter_rejects_tool_input_fields_not_declared_in_schema(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "read file",
                    "rationale": "invalid extra field",
                    "planned_actions": ["read README"],
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "tool_input": {"path": "README.md", "limit": 20},
                        }
                    ],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    try:
        adapter.decide(task="read README", task_type="general", context_snapshot=None, config_data={})
    except ModelResponseError as error:
        assert error.details["field_path"] == "tool_calls[1].tool_input"
        assert error.details["tool_name"] == "read_file"
        assert error.details["invalid_fields"] == ["limit"]
        assert "path" in error.details["allowed_fields"]
    else:
        raise AssertionError("invalid read_file limit should raise ModelResponseError")

def test_openai_compatible_adapter_normalizes_declared_tool_input_alias(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "读取文件。",
                    "rationale": "使用兼容别名读取文件。",
                    "planned_actions": ["读取 README"],
                    "working_memory": _working_memory(completed_actions=["已准备读取 README.md"]),
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "tool_input": {"file_path": "README.md"},
                        }
                    ],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    decision = adapter.decide(task="读取 README", task_type="general", context_snapshot=None, config_data={})

    assert decision.tool_calls[0].tool_input == {"path": "README.md"}


def test_openai_compatible_adapter_rejects_tool_input_type_mismatch(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "patch file",
                    "rationale": "new_text cannot be null",
                    "planned_actions": ["apply patch"],
                    "working_memory": _working_memory(),
                    "tool_calls": [
                        {
                            "tool_name": "apply_patch",
                            "tool_input": {"path": "README.md", "old_text": None, "new_text": None},
                        }
                    ],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    try:
        adapter.decide(task="fix README", task_type="general", context_snapshot=None, config_data={})
    except ModelResponseError as error:
        assert error.details["field_path"] == "tool_calls[1].tool_input.new_text"
        assert error.details["tool_name"] == "apply_patch"
        assert error.details["expected_type"] == "string"
        assert error.details["actual_type"] == "NoneType"
    else:
        raise AssertionError("invalid apply_patch new_text should raise ModelResponseError")

def test_openai_compatible_adapter_rejects_new_tool_input_type_mismatch(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "按行替换文件",
                    "rationale": "new_text 不能是 null。",
                    "planned_actions": ["本轮尝试按行替换"],
                    "working_memory": _working_memory(),
                    "tool_calls": [
                        {
                            "tool_name": "replace_lines",
                            "tool_input": {
                                "path": "README.md",
                                "start_line": 1,
                                "end_line": 1,
                                "new_text": None,
                            },
                        }
                    ],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    try:
        adapter.decide(task="修复 README", task_type="general", context_snapshot=None, config_data={})
    except ModelResponseError as error:
        assert error.details["field_path"] == "tool_calls[1].tool_input.new_text"
        assert error.details["tool_name"] == "replace_lines"
        assert error.details["expected_type"] == "string"
        assert error.details["actual_type"] == "NoneType"
    else:
        raise AssertionError("invalid replace_lines new_text should raise ModelResponseError")


def test_openai_compatible_adapter_ignores_legacy_loop_end_field(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "finish solve",
                    "rationale": "no more work is needed",
                    "loop_end": True,
                    "planned_actions": ["read README"],
                    "working_memory": _working_memory(completed_actions=["checked existing result"]),
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "tool_input": {"path": "README.md"},
                        }
                    ],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    decision = adapter.decide(task="check README", task_type="general", context_snapshot=None, config_data={})

    assert decision.summary == "finish solve"
    assert decision.tool_calls[0].tool_name == "read_file"
    assert decision.working_memory["completed_actions"] == ["checked existing result"]

def test_openai_compatible_adapter_raises_on_os_error(monkeypatch) -> None:
    def fake_urlopen(_request, timeout=None):
        raise OSError("network down")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    try:
        adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
    except ModelRequestError as error:
        assert "模型请求失败" in str(error) or "network down" in str(error)
        assert error.details["request_error_type"] == "OSError"
        assert error.details["base_url"] == "https://example.test/v1"
        assert error.details["timeout_seconds"] == 7
    else:
        raise AssertionError("HTTP failure should raise ModelRequestError")


def test_openai_compatible_adapter_raises_on_http_status_error(monkeypatch) -> None:
    def fake_urlopen(_request, timeout=None):
        body = ("x" * 400).encode("utf-8")
        raise HTTPError(
            "https://example.test/v1/chat/completions",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=_BytesBody(body),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    try:
        adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
    except ModelRequestError as error:
        assert error.details["status_code"] == 429
        assert error.details["response_excerpt"].endswith("...[truncated]")
        assert len(error.details["response_excerpt"]) < 330
    else:
        raise AssertionError("HTTP status failure should raise ModelRequestError")


def test_openai_compatible_adapter_raises_on_url_and_timeout_errors(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", raising=False)
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    for raised_error, expected_type in [
        (URLError("dns failed"), "URLError"),
        (TimeoutError("slow"), "TimeoutError"),
    ]:
        monkeypatch.setattr(
            model_module,
            "urlopen",
            lambda _request, timeout=None, error=raised_error: (_ for _ in ()).throw(error),
        )
        try:
            adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
        except ModelRequestError as error:
            assert error.details["request_error_type"] == expected_type
            assert error.details["timeout_seconds"] == 7
        else:
            raise AssertionError("request failure should raise ModelRequestError")


def test_openai_compatible_adapter_normalizes_non_executable_planned_actions(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    cases = [
        ("读取文件并修复", ["读取文件并修复"], "coerced_string_to_single_item_list"),
        ([{"step": "读取文件"}, {"action": "修复代码"}], ["读取文件", "修复代码"], "coerced_list_items_to_strings"),
        ([], ["执行工具：search_text"], "empty_list_fallback_to_tool_calls"),
    ]
    for raw_planned_actions, expected_actions, expected_reason in cases:
        response_payload = _openai_response({**_valid_decision(), "planned_actions": raw_planned_actions})
        monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", json.dumps(response_payload, ensure_ascii=False))

        decision = adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})

        assert decision.planned_actions == expected_actions
        assert decision.normalization_notes[0]["field_path"] == "planned_actions"
        assert decision.normalization_notes[0]["reason"] == expected_reason
        assert "normalization_notes" not in decision.to_dict()


def test_openai_compatible_adapter_accepts_working_memory_as_strings_lists_or_mixed(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    cases = [
        _working_memory(
            confirmed_facts="已确认事实",
            invalidated_beliefs="旧判断无效",
            completed_actions="已完成动作",
            next_risks="还要再验证",
        ),
        _working_memory(
            confirmed_facts=["已确认事实"],
            invalidated_beliefs=["旧判断无效"],
            completed_actions=["已完成动作"],
            next_risks=["还要再验证"],
        ),
        _working_memory(
            confirmed_facts="已确认事实",
            invalidated_beliefs="旧判断无效",
            completed_actions=["已完成动作"],
            next_risks="还要再验证",
        ),
    ]
    for working_memory in cases:
        response_payload = _openai_response({**_valid_decision(), "working_memory": working_memory})
        monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", json.dumps(response_payload, ensure_ascii=False))
        decision = adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
        assert decision.working_memory == working_memory


def test_openai_compatible_adapter_rejects_invalid_working_memory_shape(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    cases = [
        ({**_valid_decision(), "working_memory": "bad"}, "working_memory"),
        ({**_valid_decision(), "working_memory": {"confirmed_facts": "only one field"}}, "working_memory"),
        (
            {
                **_valid_decision(),
                "working_memory": _working_memory(completed_actions=["ok", 1]),
            },
            "working_memory.completed_actions",
        ),
    ]
    for raw_decision, field_path in cases:
        monkeypatch.setenv(
            "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
            json.dumps(_openai_response(raw_decision), ensure_ascii=False),
        )
        try:
            adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
        except ModelResponseError as error:
            assert error.details["field_path"] == field_path
        else:
            raise AssertionError("invalid working_memory should raise ModelResponseError")


def test_openai_compatible_adapter_rejects_invalid_response(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    cases = [
        ({"choices": [{"message": {"content": "not json"}}]}, "choices[0].message.content", None),
        (_openai_response({"summary": "少字段"}), "rationale", None),
        (
            _openai_response({**_valid_decision(), "tool_calls": [{"tool_name": "unknown", "tool_input": {}}]}),
            "tool_calls[1].tool_name",
            1,
        ),
        (
            _openai_response(
                {**_valid_decision(), "tool_calls": [{"tool_name": "search_text", "tool_input": "bad"}]}
            ),
            "tool_calls[1].tool_input",
            1,
        ),
    ]
    for case in cases:
        response_payload, field_path, tool_index = case
        monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", json.dumps(response_payload, ensure_ascii=False))
        try:
            adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
        except ModelResponseError as error:
            assert error.details["field_path"] == field_path
            if tool_index is not None:
                assert error.details["tool_call_index"] == tool_index
            if field_path != "choices[0].message.content":
                assert "response_excerpt" in error.details
            assert "test-key" not in json.dumps(error.details, ensure_ascii=False)
        else:
            raise AssertionError("invalid model response should raise ModelResponseError")


class _BytesBody:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

