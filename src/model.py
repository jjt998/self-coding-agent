from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from context import ContextSnapshot


ALLOWED_TOOL_NAMES = {"search_text", "read_file", "apply_patch", "run_command", "git_diff"}


class ModelError(Exception):
    """模型决策层异常基类，供 loop 统一收口成 model_error。"""

    def __init__(self, message: str, provider: str = "", model_name: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.model_name = model_name


class ModelConfigError(ModelError):
    """模型配置不合法，例如缺少 provider、模型名或 API key。"""


class ModelRequestError(ModelError):
    """模型 HTTP 请求失败，例如网络错误或非 2xx 返回。"""


class ModelResponseError(ModelError):
    """模型响应不符合约定，例如不是合法 JSON 或工具计划非法。"""


@dataclass(slots=True)
class PlannedToolCall:
    """描述决策层规划出来的一次工具调用，后面 `act` 阶段会按顺序执行。"""

    tool_name: str
    tool_input: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，方便直接写入 trace。"""
        return asdict(self)


@dataclass(slots=True)
class ModelDecision:
    """保存一次任务级决策结果，包括计划说明和准备执行的工具步骤。"""

    provider: str
    model_name: str
    task_type: str
    summary: str
    rationale: str
    planned_actions: list[str] = field(default_factory=list)
    tool_calls: list[PlannedToolCall] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，便于 trace 和报告复用。"""
        data = asdict(self)
        data["tool_calls"] = [tool_call.to_dict() for tool_call in self.tool_calls]
        return data


class ModelAdapter:
    """抽象一次任务级决策接口，具体实现负责产出结构化工具计划。"""

    provider: str
    model_name: str

    def decide(
        self,
        task: str,
        task_type: str,
        context_snapshot: ContextSnapshot | None,
        config_data: dict[str, Any],
        runtime_feedback: dict[str, Any] | None = None,
    ) -> ModelDecision:
        """根据任务、上下文和配置，产出一次结构化决策结果。"""
        raise NotImplementedError


class OpenAICompatibleModelAdapter(ModelAdapter):
    """通过 OpenAI 兼容 chat completions 接口获取任务级决策。"""

    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        base_url: str,
        api_key_env: str,
        timeout_seconds: int,
    ) -> None:
        """记录模型连接配置，并在初始化时强制检查 API key。"""
        self.provider = provider
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self.api_key = os.environ.get(api_key_env, "").strip()
        if not self.api_key:
            raise ModelConfigError(
                f"缺少模型 API key 环境变量：{api_key_env}",
                provider=provider,
                model_name=model_name,
            )

    def decide(
        self,
        task: str,
        task_type: str,
        context_snapshot: ContextSnapshot | None,
        config_data: dict[str, Any],
        runtime_feedback: dict[str, Any] | None = None,
    ) -> ModelDecision:
        """调用模型并把返回内容解析成稳定的 ModelDecision。"""
        request_payload = self._build_request_payload(
            task=task,
            task_type=task_type,
            context_snapshot=context_snapshot,
            runtime_feedback=runtime_feedback,
        )
        response_payload = self._request_chat_completion(request_payload)
        raw_decision = self._extract_decision_json(response_payload)
        return self._parse_model_decision(raw_decision=raw_decision, task_type=task_type)

    def _build_request_payload(
        self,
        task: str,
        task_type: str,
        context_snapshot: ContextSnapshot | None,
        runtime_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造模型请求，只要求返回一份 JSON 决策对象。"""
        context_payload = context_snapshot.to_dict() if context_snapshot else {}
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是本地代码任务 harness 的决策层。"
                        "必须只返回 JSON 对象，不要 Markdown。"
                        "JSON 字段必须包含 summary、rationale、planned_actions、tool_calls。"
                        "tool_calls 里的 tool_name 只能是 search_text、read_file、apply_patch、run_command、git_diff，"
                        "tool_input 必须是对象。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "重规划硬约束：当 runtime_feedback.previous_reflect_feedback 存在时，"
                        "下一轮 plan 必须在 rationale 或 planned_actions 中明确回应 "
                        "replan_constraints.failure_reason、failed_check_names、must_address。"
                        "除非 rationale 明确说明重复原因，否则不得重复 "
                        "replan_constraints.avoid_exact_tool_sequence 中完全相同的失败工具序列。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task,
                            "task_type": task_type,
                            "context_snapshot": context_payload,
                            "runtime_feedback": runtime_feedback or {},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    def _request_chat_completion(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """执行 HTTP 请求；测试可通过环境变量提供假响应但仍必须配置 API key。"""
        fake_response = os.environ.get("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", "").strip()
        if fake_response:
            try:
                return json.loads(fake_response)
            except json.JSONDecodeError as error:
                raise ModelResponseError(
                    f"测试模型响应不是合法 JSON：{error}",
                    provider=self.provider,
                    model_name=self.model_name,
                ) from error

        request = Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise ModelRequestError(
                f"模型请求返回 HTTP {error.code}：{error_body[:300]}",
                provider=self.provider,
                model_name=self.model_name,
            ) from error
        except URLError as error:
            raise ModelRequestError(
                f"模型请求失败：{error.reason}",
                provider=self.provider,
                model_name=self.model_name,
            ) from error
        except TimeoutError as error:
            raise ModelRequestError(
                "模型请求超时。",
                provider=self.provider,
                model_name=self.model_name,
            ) from error
        except OSError as error:
            raise ModelRequestError(
                f"模型请求失败：{error}",
                provider=self.provider,
                model_name=self.model_name,
            ) from error

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                f"模型 HTTP 响应不是合法 JSON：{error}",
                provider=self.provider,
                model_name=self.model_name,
            ) from error

    def _extract_decision_json(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        """从 OpenAI 兼容响应中取出 message.content 并解析为决策 JSON。"""
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelResponseError(
                "模型响应缺少 choices[0].message.content。",
                provider=self.provider,
                model_name=self.model_name,
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError(
                "模型响应 content 为空或不是字符串。",
                provider=self.provider,
                model_name=self.model_name,
            )

        try:
            raw_decision = json.loads(content)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                f"模型决策 content 不是合法 JSON：{error}",
                provider=self.provider,
                model_name=self.model_name,
            ) from error
        if not isinstance(raw_decision, dict):
            raise ModelResponseError(
                "模型决策 JSON 必须是对象。",
                provider=self.provider,
                model_name=self.model_name,
            )
        return raw_decision

    def _parse_model_decision(self, raw_decision: dict[str, Any], task_type: str) -> ModelDecision:
        """校验模型决策字段，并转换成内部数据结构。"""
        summary = _required_string(raw_decision, "summary", self)
        rationale = _required_string(raw_decision, "rationale", self)
        planned_actions = _required_string_list(raw_decision, "planned_actions", self)
        tool_calls = _required_tool_calls(raw_decision, self)
        return ModelDecision(
            provider=self.provider,
            model_name=self.model_name,
            task_type=task_type,
            summary=summary,
            rationale=rationale,
            planned_actions=planned_actions,
            tool_calls=tool_calls,
        )


def build_model_adapter(config_data: dict[str, Any]) -> ModelAdapter:
    """根据配置构建真实模型适配器；当前只接受 OpenAI 兼容 provider。"""
    model_config = config_data.get("model")
    if not isinstance(model_config, dict):
        raise ModelConfigError("缺少 model 配置。")

    provider = str(model_config.get("provider", "")).strip()
    if provider != "openai_compatible":
        raise ModelConfigError(f"不支持的 model.provider：{provider or '空'}", provider=provider)

    model_name = str(model_config.get("name", "")).strip()
    if not model_name:
        raise ModelConfigError("缺少 model.name。", provider=provider)

    base_url = str(model_config.get("base_url", "https://api.openai.com/v1")).strip()
    if not base_url:
        base_url = "https://api.openai.com/v1"
    api_key_env = str(model_config.get("api_key_env", "OPENAI_API_KEY")).strip() or "OPENAI_API_KEY"
    timeout_seconds = _normalize_timeout_seconds(model_config.get("timeout_seconds"))
    return OpenAICompatibleModelAdapter(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
    )


def _normalize_timeout_seconds(raw_value: Any) -> int:
    """把模型超时配置收敛成正整数。"""
    if isinstance(raw_value, int) and raw_value > 0:
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = int(raw_value.strip())
        except ValueError:
            return 30
        return parsed if parsed > 0 else 30
    return 30


def _required_string(raw_decision: dict[str, Any], field_name: str, adapter: OpenAICompatibleModelAdapter) -> str:
    """读取必填字符串字段。"""
    value = raw_decision.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(
            f"模型决策缺少必填字符串字段：{field_name}",
            provider=adapter.provider,
            model_name=adapter.model_name,
        )
    return value.strip()


def _required_string_list(
    raw_decision: dict[str, Any],
    field_name: str,
    adapter: OpenAICompatibleModelAdapter,
) -> list[str]:
    """读取必填字符串列表字段。"""
    value = raw_decision.get(field_name)
    if not isinstance(value, list):
        raise ModelResponseError(
            f"模型决策字段必须是字符串列表：{field_name}",
            provider=adapter.provider,
            model_name=adapter.model_name,
        )
    normalized = [str(item).strip() for item in value if str(item).strip()]
    if not normalized:
        raise ModelResponseError(
            f"模型决策字段不能为空：{field_name}",
            provider=adapter.provider,
            model_name=adapter.model_name,
        )
    return normalized


def _required_tool_calls(raw_decision: dict[str, Any], adapter: OpenAICompatibleModelAdapter) -> list[PlannedToolCall]:
    """读取并校验模型计划的工具调用。"""
    value = raw_decision.get("tool_calls")
    if not isinstance(value, list):
        raise ModelResponseError(
            "模型决策字段 tool_calls 必须是列表。",
            provider=adapter.provider,
            model_name=adapter.model_name,
        )
    tool_calls: list[PlannedToolCall] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ModelResponseError(
                f"tool_calls[{index}] 必须是对象。",
                provider=adapter.provider,
                model_name=adapter.model_name,
            )
        tool_name = str(item.get("tool_name", "")).strip()
        if tool_name not in ALLOWED_TOOL_NAMES:
            raise ModelResponseError(
                f"tool_calls[{index}] 使用了不支持的工具：{tool_name or '空'}",
                provider=adapter.provider,
                model_name=adapter.model_name,
            )
        tool_input = item.get("tool_input")
        if not isinstance(tool_input, dict):
            raise ModelResponseError(
                f"tool_calls[{index}].tool_input 必须是对象。",
                provider=adapter.provider,
                model_name=adapter.model_name,
            )
        tool_calls.append(PlannedToolCall(tool_name=tool_name, tool_input=tool_input))

    if not tool_calls:
        raise ModelResponseError(
            "模型决策至少需要包含一条 tool_call。",
            provider=adapter.provider,
            model_name=adapter.model_name,
        )
    return tool_calls
