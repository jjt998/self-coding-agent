from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from context import ContextSnapshot
from env_loader import load_dotenv


ALLOWED_TOOL_NAMES = {
    "search_text",
    "read_file",
    "read_file_range",
    "apply_patch",
    "replace_lines",
    "run_command",
    "git_diff",
}
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_text": {
        "description": "在仓库文本文件中搜索精确字符串。",
        "required": ["query"],
        "optional": ["limit"],
        "accepted_aliases": {},
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
    },
    "read_file": {
        "description": "读取仓库内单个 UTF-8 文本文件。",
        "required": ["path"],
        "optional": [],
        "accepted_aliases": {"file_path": "path"},
        "properties": {
            "path": {"type": "string", "description": "仓库内相对路径。"},
        },
    },
    "read_file_range": {
        "description": "读取仓库内 UTF-8 文本文件的闭区间行号范围；当 read_file 返回 content_mode=\"structure_summary\" 且缺少关键区域时使用。",
        "required": ["path", "start_line", "end_line"],
        "optional": [],
        "max_lines": 80,
        "accepted_aliases": {"file_path": "path"},
        "properties": {
            "path": {"type": "string", "description": "仓库内相对路径。"},
            "start_line": {"type": "integer", "description": "起始行号，1-based，包含该行。"},
            "end_line": {"type": "integer", "description": "结束行号，1-based，包含该行。"},
        },
    },
    "apply_patch": {
        "description": "对仓库内文件执行一次文本替换；old_text 为 null 时创建或替换整个文件。",
        "required": ["path", "old_text", "new_text"],
        "optional": [],
        "accepted_aliases": {"file_path": "path"},
        "properties": {
            "path": {"type": "string", "description": "仓库内相对路径。"},
            "old_text": {"type": ["string", "null"], "description": "必须逐字匹配文件内容；新建文件时可为 null。"},
            "new_text": {"type": "string"},
        },
    },
    "replace_lines": {
        "description": "按闭区间行号替换仓库内 UTF-8 文本文件内容；当同一文件连续出现 old_text_not_found 时优先使用。",
        "required": ["path", "start_line", "end_line", "new_text"],
        "optional": [],
        "accepted_aliases": {"file_path": "path"},
        "properties": {
            "path": {"type": "string", "description": "仓库内相对路径。"},
            "start_line": {"type": "integer", "description": "起始行号，1-based，包含该行。"},
            "end_line": {"type": "integer", "description": "结束行号，1-based，包含该行。"},
            "new_text": {"type": "string", "description": "替换后的文本，可以包含多行。"},
        },
    },
    "run_command": {
        "description": "在仓库根目录执行命令。",
        "required": ["command"],
        "optional": [],
        "accepted_aliases": {},
        "properties": {
            "command": {"type": ["array", "string"], "description": "推荐 argv 数组；字符串命令也可兼容。"},
        },
    },
    "git_diff": {
        "description": "读取当前运行基线到现在的文本 diff。",
        "required": [],
        "optional": ["paths"],
        "accepted_aliases": {"file_paths": "paths"},
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}},
        },
    },
}


class ModelError(Exception):
    """模型决策层异常基类，供 loop 统一收口成 model_error。"""

    def __init__(
        self,
        message: str,
        provider: str = "",
        model_name: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model_name = model_name
        self.details = _safe_model_error_details(details or {})


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
class ModelTokenUsage:
    """保存单次模型请求返回的 token usage。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    available: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，便于 trace/report/eval 复用。"""
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
    cross_round_plan: list[str] = field(default_factory=list)
    tool_calls: list[PlannedToolCall] = field(default_factory=list)
    token_usage: ModelTokenUsage = field(default_factory=ModelTokenUsage)
    raw_response_content: str = ""
    normalization_notes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成普通字典，便于 trace 和报告复用。"""
        data = asdict(self)
        data.pop("raw_response_content", None)
        data.pop("normalization_notes", None)
        data["tool_calls"] = [tool_call.to_dict() for tool_call in self.tool_calls]
        data["token_usage"] = self.token_usage.to_dict()
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
        self._last_response_content = ""
        self.api_key = os.environ.get(api_key_env, "").strip()
        if not self.api_key:
            raise ModelConfigError(
                f"缺少模型 API key 环境变量：{api_key_env}。请设置该环境变量后重试。",
                provider=provider,
                model_name=model_name,
                details=self._diagnostic_details(api_key_env=api_key_env),
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
        raw_decision, raw_response_content = self._extract_decision_json(response_payload)
        self._last_response_content = raw_response_content
        return self._parse_model_decision(
            raw_decision=raw_decision,
            task_type=task_type,
            raw_response_content=raw_response_content,
            token_usage=self._extract_token_usage(response_payload),
        )

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
                        "JSON 字段必须包含 summary、rationale、planned_actions、cross_round_plan、tool_calls。"
                        "tool_calls 里的 tool_name 只能是 search_text、read_file、apply_patch、run_command、git_diff，"
                        "tool_input 必须是对象。"
                        "工具参数必须严格遵守 user message 里的 tool_schema；"
                        "不要给工具传入 tool_schema 未声明的字段。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "runtime_feedback.previous_reflect 是上一轮工具、diff、失败工具和验证结果的事实压缩。"
                        "runtime_feedback.previous_reflect.file_context_cache 会按文件保留最近五次读取片段，供你跨轮引用已读源码。"
                        "runtime_feedback.previous_cross_round_plan 是上一轮模型留下的跨轮安排。"
                        "harness 只负责保真压缩事实，不替你判断上一轮是否有效；"
                        "你需要在 rationale 中自行解释这些事实，并据此重规划当前轮 tool_calls。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "请严格遵守 user message 中的 decision_schema："
                        "planned_actions 只写本轮 tool_calls 实际会执行的动作；"
                        "跨轮安排和下一轮意图写入 cross_round_plan；"
                        "tool_calls 是唯一执行源。"
                        "在 Windows CLI 任务中，默认让 ASCII stdout/stderr 使用纯 ASCII 文本，"
                        "除非任务明确要求 Unicode；避免 emoji、全角符号和非必要中文输出。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "文件上下文规则：当 read_file 返回 content_mode=\"full\" 时，说明文件足够小且内容已完整可见，不要重复读取同一文件；"
                        "当 read_file 返回 content_mode=\"structure_summary\" 时，说明文件过大，只能看到结构摘要与行号索引，若缺少关键区域，请使用 read_file_range(path,start_line,end_line) 精确补齐；read_file_range 每次只能读取 1 到 40 行，不要用它读取整个文件。"
                        "编辑规则：如果同一文件连续多次出现 old_text_not_found，尤其接近 3 次时，优先基于最近源码行号使用 replace_lines，"
                        "不要继续猜测大段 apply_patch.old_text。"
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
                            "decision_schema": {
                                "summary": "字符串：本轮决策摘要。",
                                "rationale": "字符串：解释为什么本轮这样安排。",
                                "planned_actions": [
                                    "字符串列表：只能描述本轮 tool_calls 实际会执行的动作。"
                                ],
                                "cross_round_plan": [
                                    "字符串列表：跨轮安排、后续轮次意图、暂不执行的计划。"
                                ],
                                "tool_calls": "数组：唯一会被 act 阶段实际执行的工具调用。",
                            },
                            "tool_schema": TOOL_SCHEMAS,
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
                    details=self._diagnostic_details(
                        source="SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
                        field_path="fake_model_response",
                        response_excerpt=_truncate_text(fake_response),
                    ),
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
                f"模型请求返回 HTTP {error.code}。请检查 base_url、模型名、API key 权限和服务状态。",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(
                    status_code=error.code,
                    response_excerpt=_truncate_text(error_body),
                ),
            ) from error
        except URLError as error:
            raise ModelRequestError(
                f"模型请求失败：{error.reason}",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(
                    request_error_type="URLError",
                    request_error_reason=_truncate_text(str(error.reason)),
                ),
            ) from error
        except TimeoutError as error:
            raise ModelRequestError(
                f"模型请求超时，当前 timeout_seconds={self.timeout_seconds}。",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(request_error_type="TimeoutError"),
            ) from error
        except OSError as error:
            raise ModelRequestError(
                f"模型请求失败：{error}",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(
                    request_error_type=type(error).__name__,
                    request_error_reason=_truncate_text(str(error)),
                ),
            ) from error

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                f"模型 HTTP 响应不是合法 JSON：{error}",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(
                    field_path="http_response",
                    response_excerpt=_truncate_text(response_text),
                ),
            ) from error

    def _extract_decision_json(self, response_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """从 OpenAI 兼容响应中取出 message.content 并解析为决策 JSON。"""
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelResponseError(
                "模型响应缺少 choices[0].message.content。",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(field_path="choices[0].message.content"),
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError(
                "模型响应 content 为空或不是字符串。",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(field_path="choices[0].message.content"),
            )

        try:
            raw_decision = json.loads(content)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                f"模型决策 content 不是合法 JSON：{error}",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(
                    field_path="choices[0].message.content",
                    response_excerpt=_truncate_text(content),
                ),
            ) from error
        if not isinstance(raw_decision, dict):
            raise ModelResponseError(
                "模型决策 JSON 必须是对象。",
                provider=self.provider,
                model_name=self.model_name,
                details=self._diagnostic_details(field_path="choices[0].message.content"),
            )
        return raw_decision, content

    def _extract_token_usage(self, response_payload: dict[str, Any]) -> ModelTokenUsage:
        """从 provider 响应中提取 usage；缺失时保持 unavailable。"""
        usage = response_payload.get("usage")
        if not isinstance(usage, dict):
            return ModelTokenUsage()

        prompt_tokens = _normalize_usage_int(usage.get("prompt_tokens"))
        completion_tokens = _normalize_usage_int(usage.get("completion_tokens"))
        total_tokens = _normalize_usage_int(usage.get("total_tokens"))
        available = all(value is not None for value in [prompt_tokens, completion_tokens, total_tokens])
        if not available:
            return ModelTokenUsage()

        return ModelTokenUsage(
            prompt_tokens=prompt_tokens or 0,
            completion_tokens=completion_tokens or 0,
            total_tokens=total_tokens or 0,
            available=True,
        )

    def _diagnostic_details(self, **extra: Any) -> dict[str, Any]:
        """生成不会泄露 API key 的模型排障信息。"""
        details = {
            "provider": self.provider,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
        }
        details.update(extra)
        if (
            self._last_response_content
            and "response_excerpt" not in details
            and str(details.get("field_path", "")).strip()
        ):
            details["response_excerpt"] = _truncate_text(self._last_response_content)
        return _safe_model_error_details(details)

    def _parse_model_decision(
        self,
        raw_decision: dict[str, Any],
        task_type: str,
        raw_response_content: str = "",
        token_usage: ModelTokenUsage | None = None,
    ) -> ModelDecision:
        """校验模型决策字段，并转换成内部数据结构。"""
        summary = _required_string(raw_decision, "summary", self)
        rationale = _required_string(raw_decision, "rationale", self)
        tool_calls = _required_tool_calls(raw_decision, self)
        planned_actions, normalization_notes = _normalize_planned_actions(
            raw_decision=raw_decision,
            tool_calls=tool_calls,
        )
        cross_round_plan, cross_round_notes = _normalize_optional_string_list(
            raw_decision=raw_decision,
            field_name="cross_round_plan",
        )
        normalization_notes.extend(cross_round_notes)
        return ModelDecision(
            provider=self.provider,
            model_name=self.model_name,
            task_type=task_type,
            summary=summary,
            rationale=rationale,
            planned_actions=planned_actions,
            cross_round_plan=cross_round_plan,
            tool_calls=tool_calls,
            token_usage=token_usage or ModelTokenUsage(),
            raw_response_content=raw_response_content,
            normalization_notes=normalization_notes,
        )


def build_model_adapter(config_data: dict[str, Any]) -> ModelAdapter:
    """根据配置构建真实模型适配器；当前只接受 OpenAI 兼容 provider。"""
    load_dotenv()
    model_config = config_data.get("model")
    if not isinstance(model_config, dict):
        raise ModelConfigError("缺少 model 配置。", details={"field_path": "model"})

    provider = str(model_config.get("provider", "")).strip()
    if provider != "openai_compatible":
        raise ModelConfigError(
            f"不支持的 model.provider：{provider or '空'}",
            provider=provider,
            details={"field_path": "model.provider", "provider": provider},
        )

    model_name = str(model_config.get("name", "")).strip()
    if not model_name:
        raise ModelConfigError(
            "缺少 model.name。",
            provider=provider,
            details={"field_path": "model.name", "provider": provider},
        )

    base_url = str(model_config.get("base_url", "https://api.deepseek.com")).strip()
    if not base_url:
        base_url = "https://api.deepseek.com"
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ModelConfigError(
            "model.base_url 必须以 http:// 或 https:// 开头。",
            provider=provider,
            model_name=model_name,
            details={
                "field_path": "model.base_url",
                "provider": provider,
                "model_name": model_name,
                "base_url": base_url,
            },
        )
    api_key_env = str(model_config.get("api_key_env", "DEEPSEEK_API_KEY")).strip() or "DEEPSEEK_API_KEY"
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


def _safe_model_error_details(details: dict[str, Any]) -> dict[str, Any]:
    """清洗模型错误 details，避免把密钥或超长响应写进 trace。"""
    safe_details: dict[str, Any] = {}
    for key, value in details.items():
        key_text = str(key)
        if "key" in key_text.lower() and key_text != "api_key_env":
            continue
        if isinstance(value, str):
            safe_details[key_text] = _truncate_text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe_details[key_text] = value
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) or item is None
            for item in value
        ):
            safe_details[key_text] = [
                _truncate_text(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            safe_details[key_text] = _truncate_text(str(value))
    return safe_details


def _truncate_text(value: str, limit: int = 300) -> str:
    """截断模型错误摘要，避免把大段响应写入 trace。"""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _normalize_usage_int(raw_value: Any) -> int | None:
    """把 provider usage 字段收敛成非负整数。"""
    if isinstance(raw_value, bool) or raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = int(raw_value.strip())
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _required_string(raw_decision: dict[str, Any], field_name: str, adapter: OpenAICompatibleModelAdapter) -> str:
    """读取必填字符串字段。"""
    value = raw_decision.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(
            f"模型决策缺少必填字符串字段：{field_name}",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(field_path=field_name),
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
            details=adapter._diagnostic_details(field_path=field_name),
        )
    normalized = [str(item).strip() for item in value if str(item).strip()]
    if not normalized:
        raise ModelResponseError(
            f"模型决策字段不能为空：{field_name}",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(field_path=field_name),
        )
    return normalized


def _validate_tool_input_types(
    tool_name: str,
    tool_input: dict[str, Any],
    adapter: OpenAICompatibleModelAdapter,
    tool_call_index: int,
) -> None:
    """按工具 schema 校验入参类型，避免非法值进入工具执行层。"""
    properties = TOOL_SCHEMAS[tool_name].get("properties", {})
    if not isinstance(properties, dict):
        return
    for field_name, value in tool_input.items():
        property_schema = properties.get(field_name, {})
        if not isinstance(property_schema, dict):
            continue
        expected_type = property_schema.get("type")
        if _matches_json_schema_type(value=value, expected_type=expected_type, property_schema=property_schema):
            continue
        raise ModelResponseError(
            (
                f"tool_calls[{tool_call_index}].tool_input.{field_name} 类型不符合工具 schema："
                f"expected={_format_expected_type(expected_type)} actual={type(value).__name__}。"
            ),
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(
                field_path=f"tool_calls[{tool_call_index}].tool_input.{field_name}",
                tool_call_index=tool_call_index,
                tool_name=tool_name,
                expected_type=_format_expected_type(expected_type),
                actual_type=type(value).__name__,
            ),
        )


def _matches_json_schema_type(value: Any, expected_type: Any, property_schema: dict[str, Any]) -> bool:
    """支持当前工具 schema 需要的最小 JSON 类型集合。"""
    expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
    for item_type in expected_types:
        if item_type == "string" and isinstance(value, str):
            return True
        if item_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if item_type == "null" and value is None:
            return True
        if item_type == "array" and isinstance(value, list):
            item_schema = property_schema.get("items", {})
            if not isinstance(item_schema, dict) or "type" not in item_schema:
                return True
            return all(
                _matches_json_schema_type(
                    value=array_item,
                    expected_type=item_schema.get("type"),
                    property_schema=item_schema,
                )
                for array_item in value
            )
    return False


def _format_expected_type(expected_type: Any) -> str:
    """把 schema 类型整理成稳定错误摘要。"""
    if isinstance(expected_type, list):
        return "|".join(str(item) for item in expected_type)
    return str(expected_type)


def _normalize_planned_actions(
    raw_decision: dict[str, Any],
    tool_calls: list[PlannedToolCall],
) -> tuple[list[str], list[dict[str, Any]]]:
    """把非执行字段 planned_actions 宽容归一化，避免展示字段导致 run 中断。"""
    value = raw_decision.get("planned_actions")
    notes: list[dict[str, Any]] = []
    if isinstance(value, list):
        normalized: list[str] = []
        changed = False
        for item in value:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = _extract_action_text_from_dict(item)
                changed = True
            else:
                text = str(item).strip()
                changed = True
            if text:
                normalized.append(text)
        if normalized:
            if changed:
                notes.append(
                    {
                        "field_path": "planned_actions",
                        "reason": "coerced_list_items_to_strings",
                    }
                )
            return normalized, notes
        notes.append({"field_path": "planned_actions", "reason": "empty_list_fallback_to_tool_calls"})
        return _planned_actions_from_tool_calls(tool_calls), notes

    if isinstance(value, str) and value.strip():
        notes.append({"field_path": "planned_actions", "reason": "coerced_string_to_single_item_list"})
        return [value.strip()], notes

    notes.append(
        {
            "field_path": "planned_actions",
            "reason": "missing_or_unusable_fallback_to_tool_calls",
            "raw_type": type(value).__name__,
        }
    )
    return _planned_actions_from_tool_calls(tool_calls), notes


def _extract_action_text_from_dict(item: dict[str, Any]) -> str:
    """从模型常见对象形式里提取可读 action 文本。"""
    for key in ["step", "action", "description", "text", "name"]:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(item, ensure_ascii=False)


def _normalize_optional_string_list(
    raw_decision: dict[str, Any],
    field_name: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """把可选的字符串列表字段宽容归一化，缺失时保持空列表兼容旧模型。"""
    value = raw_decision.get(field_name)
    if value is None:
        return [], []
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if normalized:
            return normalized, []
        return [], [{"field_path": field_name, "reason": "empty_list_normalized_to_empty"}]
    if isinstance(value, str) and value.strip():
        return [value.strip()], [{"field_path": field_name, "reason": "coerced_string_to_single_item_list"}]
    return [], [
        {
            "field_path": field_name,
            "reason": "unusable_value_normalized_to_empty",
            "raw_type": type(value).__name__,
        }
    ]


def _planned_actions_from_tool_calls(tool_calls: list[PlannedToolCall]) -> list[str]:
    """当 planned_actions 不可用时，从真实执行工具计划派生可读说明。"""
    return [f"执行工具：{tool_call.tool_name}" for tool_call in tool_calls]


def _required_tool_calls(raw_decision: dict[str, Any], adapter: OpenAICompatibleModelAdapter) -> list[PlannedToolCall]:
    """读取并校验模型计划的工具调用。"""
    value = raw_decision.get("tool_calls")
    if not isinstance(value, list):
        raise ModelResponseError(
            "模型决策字段 tool_calls 必须是列表。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(field_path="tool_calls"),
        )
    tool_calls: list[PlannedToolCall] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ModelResponseError(
                f"tool_calls[{index}] 必须是对象。",
                provider=adapter.provider,
                model_name=adapter.model_name,
                details=adapter._diagnostic_details(field_path=f"tool_calls[{index}]", tool_call_index=index),
            )
        tool_name = str(item.get("tool_name", "")).strip()
        if tool_name not in ALLOWED_TOOL_NAMES:
            raise ModelResponseError(
                f"tool_calls[{index}] 使用了不支持的工具：{tool_name or '空'}",
                provider=adapter.provider,
                model_name=adapter.model_name,
                details=adapter._diagnostic_details(
                    field_path=f"tool_calls[{index}].tool_name",
                    tool_call_index=index,
                    tool_name=tool_name or "空",
                ),
            )
        tool_input = item.get("tool_input")
        if not isinstance(tool_input, dict):
            raise ModelResponseError(
                f"tool_calls[{index}].tool_input 必须是对象。",
                provider=adapter.provider,
                model_name=adapter.model_name,
                details=adapter._diagnostic_details(
                    field_path=f"tool_calls[{index}].tool_input",
                    tool_call_index=index,
                    tool_name=tool_name,
                ),
            )
        tool_input = _normalize_and_validate_tool_input(
            tool_name=tool_name,
            tool_input=tool_input,
            adapter=adapter,
            tool_call_index=index,
        )
        tool_calls.append(PlannedToolCall(tool_name=tool_name, tool_input=tool_input))

    if not tool_calls:
        raise ModelResponseError(
            "模型决策至少需要包含一条 tool_call。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(field_path="tool_calls"),
        )
    return tool_calls


def _normalize_and_validate_tool_input(
    tool_name: str,
    tool_input: dict[str, Any],
    adapter: OpenAICompatibleModelAdapter,
    tool_call_index: int,
) -> dict[str, Any]:
    """按结构化工具 schema 归一化别名并拒绝未声明字段。"""
    schema = TOOL_SCHEMAS[tool_name]
    aliases = schema.get("accepted_aliases", {})
    normalized = dict(tool_input)
    if isinstance(aliases, dict):
        for alias, canonical in aliases.items():
            if alias in normalized and canonical not in normalized:
                normalized[canonical] = normalized.pop(alias)

    allowed_fields = set(schema.get("required", [])) | set(schema.get("optional", []))
    extra_fields = sorted(field for field in normalized if field not in allowed_fields)
    if extra_fields:
        raise ModelResponseError(
            f"tool_calls[{tool_call_index}].tool_input 包含未声明字段：{', '.join(extra_fields)}。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(
                field_path=f"tool_calls[{tool_call_index}].tool_input",
                tool_call_index=tool_call_index,
                tool_name=tool_name,
                invalid_fields=extra_fields,
                allowed_fields=sorted(allowed_fields),
            ),
        )

    missing_fields = [
        field_name
        for field_name in schema.get("required", [])
        if field_name not in normalized
    ]
    if missing_fields:
        raise ModelResponseError(
            f"tool_calls[{tool_call_index}].tool_input 缺少必填字段：{', '.join(missing_fields)}。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(
                field_path=f"tool_calls[{tool_call_index}].tool_input",
                tool_call_index=tool_call_index,
                tool_name=tool_name,
                missing_fields=missing_fields,
                allowed_fields=sorted(allowed_fields),
            ),
        )
    _validate_tool_input_types(
        tool_name=tool_name,
        tool_input=normalized,
        adapter=adapter,
        tool_call_index=tool_call_index,
    )
    return normalized
