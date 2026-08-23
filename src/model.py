from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from context import ContextSnapshot, InitialGuide
from env_loader import load_dotenv


ALLOWED_TOOL_NAMES = {
    "search_text",
    "read_file",
    "read_file_structure_summary",
    "read_file_range",
    "apply_patch",
    "replace_lines",
    "run_command",
    "git_diff",
}
WORKING_MEMORY_FIELDS = (
    "confirmed_facts",
    "invalidated_beliefs",
    "completed_actions",
    "next_risks",
)
WorkingMemoryValue = str | list[str]
WorkingMemoryDocument = dict[str, WorkingMemoryValue]
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
    "read_file_structure_summary": {
        "description": "只读取仓库内 UTF-8 文本文件的结构摘要，适合先定位函数、类、标题和起始行号。",
        "required": ["path"],
        "optional": [],
        "accepted_aliases": {"file_path": "path"},
        "properties": {
            "path": {"type": "string", "description": "仓库内相对路径。"},
        },
    },
    "read_file_range": {
        "description": "读取仓库内 UTF-8 文本文件的闭区间行号范围；当 read_file 或 read_file_structure_summary 只给出结构摘要且缺少关键区域时使用。",
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


def build_empty_working_memory() -> WorkingMemoryDocument:
    """构造一份空的 working_memory，统一四个固定字段。"""
    return {field_name: [] for field_name in WORKING_MEMORY_FIELDS}


@dataclass(slots=True)
class ModelDecision:
    """保存一次任务级决策结果，包括本轮动作说明和模型维护的工作记忆。"""

    provider: str
    model_name: str
    task_type: str
    summary: str
    rationale: str
    planned_actions: list[str] = field(default_factory=list)
    working_memory: WorkingMemoryDocument = field(default_factory=build_empty_working_memory)
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
        data["working_memory"] = _clone_working_memory(self.working_memory)
        return data


class ModelAdapter:
    """抽象一次任务级决策接口，具体实现负责产出结构化工具计划。"""

    provider: str
    model_name: str

    def decide(
        self,
        task: str,
        task_type: str,
        initial_guide: InitialGuide | None = None,
        context_snapshot: ContextSnapshot | None = None,
        config_data: dict[str, Any] | None = None,
        **_unused_context: Any,
    ) -> ModelDecision:
        """根据任务、上下文和配置，产出一次结构化决策结果。"""
        raise NotImplementedError

    def get_last_request_payload(self) -> dict[str, Any]:
        """返回最近一次真实发给模型的请求快照；默认没有可用数据。"""
        return {}

    def complete_json(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Return one generic JSON object from the model without ModelDecision parsing."""
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
        self._last_request_payload: dict[str, Any] = {}
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
        initial_guide: InitialGuide | None = None,
        context_snapshot: ContextSnapshot | None = None,
        config_data: dict[str, Any] | None = None,
        **_unused_context: Any,
    ) -> ModelDecision:
        """调用模型并把返回内容解析成稳定的 ModelDecision。"""
        request_payload = self._last_request_payload or self.prepare_request_payload(
            task=task,
            task_type=task_type,
            initial_guide=initial_guide,
            context_snapshot=context_snapshot,
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

    def prepare_request_payload(
        self,
        task: str,
        task_type: str,
        initial_guide: InitialGuide | None = None,
        context_snapshot: ContextSnapshot | None = None,
        **_unused_context: Any,
    ) -> dict[str, Any]:
        """构造并缓存真实请求 payload，供 trace 和后续 decide 复用。"""
        self._last_request_payload = self._build_request_payload(
            task=task,
            task_type=task_type,
            initial_guide=initial_guide,
            context_snapshot=context_snapshot,
        )
        return dict(self._last_request_payload)

    def get_last_request_payload(self) -> dict[str, Any]:
        """返回最近一次准备好的请求快照。"""
        return dict(self._last_request_payload)

    def complete_json(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Call the model for a generic JSON object, used by non-decision tasks."""
        payload = dict(request_payload)
        payload["model"] = self.model_name
        self._last_request_payload = payload
        response_payload = self._request_chat_completion(
            payload,
            fake_response_env="SELF_CODING_AGENT_FAKE_SUMMARY_POLISH_RESPONSE",
        )
        raw_object, raw_response_content = self._extract_json_content(response_payload)
        self._last_response_content = raw_response_content
        return raw_object

    def _request_chat_completion(
        self,
        request_payload: dict[str, Any],
        fake_response_env: str = "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE",
    ) -> dict[str, Any]:
        """执行 HTTP 请求；测试可通过环境变量提供假响应但仍必须配置 API key。"""
        fake_response = os.environ.get(fake_response_env, "").strip()
        if not fake_response and fake_response_env != "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE":
            fake_response = os.environ.get("SELF_CODING_AGENT_FAKE_MODEL_RESPONSE", "").strip()
            fake_response_env = "SELF_CODING_AGENT_FAKE_MODEL_RESPONSE"
        if fake_response:
            try:
                return json.loads(fake_response)
            except json.JSONDecodeError as error:
                raise ModelResponseError(
                    f"测试模型响应不是合法 JSON：{error}",
                    provider=self.provider,
                    model_name=self.model_name,
                    details=self._diagnostic_details(
                        source=fake_response_env,
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
        return self._extract_json_content(response_payload)

    def _extract_json_content(self, response_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Extract a JSON object from choices[0].message.content."""
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
                "模型返回 JSON 必须是对象。",
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

    def _build_request_payload(
        self,
        task: str,
        task_type: str,
        initial_guide: InitialGuide | None,
        context_snapshot: ContextSnapshot | None,
    ) -> dict[str, Any]:
        """构造模型请求，只要求返回一份结构化 JSON 决策。"""
        initial_guide_payload = initial_guide.to_dict() if initial_guide else {}
        context_payload = context_snapshot.to_dict() if context_snapshot else {}
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是本地代码任务 harness 的决策层。"
                        "必须只返回 JSON 对象，不要 Markdown。"
                        "JSON 字段必须包含 summary、rationale、planned_actions、working_memory、tool_calls。"
                        "tool_calls 里的 tool_name 只能是 search_text、read_file、read_file_structure_summary、read_file_range、apply_patch、replace_lines、run_command、git_diff，"
                        "tool_input 必须是对象。"
                        "工具参数必须严格遵守 user message 里的 tool_schema，"
                        "不要给工具传入 tool_schema 未声明的字段。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "initial_guide 是首轮任务、仓库召回和长期记忆指导；"
                        "它只提供候选文件结构和推荐理由，不直接替你决定必须读取哪些正文。"
                        "context_snapshot 是当前 plan 轮的事实快照。"
                        "context_snapshot.working_memory 的主体是上一轮模型返回的四字段工作记忆；"
                        "其中 last_rational 是 harness 从上一轮 rationale 额外注入的连续性线索，用来帮助你接着之前的思路推理。"
                        "context_snapshot.fresh_context.file_snippets 是当前仍可信的文件片段，content 字段就是工具读取到的内容。"
                        "context_snapshot.fresh_context.diffs 和 command_results 会标注 from_iteration，"
                        "请根据当前 iteration 判断它们是否仍足够新。"
                        "context_snapshot.stale_context 只描述当前仍 stale 的文件；"
                        "如果某文件不在 stale_file_paths 中，就不要把它写成当前 stale。"
                        "context_snapshot.recent_facts 提供最近工具结果、失败工具和 signals。"
                        "你需要在 rationale 中自行解释这些事实，并据此避免重复兜圈。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "请严格遵守 user message 中的 decision_schema："
                        "planned_actions 只写本轮 tool_calls 实际会执行的动作；"
                        "working_memory 必须是完整对象，并且固定包含 confirmed_facts、invalidated_beliefs、completed_actions、next_risks 四个字段；"
                        "每个字段可以写成一个字符串，也可以写成字符串列表；"
                        "下一轮会在 context_snapshot.working_memory 中看到你这一轮返回的四字段对象，以及 harness 额外注入的 last_rational；"
                        "如果上一轮判断被推翻，必须在本轮主动改写对应字段，不要依赖 harness 帮你 merge、修正或补写；"
                        "凡是被当前轮代码读取结果、命令输出或 diff 直接否定的旧怀疑，必须写入 invalidated_beliefs。"
                        "working_memory 不再保留专门的 open_questions 字段，避免把未确认问题越积越多，驱动模型继续发散。"
                        "tool_calls 是唯一执行源。"
                        "由 harness 根据本轮 tool_calls 是否为空来决定是否继续求解。"
                        "在 Windows CLI 任务中，默认要求 ASCII stdout/stderr；"
                        "除非任务明确要求 Unicode，否则避免 emoji、全角符号和非必要中文输出。"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "文件上下文规则：当 read_file 返回 content_mode=\"full\" 时，说明文件足够小且内容已完整可见，不要重复读取同一文件；"
                        "当你只想先看大文件结构、函数名、类名、标题和起始行号时，优先使用 read_file_structure_summary(path)；"
                        "当 read_file 或 read_file_structure_summary 返回 content_mode=\"structure_summary\" 时，说明当前只拿到了结构摘要与行号索引，若缺少关键区域，请使用 read_file_range(path,start_line,end_line) 精确补齐；read_file_range 每次只能读取 1 到 80 行，不要用它读取整个文件。"
                        "如果某个文件在上一轮编辑后被标记为 stale，不要继续依赖编辑前读取到的旧片段；"
                        "若只需要重新定位结构，先调用 read_file_structure_summary，再按行号调用 read_file_range。"
                        "如果 context_snapshot.stale_context 已给出 recommended_sequence，默认按这个顺序执行；"
                        "也就是说，编辑后的重读优先走 read_file_structure_summary -> read_file_range，不要一上来就反复读取同一小段旧附近行号。"
                        "如果 context_snapshot.fresh_context.file_snippets 已经包含最新可信片段，优先直接使用这些片段；"
                        "除非片段范围仍然不够，否则不要仅因为文件历史上 stale 过就重复读取同一函数。"
                        "编辑规则：默认先使用 apply_patch，不要一开始就把 replace_lines 当成主编辑方式。"
                        "只有在 apply_patch 连续失败、old_text_not_found、文件存在换行/缩进/不可见字符等问题导致精确文本难以匹配，并且你已经重新读取目标范围并确认最新行号时，才使用 replace_lines。"
                        "编辑规则：如果同一文件连续多次出现 old_text_not_found，尤其接近 3 次时，优先基于最近源码行号使用 replace_lines；"
                        "不要继续猜测大段 apply_patch.old_text。"
                        "bug_fix 收口规则：如果当前 diff 已经命中任务目标修改点，并且针对任务描述的核心验证命令已经符合预期，优先进入结束判断；"
                        "不要在这种情况下继续扩展读取外围函数、补做低价值旁路确认或重新打开已经被命令验证过的主假设。"
                        "对于 bug_fix，核心命令优先指任务描述、verify_commands、context_snapshot.recent_facts.recent_tool_results 或当前轮计划里直接针对缺陷现象的命令；"
                        "如果这些核心命令已经证明主缺陷修复成立，默认下一轮应减少读取并准备让 tool_calls 为空。"
                        "请注意："
                        "任务描述描述的是待修复现象，不保证与当前轮已修改后的文件内容一致。"
                        "当任务描述、当前代码、recent facts 和 git diff 看起来冲突时，优先相信当前轮可验证的运行时证据，而不是反复把初始任务描述当成当前代码事实。"
                        "如果关键目标函数已经处于 fresh 状态，并且你已经直接读到其当前实现，"
                        "不要仅因为任务描述与当前代码冲突，就立刻扩展读取外围 helper；"
                        "先把这个冲突写入 working_memory 的 invalidated_beliefs 或直接在 rationale 中说明，"
                        "并优先运行核心命令校验当前代码行为。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task,
                            "task_type": task_type,
                            "initial_guide": initial_guide_payload,
                            "context_snapshot": context_payload,
                            "decision_schema": {
                                "summary": "字符串：本轮决策摘要。",
                                "rationale": "字符串：解释为什么本轮这样安排。",
                                "planned_actions": [
                                    "字符串列表：只能描述本轮 tool_calls 实际会执行的动作。"
                                ],
                                "working_memory": {
                                    "confirmed_facts": "字符串或字符串列表：当前已确认的事实。",
                                    "invalidated_beliefs": "字符串或字符串列表：本轮已推翻的旧怀疑、旧判断。",
                                    "completed_actions": "字符串或字符串列表：到当前轮为止已经完成的动作。",
                                    "next_risks": "字符串或字符串列表：若现在结束或继续，最需要注意的风险。",
                                },
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
        working_memory, working_memory_notes = _normalize_working_memory(
            raw_decision=raw_decision,
            adapter=self,
        )
        normalization_notes.extend(working_memory_notes)
        return ModelDecision(
            provider=self.provider,
            model_name=self.model_name,
            task_type=task_type,
            summary=summary,
            rationale=rationale,
            planned_actions=planned_actions,
            working_memory=working_memory,
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


def _clone_working_memory(working_memory: WorkingMemoryDocument) -> WorkingMemoryDocument:
    """复制 working_memory，避免 trace/report 后续误改原对象。"""
    cloned = build_empty_working_memory()
    for field_name in WORKING_MEMORY_FIELDS:
        field_value = working_memory.get(field_name, [])
        if isinstance(field_value, list):
            cloned[field_name] = list(field_value)
        elif isinstance(field_value, str):
            cloned[field_name] = field_value
        else:
            cloned[field_name] = []
    return cloned


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


def _normalize_working_memory(
    raw_decision: dict[str, Any],
    adapter: OpenAICompatibleModelAdapter,
) -> tuple[WorkingMemoryDocument, list[dict[str, Any]]]:
    """校验并做最小归一化，确保模型每轮都返回完整 working_memory。"""
    value = raw_decision.get("working_memory")
    if not isinstance(value, dict):
        raise ModelResponseError(
            "模型决策字段 working_memory 必须是对象。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(field_path="working_memory"),
        )

    missing_fields = [field_name for field_name in WORKING_MEMORY_FIELDS if field_name not in value]
    if missing_fields:
        raise ModelResponseError(
            f"working_memory 缺少必填字段：{', '.join(missing_fields)}。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(
                field_path="working_memory",
                missing_fields=missing_fields,
            ),
        )

    normalized = build_empty_working_memory()
    normalization_notes: list[dict[str, Any]] = []
    for field_name in WORKING_MEMORY_FIELDS:
        field_value = value.get(field_name)
        if isinstance(field_value, str):
            normalized[field_name] = field_value
            continue
        if isinstance(field_value, list):
            cleaned_items: list[str] = []
            dropped_empty = False
            for item in field_value:
                if not isinstance(item, str):
                    raise ModelResponseError(
                        f"working_memory.{field_name} 数组内必须全部是字符串。",
                        provider=adapter.provider,
                        model_name=adapter.model_name,
                        details=adapter._diagnostic_details(
                            field_path=f"working_memory.{field_name}",
                            invalid_item_type=type(item).__name__,
                        ),
                    )
                trimmed_item = item.strip()
                if not trimmed_item:
                    dropped_empty = True
                    continue
                cleaned_items.append(trimmed_item)
            normalized[field_name] = cleaned_items
            if dropped_empty:
                normalization_notes.append(
                    {
                        "field_path": f"working_memory.{field_name}",
                        "reason": "dropped_empty_string_items",
                    }
                )
            continue
        raise ModelResponseError(
            f"working_memory.{field_name} 必须是字符串或字符串列表。",
            provider=adapter.provider,
            model_name=adapter.model_name,
            details=adapter._diagnostic_details(
                field_path=f"working_memory.{field_name}",
                raw_type=type(field_value).__name__,
            ),
        )
    return normalized, normalization_notes


def _planned_actions_from_tool_calls(tool_calls: list[PlannedToolCall]) -> list[str]:
    """当 planned_actions 不可用时，从真实执行工具计划派生可读说明。"""
    return [f"执行工具：{tool_call.tool_name}" for tool_call in tool_calls]


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


def _required_tool_calls(raw_decision: dict[str, Any], adapter: OpenAICompatibleModelAdapter) -> list[PlannedToolCall]:
    """读取并校验模型计划的工具调用，允许空列表作为收口信号。"""
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
        tool_calls.append(
            PlannedToolCall(
                tool_name=tool_name,
                tool_input=_normalize_and_validate_tool_input(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    adapter=adapter,
                    tool_call_index=index,
                ),
            )
        )
    return tool_calls


def _required_bool(
    raw_decision: dict[str, Any],
    field_name: str,
    adapter: OpenAICompatibleModelAdapter,
) -> bool:
    """读取并校验布尔字段；缺失时兼容回落为 false。"""
    value = raw_decision.get(field_name)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    raise ModelResponseError(
        f"模型决策字段 {field_name} 必须是布尔值。",
        provider=adapter.provider,
        model_name=adapter.model_name,
        details=adapter._diagnostic_details(
            field_path=field_name,
            raw_type=type(value).__name__,
        ),
    )
