from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import model as model_module
from model import (
    ModelConfigError,
    ModelRequestError,
    ModelResponseError,
    OpenAICompatibleModelAdapter,
    build_model_adapter,
)


def _openai_response(decision: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(decision, ensure_ascii=False),
                }
            }
        ]
    }


def _valid_decision() -> dict:
    return {
        "summary": "已生成真实模型决策。",
        "rationale": "先搜索任务相关文本。",
        "planned_actions": ["搜索相关文件"],
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
        assert "缺少 model 配置" in str(error)
    else:
        raise AssertionError("missing model config should fail")

    try:
        build_model_adapter({"model": {"provider": "rule_based", "name": "demo"}})
    except ModelConfigError as error:
        assert "不支持的 model.provider" in str(error)
    else:
        raise AssertionError("unsupported provider should fail")


def test_build_model_adapter_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        build_model_adapter({"model": {"provider": "openai_compatible", "name": "demo"}})
    except ModelConfigError as error:
        assert "OPENAI_API_KEY" in str(error)
        assert error.provider == "openai_compatible"
        assert error.model_name == "demo"
    else:
        raise AssertionError("missing API key should fail")


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
    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {}
    assert decision.provider == "openai_compatible"
    assert decision.model_name == "demo-model"
    assert decision.planned_actions == ["搜索相关文件"]
    assert decision.tool_calls[0].tool_name == "search_text"
    assert decision.tool_calls[0].tool_input == {"query": "Demo", "limit": 5}


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
        runtime_feedback={"iteration": 2, "previous_verification": {"passed": False}},
    )

    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {
        "iteration": 2,
        "previous_verification": {"passed": False},
    }


def test_openai_compatible_adapter_includes_reflect_feedback_constraints(monkeypatch) -> None:
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
        "iteration": 2,
        "previous_reflect_feedback": {
            "trigger": "verification_failed",
            "replan_constraints": {
                "failure_reason": "verification_failed",
                "avoid_exact_tool_sequence": ["read_file", "git_diff"],
            },
        },
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
    assert "runtime_feedback.previous_reflect_feedback" in prompt_text
    assert "replan_constraints" in prompt_text
    assert "avoid_exact_tool_sequence" in prompt_text
    assert "重规划硬约束" in prompt_text
    assert "必须在 rationale 或 planned_actions 中明确回应" in prompt_text


def test_openai_compatible_adapter_raises_on_http_error(monkeypatch) -> None:
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
    else:
        raise AssertionError("HTTP failure should raise ModelRequestError")


def test_openai_compatible_adapter_rejects_invalid_response(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    adapter = OpenAICompatibleModelAdapter(
        provider="openai_compatible",
        model_name="demo-model",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        timeout_seconds=7,
    )

    for response_payload in [
        {"choices": [{"message": {"content": "not json"}}]},
        _openai_response({"summary": "少字段"}),
        _openai_response({**_valid_decision(), "tool_calls": [{"tool_name": "unknown", "tool_input": {}}]}),
        _openai_response({**_valid_decision(), "tool_calls": [{"tool_name": "search_text", "tool_input": "bad"}]}),
    ]:
        monkeypatch.setenv("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", json.dumps(response_payload, ensure_ascii=False))
        try:
            adapter.decide(task="任务", task_type="general", context_snapshot=None, config_data={})
        except ModelResponseError:
            pass
        else:
            raise AssertionError("invalid model response should raise ModelResponseError")
