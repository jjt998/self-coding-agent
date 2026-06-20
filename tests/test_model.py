from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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


def _valid_decision() -> dict:
    return {
        "summary": "已生成真实模型决策。",
        "rationale": "先搜索任务相关文本。",
        "planned_actions": ["搜索相关文件"],
        "cross_round_plan": ["下一轮根据验证结果继续调整。"],
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
    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {}
    assert user_payload["tool_schema"]["read_file"]["required"] == ["path"]
    assert user_payload["tool_schema"]["read_file"]["optional"] == []
    assert user_payload["tool_schema"]["read_file_range"]["required"] == ["path", "start_line", "end_line"]
    assert user_payload["tool_schema"]["read_file_range"]["max_lines"] == 40
    assert user_payload["tool_schema"]["replace_lines"]["required"] == ["path", "start_line", "end_line", "new_text"]
    assert user_payload["tool_schema"]["replace_lines"]["properties"]["new_text"]["type"] == "string"
    assert user_payload["tool_schema"]["search_text"]["optional"] == ["limit"]
    assert "cross_round_plan" in user_payload["decision_schema"]
    assert "本轮 tool_calls" in user_payload["decision_schema"]["planned_actions"][0]
    assert decision.provider == "openai_compatible"
    assert decision.model_name == "demo-model"
    assert decision.planned_actions == ["搜索相关文件"]
    assert decision.cross_round_plan == ["下一轮根据验证结果继续调整。"]
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
        runtime_feedback={"iteration": 2, "previous_verification": {"passed": False}},
    )

    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["runtime_feedback"] == {
        "iteration": 2,
        "previous_verification": {"passed": False},
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
            "verification": {"passed": False},
        },
        "previous_cross_round_plan": ["先修复失败 patch，再运行验证"],
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
    assert "file_context_cache" in prompt_text
    assert "最近五次读取片段" in prompt_text
    assert "previous_cross_round_plan" in prompt_text
    assert "cross_round_plan" in prompt_text
    assert "planned_actions" in prompt_text
    assert "ASCII stdout/stderr" in prompt_text
    assert "content_mode=\"full\"" in prompt_text
    assert "content_mode=\"structure_summary\"" in prompt_text
    assert "read_file_range" in prompt_text
    assert "1 到 40 行" in prompt_text
    assert "不要用它读取整个文件" in prompt_text
    assert "replace_lines" in prompt_text
    assert "old_text_not_found" in prompt_text
    assert "previous_reflect_feedback" not in prompt_text
    assert "replan_constraints" not in prompt_text
    assert "avoid_exact_tool_sequence" not in prompt_text


def test_openai_compatible_adapter_rejects_tool_input_fields_not_declared_in_schema(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeHttpResponse(
            _openai_response(
                {
                    "summary": "读取文件。",
                    "rationale": "错误地给 read_file 传入 limit。",
                    "planned_actions": ["读取 README"],
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
        adapter.decide(task="读取 README", task_type="general", context_snapshot=None, config_data={})
    except ModelResponseError as error:
        assert "未声明字段" in str(error)
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
                    "summary": "修复文件",
                    "rationale": "new_text 不能是 null。",
                    "planned_actions": ["本轮尝试 patch"],
                    "cross_round_plan": [],
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
        adapter.decide(task="修复 README", task_type="general", context_snapshot=None, config_data={})
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
                    "cross_round_plan": [],
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
