# MVP2 HITL 与工具权限控制设计

## 背景

当前 MVP1 已经具备稳定的单 agent 自动执行链路：`ingest -> analyze -> (plan -> act -> observe)* -> verify -> finalize`。它已经支持 `initial_guide`、`context_snapshot`、运行时记忆、长期记忆、工具 schema 校验、沙箱执行、验证规则、trace、report、live trace、eval summary，以及任务结束总览。

MVP2 的目标不是先扩张能力，而是把项目往“可靠、可控、可解释”的方向推进。当前版本最明显的短板是：模型一旦决定调用工具，harness 缺少细粒度的人类审批点；运行暂停后也没有清晰的恢复协议；报告和 eval 中缺少对人工介入过程的结构化说明。

因此 MVP2 聚焦三件事：

1. 工具执行前的静态权限控制。
2. headless human-in-the-loop 暂停与恢复。
3. 人工介入信息进入 trace、report、eval 和 `context_snapshot`。

## 目标

- 保持 MVP1 的 `tasks` 默认模式兼容，不破坏已有自动 eval。
- 新增 `headless_hitl` 模式，在敏感工具执行前暂停并等待人工响应。
- 用静态规则表控制工具行为，支持 `allow`、`deny`、`require_approval`。
- 暂停时写出明确的 `HumanInputRequest`，恢复时读取匹配的 `HumanInputResponse`。
- 恢复时加载之前的运行态上下文，而不是把任务当成新任务重跑。
- 在 `context_snapshot.human_context` 中提供对下一轮决策有帮助的人工介入摘要。
- 在 trace、report、eval summary 中说明人工介入是否发生、为什么发生、处理结果如何。
- 为未来 `interactive`、multi-agent、skill、sub-agent 留下文档化扩展点，但 MVP2 不实现这些能力。

## 非目标

- 不实现实时 CLI 对话式审批。
- 不实现多 agent 调度。
- 不实现 sub-agent。
- 不实现 skill runtime。
- 不允许人类直接编辑模型生成的工具参数。
- 不实现任意阶段 checkpoint/replay。
- 不实现复杂风险评分或命令语义分析。
- 不做批量工具审批。

## 运行模式

MVP2 引入 `interaction_mode`：

```text
tasks
  默认模式，保持 MVP1 行为。
  agent 自动运行到 verify/finalize。
  不主动生成人工输入请求。

headless_hitl
  MVP2 核心模式。
  在 act 阶段执行工具前检查工具权限。
  命中 require_approval 时写出 human_input_request.json 并暂停。
  通过 --resume-run 和 human_response.json 恢复。

interactive
  未来模式。
  MVP2 只保留枚举、配置说明和错误提示。
  运行时选择该模式时，应明确报错：interactive 模式暂未实现，请使用 tasks 或 headless_hitl。
```

模式来源优先级：

```text
CLI --interaction-mode
  > eval task interaction_mode
  > config runtime.interaction_mode
  > default tasks
```

建议 CLI 入口：

```powershell
python -m cli --task "..." --interaction-mode tasks
python -m cli --task "..." --interaction-mode headless_hitl
python -m cli --resume-run runs/run-xxx --human-response human_response.json
```

`--resume-run` 只恢复 `need_human_input` 状态，不是通用 run resume 系统。如果 run 不是暂停等待人工输入、请求已经处理、`request_id` 不匹配或 `pending_tool_call` 缺失，应直接失败并给出中文错误。

## 工具权限静态规则表

MVP2 使用静态规则表，不做风险评分。权限表的职责是决定工具是否可以执行，或是否需要人工审批。

示例配置：

```json
{
  "tool_permissions": {
    "enabled": true,
    "default_action": "allow",
    "rules": [
      {
        "id": "read_file_allowed",
        "tool": "read_file",
        "action": "allow"
      },
      {
        "id": "edit_requires_approval",
        "tool": "apply_patch",
        "action": "require_approval"
      },
      {
        "id": "risky_shell_requires_approval",
        "tool": "shell_command",
        "action": "require_approval",
        "match": {
          "command_contains_any": ["Remove-Item", "rm", "git reset", "pip install"]
        }
      },
      {
        "id": "hard_reset_denied",
        "tool": "shell_command",
        "action": "deny",
        "match": {
          "command_contains_any": ["git reset --hard"]
        }
      }
    ]
  }
}
```

行为规则：

- `allow`：正常执行工具。
- `deny`：不执行工具，把策略拒绝结果写入 observe，让模型下一轮知道失败原因。
- `require_approval`：不执行工具，生成 `human_input_request.json`，run 以 `need_human_input` 暂停。
- 规则按顺序匹配，命中第一条后停止。
- 未命中任何规则时使用 `default_action`。
- 第一版只支持简单匹配：`tool`、`command_contains_any`、`path_contains_any`、`path_glob_any`。

权限表不修改工具参数。如果人类认为工具参数不合适，应使用 `reject` 或 `add_instruction`，让模型重新决策。

## 人工输入请求与响应

`HumanInputRequest` 写在 run 目录，用于说明系统为什么暂停，以及等待人类处理哪一个工具调用。

```json
{
  "request_id": "hir_20260707_000001",
  "run_id": "run-xxx",
  "created_at": "2026-07-07T12:00:00+08:00",
  "stage": "act",
  "reason": "tool_requires_approval",
  "message": "工具 apply_patch 需要人工确认后才能执行。",
  "tool_call_id": "toolcall_001",
  "tool_index": 0,
  "tool_total": 3,
  "tool": "apply_patch",
  "tool_input_preview": "...",
  "full_tool_input_path": "runs/.../pending_tool_call.json",
  "policy": {
    "matched_rule_id": "edit_requires_approval",
    "action": "require_approval"
  },
  "allowed_responses": ["approve", "reject", "add_instruction"],
  "context_hint": {
    "task": "...",
    "iteration": 3,
    "last_rational": "..."
  }
}
```

`HumanInputResponse` 由用户或外部系统提供：

```json
{
  "request_id": "hir_20260707_000001",
  "tool_call_id": "toolcall_001",
  "action": "approve",
  "instruction": "",
  "responded_at": "2026-07-07T12:05:00+08:00"
}
```

响应动作：

- `approve`：执行暂停前保存的 pending tool call。
- `reject`：不执行 pending tool call，把人工拒绝写回 observe，让模型重新决策。
- `add_instruction`：不执行 pending tool call，把补充指令写入 `context_snapshot.human_context`，让模型带着新指令重新规划。

MVP2 的人工审批粒度是单个 tool call。即使模型一次返回多个工具调用，也按顺序逐个检查和暂停。恢复时必须同时校验 `request_id` 和 `tool_call_id`，保证人类响应准确对应到某一个工具调用。

## 暂停与恢复流程

暂停点只放在 `act` 阶段真正执行工具之前。

```text
model_decision 生成 tool_call
        ↓
act 准备执行工具
        ↓
ToolPermissionEngine 检查静态规则
        ↓
allow：执行工具，进入 observe
deny：不执行工具，写入 observe，继续下一轮
require_approval：写 human_input_request.json，run 暂停
```

命中 `require_approval` 后，run 的结束状态为：

```json
{
  "stop_reason": {
    "kind": "need_human_input",
    "details": {
      "request_id": "hir_...",
      "tool_call_id": "toolcall_...",
      "request_path": "runs/.../human_input_request.json"
    }
  }
}
```

恢复不是恢复 Python 进程现场，而是恢复运行所需的持久化状态：

- 原始 task spec。
- 当前 runtime state，例如 iteration、step、working_memory、最近 observe 结果。
- `context_snapshot` 可重建状态，例如 `last_rational`、`human_context`、已读片段和过期上下文提示。
- 暂停前未执行的 `pending_tool_call`。
- `human_input_request.json`。
- 已有 trace、report 和 artifacts。

恢复流程：

```text
加载 paused run 目录
        ↓
校验 human_response 的 request_id/tool_call_id
        ↓
approve：执行 pending tool call，进入 observe
reject：写入人工拒绝结果，进入下一轮 model_decision
add_instruction：写入人工指令，进入下一轮 model_decision
        ↓
继续追加同一个 run 的 trace
```

恢复后不能新开一个 run，也不能覆盖历史 trace。

## context_snapshot.human_context

人工介入信息不混进 `recent_facts`，而是单独放在 `context_snapshot.human_context`。

```json
{
  "context_snapshot": {
    "human_context": {
      "pending_request": null,
      "responses": [
        {
          "request_id": "hir_20260707_000001",
          "tool_call_id": "toolcall_001",
          "action": "reject",
          "instruction": "",
          "created_at": "2026-07-07T12:05:00+08:00",
          "stage": "act",
          "tool": "apply_patch"
        }
      ],
      "instructions": [
        {
          "request_id": "hir_20260707_000002",
          "tool_call_id": "toolcall_002",
          "text": "不要改测试，只改业务逻辑。",
          "created_at": "2026-07-07T12:10:00+08:00"
        }
      ],
      "policy_events": [
        {
          "tool": "shell_command",
          "action": "deny",
          "reason": "命中禁止执行规则：git reset --hard"
        }
      ]
    }
  }
}
```

字段语义：

- `pending_request`：当前是否存在等待处理的人工请求。
- `responses`：历史人工响应摘要，让模型知道哪些工具被批准或拒绝过。
- `instructions`：`add_instruction` 提供的补充指令。
- `policy_events`：权限系统造成的拒绝、拦截、需审批记录。

`human_context` 是给模型看的运行上下文，不是完整审计日志。完整审计以 `trace.jsonl` 为准。`human_context` 只保留对下一轮决策有帮助的精简信息。

`add_instruction` 的优先级高于普通 runtime facts，但低于系统级约束、任务原始要求、sandbox 规则和工具 schema。

## Trace 事件

MVP2 新增或标准化以下事件：

```text
tool_permission_checked
tool_permission_denied
human_input_requested
run_paused
human_input_response_loaded
run_resumed
human_input_approved
human_input_rejected
human_instruction_added
```

事件中应包含 `request_id`、`tool_call_id`、`tool`、`action`、`matched_rule_id` 等可审计字段。涉及工具输入时，trace 可以记录摘要和 artifact 路径，避免把过长内容重复写入事件。

## Report 与 Eval 输出

`report.md` 增加人工介入记录：

```markdown
## 人工介入记录

- 本次运行触发了人工审核：是
- 暂停原因：工具 apply_patch 命中 require_approval 规则
- 请求文件：human_input_request.json
- 人工响应：approve
- 恢复结果：已执行原 pending tool call，并继续进入 observe
```

未触发时也保留说明：

```markdown
## 人工介入记录

本次运行没有触发人工审核。
```

`summary.json` / eval 汇总增加：

```json
{
  "hitl": {
    "triggered": true,
    "paused": true,
    "resumed": true,
    "requests": 1,
    "responses": 1,
    "last_action": "approve",
    "last_request_path": "..."
  }
}
```

`summary.md` 每条任务结果追加短摘要，例如：

```text
HITL: paused for apply_patch approval, resumed with approve
```

人工介入流程状态与任务验证状态必须分开表达。一个 run 可以是“HITL 流程成功，但业务验证失败”，也可以是“HITL 未触发，但任务验证通过”。

`task_outcome_summary` 的事实层也应纳入 HITL 摘要信息，使最终润色总结能说明本次任务是否触发人工介入。

## Eval 支持

MVP2 的 eval 需要覆盖两类任务。

第一类验证按预期暂停：

```json
{
  "id": "hitl_apply_patch_requires_approval",
  "interaction_mode": "headless_hitl",
  "expected_stop_reason": "need_human_input",
  "verify_rules": [
    {
      "type": "json_file_value_equals",
      "path": "human_input_request.json",
      "json_path": "$.reason",
      "expected": "tool_requires_approval"
    }
  ]
}
```

第二类验证预置人工响应后能恢复：

```json
{
  "id": "hitl_apply_patch_approved_resume",
  "interaction_mode": "headless_hitl",
  "expected_stop_reason": "need_human_input",
  "auto_human_response": {
    "action": "approve"
  },
  "resume_after_human_response": true
}
```

推荐实现为两段式：

```text
第 1 段 run：
  运行到 need_human_input，生成 request。

第 2 段 resume：
  eval_runner 根据 request_id/tool_call_id 生成 human_response.json。
  调用 --resume-run 继续跑。
```

这样可以同时测试暂停、request 写入、response 对齐、恢复运行态、trace 追加和后续 verify。

## 未来扩展预留

### interactive mode

MVP2 不实现 interactive，只保留枚举和文档。未来 interactive 必须是 CLI 直接对话，不要求用户手写 JSON。

未来交互示例：

```text
工具 apply_patch 需要人工确认

[1] approve
[2] reject
[3] add_instruction

请输入选择：
```

如果选择 `add_instruction`：

```text
请输入补充指令：
不要改测试文件，只修改业务逻辑。
```

interactive 内部可以复用 `HumanInputRequest` / `HumanInputResponse` 结构，但这是系统内部对象。用户体验上应直接在 CLI 输入选择和自然语言 instruction。

### multi-agent、skill、sub-agent

MVP2 只做接口预留和文档说明，不实现能力扩张面。

后续接入这些能力时，需要遵守以下原则：

- sub-agent 调用也应能被包装成工具或 action，并进入权限检查。
- skill 加载、skill 选择、skill 注入上下文不能绕过工具权限和 HITL。
- multi-agent 需要明确 owner、权限继承、trace 归属、子任务结果合并。
- 人工介入结构继续复用 `human_context`，避免为每种新能力单独设计一套上下文入口。

## 测试策略

### 单元测试

- 工具权限规则匹配：`allow`、`deny`、`require_approval`、顺序优先级、默认动作。
- `HumanInputRequest` / `HumanInputResponse` 校验：`request_id`、`tool_call_id`、非法 action、缺字段中文错误。
- `context_snapshot.human_context` 构建：approve、reject、add_instruction、policy events。

### 运行流测试

- `tasks` 模式保持 MVP1 行为。
- `headless_hitl` 命中 `require_approval` 后正确暂停。
- `approve` 后恢复并执行 pending tool call。
- `reject` 后不执行 pending tool call，并让模型下一轮重新决策。
- `add_instruction` 后不执行 pending tool call，指令进入下一轮上下文。
- 多 tool calls 时逐个审批。

### Eval 测试

- expected pause task：验证 `need_human_input`、request 文件、trace 事件。
- auto resume task：验证自动生成 response 后可以 resume，并继续 verify。
- mismatch response task：验证错误 `request_id/tool_call_id` 会失败。
- deny task：验证禁止工具不会执行，但 run 不一定暂停。
- interactive task：MVP2 中选择 interactive 应明确失败并提示未实现。

### 报告与追踪测试

- `report.md` 有人工介入记录。
- `trace.jsonl` 有完整 HITL 事件链。
- `summary.json` 有 `hitl` 字段。
- `task_outcome_summary` 能说明是否触发人工介入。
- 恢复后的 trace 追加到同一个 run。

## MVP2 验收标准

1. 旧 `tasks` 模式 eval 不回退。
2. `headless_hitl` 能在敏感工具前暂停。
3. `approve`、`reject`、`add_instruction` 三种路径都可验证。
4. resume 能恢复之前运行态上下文，而不是重跑新任务。
5. report、trace、eval summary 能解释 HITL 发生了什么。
6. `interactive`、multi-agent、skill、sub-agent 的预留边界写入文档。

