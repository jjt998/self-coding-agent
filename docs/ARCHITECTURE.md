# Self Coding Agent 技术架构文档

## 1. 文档目的

本文档定义 `self-coding-agent` 一个月 MVP 的技术架构。

目标不是做一个通用自治 agent 平台，而是做一个面向本地代码仓库的 coding agent harness。这个 harness 需要足够结构化，以支持：

- 可重复执行
- 可追踪
- 可评测
- 可比较不同策略
- 后续围绕 context、memory、loop 持续迭代

## 2. 架构原则

- 第一版必须小到能在一个月内完成。
- 组件边界必须清晰，便于隔离策略变量。
- 优先使用结构化状态和结构化事件，而不是自由文本日志。
- trace、replay、eval 不是附属功能，而是一等架构能力。
- 工具执行必须受控、有边界、可审计。
- 设计时预留可插拔能力，但第一周不过度抽象。

## 3. 系统总览

```text
CLI
  -> Config Loader
  -> Orchestrator
    -> Agent Loop
      -> Context Builder
      -> Memory Manager
      -> Model Adapter
      -> Tool Registry
      -> Verifier
      -> Trace Writer
      -> Reporter

Eval Runner
  -> Task Spec Loader
  -> Orchestrator
  -> Metrics Aggregator
  -> Diagnostics Pass
  -> Batch Reporter
```

核心运行路径如下：

1. 加载任务和策略配置。
2. 创建初始运行状态。
3. 进入显式状态机 loop。
4. 为当前状态构建上下文。
5. 调用模型，请它输出结构化决策。
6. 执行工具调用或状态转移。
7. 更新 runtime memory 和 trace。
8. 在合适时机执行 verify。
9. 最终收尾并输出报告。

## 4. 模块职责

### 4.1 CLI

职责：

- 接收 repo 路径、任务输入、配置路径和预算覆盖项。
- 启动单任务运行或批量 eval 运行。
- 选择策略 profile。
- 选择模型 provider。

非目标：

- 富交互 UI。
- 多会话状态管理。

### 4.2 Orchestrator

职责：

- 持有一次 run 的完整生命周期。
- 创建初始 runtime state。
- 驱动 loop 的状态转移。
- 执行预算和 stop 条件控制。
- 协调 trace、report 和 memory 持久化。

Orchestrator 是顶层应用服务，不应包含 provider 级模型细节，也不应包含具体工具实现。

### 4.3 Agent Loop

职责：

- 定义状态。
- 定义允许的状态转移。
- 定义什么时候调用模型。
- 定义什么时候执行工具。
- 定义什么时候 verify 和 reflect。

MVP 阶段 loop 是固定 baseline，不是第一批主要实验变量。

### 4.4 Context Builder

职责：

- 从 task、repo、runtime、memory 四层组装模型输入。
- 应用召回、摘要和裁剪策略。
- 产出上下文 bundle 以及“上下文是如何构建出来的”元数据。

### 4.5 Memory Manager

职责：

- 维护当前 run 的 runtime memory。
- 读取和写入 long-term memory。
- 应用 memory 检索过滤规则。
- 记录 memory 冲突和使用元数据。

### 4.6 Model Adapter

职责：

- 将 harness 内部统一请求转换成 provider 原生请求。
- 将 provider 返回统一归一化为公共结果结构。
- 暴露模型能力元数据。

### 4.7 Tool Registry

职责：

- 注册工具 schema 和处理器。
- 校验工具参数。
- 在 workspace 边界内执行工具。
- 标准化工具返回。

### 4.8 Verifier

职责：

- 运行验证命令或验证检查。
- 标准化验证结果。
- 输出 passed、failed 或 blocked。

### 4.9 Trace Writer

职责：

- 持久化 JSONL 结构化事件。
- 分配 event ID 和 timestamp。
- 为大输出写 artifact 引用。

### 4.10 Reporter

职责：

- 生成单次 run Markdown report。
- 生成批量 eval Markdown summary。
- 呈现 diagnostics、metrics 和 strategy delta。

## 5. 建议目录结构

```text
self-coding-agent/
  pyproject.toml
  README.md
  configs/
    default.yaml
    strategies/
      baseline.yaml
  docs/
    PRD.md
    PRD.zh-CN.md
    ARCHITECTURE.md
    ARCHITECTURE.zh-CN.md
    MONTH_PLAN.md
    MONTH_PLAN.zh-CN.md
  src/
    cli.py
    config.py
    loop.py
    runner.py
    trace.py
    tools/
      base.py
      registry.py
      filesystem.py
      command.py
      git.py
    context/
      builder.py
      recall.py
      compression.py
      layers.py
    memory/
      runtime_memory.py
      long_term_memory.py
      store.py
      retrieval.py
    models/
      base.py
      openai_adapter.py
    eval/
      task_spec.py
      runner.py
      metrics.py
      diagnostics.py
    reports/
      markdown.py
    schemas/
      common.py
  eval_tasks/
  runs/
  tests/
```

## 6. 核心数据模型

MVP 阶段所有跨模块边界都应使用强结构化数据模型。

建议的一组核心模型如下：

### 6.1 RunConfig

```yaml
run_config:
  repo_path:
  model_provider:
  model_name:
  strategy_name:
  max_steps:
  max_tool_calls:
  verify_enabled:
  trace_enabled:
```

### 6.2 TaskSpec

```yaml
task_spec:
  id:
  task_type:
  instruction:
  success_criteria:
  constraints:
  prohibitions:
  validation:
  expected_touched_files:
  forbidden_touched_files:
  allowed_tools:
  tags:
```

### 6.3 RuntimeState

```yaml
runtime_state:
  run_id:
  task_id:
  current_state:
  step_count:
  tool_call_count:
  status:
  stop_reason:
  current_plan:
  candidate_files:
  active_files:
  modified_files:
  last_verify_result:
```

### 6.4 PlanStep

```yaml
plan_step:
  step_id:
  description:
  status: pending | in_progress | completed | dropped
  rationale:
```

### 6.5 ModelDecision

```yaml
model_decision:
  provider:
  model_name:
  task_type:
  summary:
  rationale:
  loop_end:
  planned_actions:
    - "本轮 tool_calls 实际会执行的动作说明"
  donelist:
    - "到当前轮为止已经完成的事项列表（累计 done list）"
  tool_calls:
    - tool_name:
      tool_input:
  raw_response_content:
  normalization_notes:
```

字段职责：

- `tool_calls` 是唯一执行源，`act` 阶段只按这个数组调用工具。
- `planned_actions` 是本轮可读计划说明，不是跨轮任务队列，也不驱动执行。
- `donelist` 当前承载累计已完成事项，下一轮会通过 `runtime_feedback.previous_donelist` 回填给模型，帮助模型记住“已经做过什么”。
- `loop_end` 不是“差不多做完了”的软信号，而是“后续不再执行任何读取、修改、命令检查、diff 检查或补充验证”的硬收口信号；当它为 `true` 时，同轮 `tool_calls` 必须为空。
- `raw_response_content` 只写入本地 trace，用于排查模型显式返回内容，不包含 provider 隐藏推理链。
- `normalization_notes` 记录展示字段的宽容归一化，例如缺失 `planned_actions` 时从 `tool_calls` 派生说明。

### 6.6 ToolResult

```yaml
tool_result:
  tool_name:
  status: success | error | blocked
  output:
  error:
  metadata:
  duration_ms:
```

### 6.7 VerifyResult

```yaml
verify_result:
  status: passed | failed | blocked
  command:
  exit_code:
  stdout_summary:
  stderr_summary:
```

### 6.8 MemoryEntry

```yaml
memory_entry:
  memory_id:
  repo_id:
  memory_kind:
  content:
  file_paths:
  module_tags:
  task_type:
  source_run_id:
  verified:
  stability_level:
  confidence:
  conflict_count:
  status:
```

## 7. Agent Loop

### 7.1 状态

- `ingest`：加载任务、repo、约束、预算和策略。
- `analyze`：理解任务，并识别初始 repo 线索。
- `plan`：在第一次行动前产出阶段性执行计划。
- `act`：调用工具或执行修改。
- `reflect`：每轮 `act` 后固定执行，保真压缩工具结果、diff 事实、失败工具和轻量 signals。
- `verify`：运行验证检查。
- `finalize`：输出最终状态、报告和可写入的 memory。

### 7.2 状态转移规则

```text
ingest -> analyze -> (plan -> act -> reflect)* -> verify -> finalize

solve loop exit -> verify
final verify passed -> finalize(completed)
final verify failed -> finalize(verification_failed)
```

### 7.3 Loop 不变量

- 第一次 `act` 前必须先经过 `plan`。
- 除非任务类型明确允许，否则 `finalize` 之前必须至少有一次 verify。
- `reflect` 是每一轮 `act` 后的固定事实压缩步骤。
- 每次工具调用都必须增加 `tool_call_count`。
- 每次状态转移都必须写入 trace event。

### 7.4 Reflect 事实压缩

- harness 负责保真地压缩事实，LLM 负责解释事实并重规划。
- 如果本轮有修改类工具且最新 `git_diff.changed_file_count == 0`，reflect 记录 `no_diff_after_edit_attempt`。
- 如果本轮只有读取、搜索或其它信息收集工具，不产生 no-diff signal。
- 下一轮模型不会再收到 `previous_verification` 或 `previous_reflect.verification`；最终验证只作为末尾裁判结果保留在 trace、report 和 eval 聚合里。
- `file_context_cache` 现在会区分 `fresh` 与 `stale`：文件一旦被 `apply_patch` 或 `replace_lines` 成功编辑，旧读取缓存按整文件失效；只有后续重新读取后才会恢复为 `fresh`。

### 7.5 模型可见预算

- `runtime.max_steps` 仍由 harness 内部控制最大求解轮数。
- 模型请求里的 `runtime_feedback` 不暴露当前轮数、剩余轮数或最大轮数。
- trace、report、stop reason 可继续记录轮数信息，供本地审计和诊断使用。

## 8. Context 架构

### 8.1 Context 分层

- `task_context`
- `repo_context`
- `runtime_context`
- `memory_context`

### 8.2 各层语义

`task_context`

- 任务目标
- 成功标准
- 约束条件
- 禁止事项
- 预算
- 任务类型

`repo_context`

- repo map
- 关键模块
- 构建和测试命令
- 候选文件
- 与任务相关的代码事实

`runtime_context`

- 当前计划
- 最近工具调用
- 关键观察
- 当前 diff 摘要
- 已尝试路径
- 当前活跃假设

当前实现里，进入第二轮及后续 `plan` 的跨轮输入由 `runtime_feedback` 承载：

- `previous_reflect`：上一轮事实反馈，包含 observation、signals、failed_tools、recent_tool_results、`file_context_cache`、`stale_file_paths` 和最近缓存失效诊断。
- `previous_donelist`：到上一轮为止的累计已完成事项列表。

这些字段共同组成下一轮模型的“运行上下文窗口”。其中 `previous_reflect.recent_tool_results`、`previous_reflect.file_context_cache` 和 `previous_donelist` 是为了减少模型在第二轮继续猜测源码，或忘记已经完成的事项；窗口中不会包含当前第几轮、还剩几轮或最大轮数。

`memory_context`

- 被选中的稳定长期记忆

### 8.3 注入策略

原文注入：

- 任务目标
- 成功标准
- 关键约束
- 最近验证错误
- 当前活跃代码片段
- 当前活跃测试片段
- patch 周边上下文

摘要注入：

- 大文件
- 长命令输出
- 历史尝试
- 旧验证结果
- diff 摘要

只做索引：

- 全 repo 文件列表
- 完整 trace 历史
- 大型文档
- 长期 memory 全量库
- 低概率候选文件

### 8.4 Context Builder 输出

Context Builder 应至少返回：

- 最终消息列表
- source references
- truncation summary
- 被选中的 candidate files
- 使用到的 memory entries

这些信息是 replay 和 diagnostics 的必要输入。

## 9. 文件级召回

MVP 使用文件级召回，加轻量关键词和符号搜索。

召回流程：

1. 从任务、错误、测试、最近结果和 memory 中提取线索。
2. 将线索映射到候选文件。
3. 根据不同信号强度对候选文件排序。
4. 读取 top 候选文件的摘要或命中片段。
5. 只将高价值片段注入上下文。

信号分层：

- 强信号：stack trace、测试输出、显式文件名、函数名、类名、测试名。
- 中信号：关键词命中、文件名、目录名、repo summary 提示。
- 弱信号：模糊关键词、宽泛模块标签、memory hint。

召回层不直接决定最终 prompt 内容，它只负责产出排序后的候选文件。

## 10. Memory 架构

### 10.1 Runtime Memory

Runtime memory 是单次 run 的结构化状态存储。

它应记录：

- 当前计划
- 已读文件
- 已修改文件
- 候选文件
- 已尝试路径
- 关键工具结果
- 关键错误
- verify 状态
- diff 摘要
- 当前活跃假设
- progress/no-progress 信号

### 10.2 Long-Term Memory

Long-term memory 是跨 run 的结构化存储。

只存储：

- 稳定 repo 事实
- 构建和测试命令
- 关键模块和入口点
- 用户偏好
- 成功修复模式
- 特定任务类型在该 repo 上的经验

### 10.3 写入规则

- 默认只有任务成功且 verify 通过后才写入。
- 写入小颗粒、结构化条目，而不是长故事。
- 当 memory 与实时证据冲突时，增加 conflict 元数据。

### 10.4 检索规则

MVP 检索方式：

- repo filter
- task-type filter
- module-tag filter
- file-path filter
- keyword search

MVP 不使用 embedding 检索。

### 10.5 Memory 污染预留

MVP 包含：

- `memory_pollution` 诊断标签
- `memory_conflict` 证据
- schema 预留 confidence、conflict count、status 等字段

MVP 不包含专门的 memory 污染治理策略实验。

## 11. Model Adapter

Model Adapter 负责统一不同 provider 的行为。

建议接口形态：

```python
class BaseModelAdapter:
    def generate(self, request): ...
    def supports_native_tools(self) -> bool: ...
    def supports_structured_output(self) -> bool: ...
    def max_context_tokens(self) -> int: ...
```

归一化后的结果至少应包含：

- assistant text
- structured decision
- tool call requests
- usage metadata
- raw provider metadata

架构上同时支持两种模式：

- native tool calling
- text action parsing

## 12. Tool Layer

### 12.1 核心工具

- `search_text`
- `read_file`
- `read_file_structure_summary`
- `read_file_range`
- `apply_patch`
- `replace_lines`
- `run_command`
- `git_diff`

读取类工具分工如下：

- `read_file`：小文件直接返回全文；大文件只返回 `content_mode="structure_summary"` 与结构摘要。
- `read_file_structure_summary`：显式只读结构摘要，适合先定位大文件里的函数、类、标题和起始行号。
- `read_file_range`：按闭区间行号精读关键片段。

### 12.2 工具契约

每个工具定义应包含：

- name
- description
- argument schema
- accepted aliases
- execution handler
- permission constraints

当前工具 schema 至少包含：

- `required`：必填字段。
- `optional`：可选字段。
- `properties`：字段类型，例如 `string`、`integer`、`null`、`array` 和数组元素类型。
- `accepted_aliases`：模型常见别名到规范字段的映射，例如 `file_path -> path`。

校验发生在两层：

- 模型响应解析阶段：拒绝未知工具、非对象 `tool_input`、未声明字段、缺少必填字段和类型不匹配字段。
- `act` 前兜底阶段：对 fake adapter 或测试直接构造的 `ModelDecision` 再做一次 schema 校验。

示例：

```yaml
apply_patch:
  required: [path, old_text, new_text]
  properties:
    path: string
    old_text: string | null
    new_text: string
```

因此 `apply_patch.new_text = null` 会在模型决策层收口为 `ModelResponseError` / `model_error`，不会继续进入 `Path.write_text(None)` 这类工具层 traceback。

每个工具结果应包含：

- `status`
- `output`
- `error`
- `metadata`
- `duration_ms`

命令类工具还应包含：

- `exit_code`
- `stdout`
- `stderr`
- `timed_out`

### 12.3 安全规则

- 所有文件写入必须保持在 workspace 内。
- 危险命令模式必须阻断。
- 命令执行必须包含 timeout 和 working directory 控制。
- 工具失败必须结构化返回，不能用沉默异常吞掉。
- 即使上游绕过 schema 校验，工具实现也应尽量返回结构化失败，例如 `apply_patch` 的 `invalid_tool_input`。

## 13. Trace 与 Replay

### 13.1 Trace 格式

Trace 使用 JSONL，一行一个事件。

核心事件类型：

- `run_started`
- `state_entered`
- `context_built`
- `model_requested`
- `model_responded`
- `tool_called`
- `tool_completed`
- `memory_read`
- `memory_written`
- `patch_applied`
- `verify_completed`
- `reflect_completed`
- `state_result`
- `state_transitioned`
- `run_finished`

### 13.2 事件结构

```json
{
  "run_id": "run_001",
  "task_id": "bug_fix_001",
  "event_id": 1,
  "timestamp": "2026-06-11T00:00:00Z",
  "state": "act",
  "event_type": "tool_called",
  "payload": {}
}
```

### 13.3 存储策略

Trace 应存储：

- 结构化事件元数据
- 大 payload 的摘要
- 大输出的 artifact 引用

大 artifact 可能包括：

- 长 stdout/stderr
- 完整 prompt
- 完整文件快照
- 长 diff 输出

### 13.4 Replay 模式

MVP replay 模式：

- trace replay：重建历史 run 时间线
- deterministic rerun：后续增强，用相同配置重新跑任务

## 14. Eval 架构

### 14.1 Task Spec

Eval task spec 使用 YAML 或 JSON。

建议字段：

- `id`
- `task_type`
- `repo`
- `instruction`
- `success_criteria`
- `allowed_tools`
- `budgets`
- `validation`
- `expected_touched_files`
- `forbidden_touched_files`
- `tags`

### 14.2 指标

结果指标：

- success
- validation pass
- expected files touched
- unexpected changes

过程指标：

- steps
- tool calls
- verify count
- reflect count
- duration

诊断指标：

- primary failure
- secondary failures
- evidence
- diagnosis source

### 14.3 实验规则

- 先定义 baseline。
- 一次只改一个变量。
- 对比实验中固定 task set、model 和 budget。
- 每次运行保存完整配置快照。

## 15. Reports

MVP report 使用 Markdown。

单次 run report 应包含：

- summary
- final status 和 stop reason
- strategy 和 model
- changes
- timeline
- diagnostics
- verification
- memory read/write

批量 eval summary 应包含：

- task set
- strategy
- model
- success rate
- 平均过程指标
- 各任务类型成功率
- failure profile
- 相对 baseline 的 delta

## 16. 持久化布局

建议的 run 输出目录：

```text
runs/
  run_20260611_001/
    trace.jsonl
    report.md
    config_snapshot.yaml
    artifacts/
      verify_stdout.txt
      verify_stderr.txt
      prompt_003.txt
```

建议的 long-term memory 存储：

```text
memory/
  long_term_memory.jsonl
```

MVP 阶段不需要复杂存储后端，JSONL 和本地文件已经足够。

## 17. 演进路径

### MVP

- 固定 baseline loop
- 文件级召回
- 无 embedding 的结构化 long-term memory
- 本地 CLI
- JSONL trace
- Markdown report
- batch eval

### Post-MVP

- 更丰富的 model adapters
- embedding-based memory retrieval
- 更强的 diagnostics automation
- symbol-aware recall
- memory pollution strategy experiments
- 远程执行隔离
- 更丰富的 report UI

## 18. 架构风险

- 如果 context layer 边界不严，Context Builder 会变成隐藏复杂度中心。
- 如果工具输出没有尽早标准化，tool contract 会快速漂移。
- 如果 trace payload 策略不控制，trace 会很快变得噪音过多。
- 如果过早放松 memory 写入规则，未来 run 会被污染。
- 如果 success criteria 没有按任务类型区分，eval 会失去可信度。
- 如果把可读计划说明、累计完成记录和真实工具执行混为一谈，模型可能“文字上看起来很忙、实际只读文件”；当前通过 `planned_actions`、`donelist`、`tool_calls` 三字段拆分降低这个风险。

MVP 架构选择故意偏保守，目标是在保证后续扩展点的同时，降低这些风险。

