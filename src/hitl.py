from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import fnmatch
import json
from pathlib import Path
from typing import Any


HUMAN_INPUT_REQUEST_FILE = "human_input_request.json"
HUMAN_INPUT_RESPONSE_FILE = "human_response.json"
PENDING_TOOL_CALL_FILE = "pending_tool_call.json"
PENDING_RUNTIME_STATE_FILE = "pending_runtime_state.pkl"
TOOL_BASELINE_FILE = "tool_baseline_snapshot.json"


def utc_now_iso() -> str:
    """返回写入 HITL 文件的 UTC 时间，保证 trace 和请求文件能按时间对齐。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ToolPermissionDecision:
    """保存一次工具权限检查结果，告诉 act 阶段是执行、拒绝还是暂停等待人审。"""

    action: str
    matched_rule_id: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """导出普通字典，方便写入 trace 和人工请求文件。"""
        return asdict(self)


@dataclass(slots=True)
class HumanInputRequest:
    """描述一次等待人工处理的单个工具调用。"""

    request_id: str
    run_id: str
    created_at: str
    stage: str
    reason: str
    message: str
    tool_call_id: str
    tool_index: int
    tool_total: int
    tool: str
    tool_input_preview: str
    full_tool_input_path: str
    policy: dict[str, Any]
    allowed_responses: list[str] = field(default_factory=lambda: ["approve", "reject", "add_instruction"])
    context_hint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """导出稳定 schema，供 headless 模式和 eval 读取。"""
        return asdict(self)


@dataclass(slots=True)
class HumanInputResponse:
    """保存用户或外部系统对某个 HITL 请求的处理结果。"""

    request_id: str
    tool_call_id: str
    action: str
    instruction: str = ""
    responded_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """导出普通字典，方便写入 trace 和 context_snapshot。"""
        return asdict(self)


def build_tool_call_id(iteration: int, tool_index: int) -> str:
    """用轮次和工具序号生成稳定 ID，让人工响应能精确对应单个工具。"""
    return f"toolcall_i{iteration:03d}_{tool_index + 1:03d}"


def build_human_request_id(iteration: int, tool_index: int) -> str:
    """生成可读的人工请求 ID，避免用户在多次暂停时分不清对象。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"hir_{timestamp}_i{iteration:03d}_{tool_index + 1:03d}"


def load_human_response(path: Path) -> HumanInputResponse:
    """读取并校验 headless 模式传入的人工响应文件。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"人工响应文件不存在：{path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"人工响应文件不是合法 JSON：{error}") from error
    if not isinstance(payload, dict):
        raise ValueError("人工响应文件根节点必须是对象。")
    request_id = str(payload.get("request_id", "")).strip()
    tool_call_id = str(payload.get("tool_call_id", "")).strip()
    action = str(payload.get("action", "")).strip()
    instruction = str(payload.get("instruction", "")).strip()
    responded_at = str(payload.get("responded_at", "")).strip() or utc_now_iso()
    if not request_id:
        raise ValueError("人工响应缺少 request_id。")
    if not tool_call_id:
        raise ValueError("人工响应缺少 tool_call_id。")
    if action not in {"approve", "reject", "add_instruction"}:
        raise ValueError("人工响应 action 只能是 approve、reject 或 add_instruction。")
    if action == "add_instruction" and not instruction:
        raise ValueError("人工响应 action=add_instruction 时必须提供 instruction。")
    return HumanInputResponse(
        request_id=request_id,
        tool_call_id=tool_call_id,
        action=action,
        instruction=instruction,
        responded_at=responded_at,
    )


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """按项目统一 UTF-8 口径写 JSON 文件，避免中文提示在 Windows 上乱码。"""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json_file(path: Path) -> dict[str, Any]:
    """读取对象型 JSON 文件；格式错误时给出中文异常。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"文件不存在：{path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 文件格式错误：{path}，{error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件根节点必须是对象：{path}")
    return payload


class ToolPermissionEngine:
    """按静态规则表判断工具是否可执行，第一版只做简单字段匹配。"""

    def __init__(self, config_data: dict[str, Any], interaction_mode: str = "tasks") -> None:
        """读取配置中的权限表；headless_hitl 才启用 require_approval 暂停能力。"""
        policy_config = config_data.get("tool_permissions", {})
        if not isinstance(policy_config, dict):
            policy_config = {}
        self.enabled = bool(policy_config.get("enabled", False))
        self.default_action = str(policy_config.get("default_action", "allow")).strip() or "allow"
        self.rules = [
            item
            for item in policy_config.get("rules", [])
            if isinstance(item, dict)
        ]
        self.interaction_mode = interaction_mode

    def check(self, *, tool_name: str, tool_input: dict[str, Any]) -> ToolPermissionDecision:
        """返回命中的权限动作；tasks 模式下 require_approval 会降级成 allow。"""
        if not self.enabled:
            return ToolPermissionDecision(action="allow", reason="工具权限表未启用。")

        matched_rule = self._find_first_matching_rule(tool_name=tool_name, tool_input=tool_input)
        if matched_rule:
            action = str(matched_rule.get("action", "allow")).strip() or "allow"
            rule_id = str(matched_rule.get("id", "")).strip()
        else:
            action = self.default_action
            rule_id = "default_action"

        if action == "require_approval" and self.interaction_mode != "headless_hitl":
            return ToolPermissionDecision(
                action="allow",
                matched_rule_id=rule_id,
                reason="当前不是 headless_hitl 模式，require_approval 按 allow 处理。",
            )
        if action not in {"allow", "deny", "require_approval"}:
            return ToolPermissionDecision(
                action="deny",
                matched_rule_id=rule_id,
                reason=f"权限规则 action 非法：{action}",
            )
        return ToolPermissionDecision(
            action=action,
            matched_rule_id=rule_id,
            reason=f"命中工具权限动作：{action}",
        )

    def _find_first_matching_rule(self, *, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
        """按顺序查找第一条匹配规则，保证配置顺序就是策略优先级。"""
        for rule in self.rules:
            if str(rule.get("tool", "")).strip() not in {"", tool_name}:
                continue
            if self._match_extra_conditions(rule=rule, tool_input=tool_input):
                return rule
        return None

    def _match_extra_conditions(self, *, rule: dict[str, Any], tool_input: dict[str, Any]) -> bool:
        """匹配 path 和 command 的简单条件；没有 match 时代表只按 tool 命中。"""
        match_config = rule.get("match", {})
        if not isinstance(match_config, dict) or not match_config:
            return True

        command_text = self._command_text(tool_input.get("command"))
        path_text = str(tool_input.get("path", "")).strip()
        if not self._contains_any(command_text, match_config.get("command_contains_any")):
            return False
        if not self._contains_any(path_text, match_config.get("path_contains_any")):
            return False
        if not self._glob_any(path_text, match_config.get("path_glob_any")):
            return False
        return True

    def _contains_any(self, text: str, patterns: Any) -> bool:
        """如果配置了 contains 条件，则要求文本至少包含一个指定片段。"""
        pattern_list = [str(item) for item in patterns] if isinstance(patterns, list) else []
        if not pattern_list:
            return True
        return any(pattern in text for pattern in pattern_list)

    def _glob_any(self, text: str, patterns: Any) -> bool:
        """如果配置了 glob 条件，则要求路径至少命中一个 glob。"""
        pattern_list = [str(item) for item in patterns] if isinstance(patterns, list) else []
        if not pattern_list:
            return True
        return any(fnmatch.fnmatch(text, pattern) for pattern in pattern_list)

    def _command_text(self, command: Any) -> str:
        """把命令参数转成单行文本，供 contains 规则做保守匹配。"""
        if isinstance(command, list):
            return " ".join(str(item) for item in command)
        return str(command or "")
