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
    self_coding_agent/
      cli/
        main.py
      core/
        loop.py
        state.py
        runtime.py
        stop.py
        orchestrator.py
      models/
        base.py
        openai_adapter.py
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
      trace/
        events.py
        writer.py
        replay.py
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
  decision_type: tool_call | update_plan | verify | reflect | finalize
  reasoning_summary:
  tool_name:
  tool_args:
  plan_update:
  finalize_message:
```

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
- `observe`：解释工具结果并更新 runtime memory。
- `reflect`：分析低进展、验证失败或证据冲突。
- `verify`：运行验证检查。
- `finalize`：输出最终状态、报告和可写入的 memory。

### 7.2 状态转移规则

```text
ingest -> analyze -> plan -> act -> observe

observe -> act
observe -> reflect
observe -> verify

verify -> finalize
verify -> reflect

reflect -> act
reflect -> plan
reflect -> finalize
```

### 7.3 Loop 不变量

- 第一次 `act` 前必须先经过 `plan`。
- 除非任务类型明确允许，否则 `finalize` 之前必须至少有一次 verify。
- `reflect` 不是每一轮 loop 的固定步骤。
- 每次工具调用都必须增加 `tool_call_count`。
- 每次状态转移都必须写入 trace event。

### 7.4 Reflect 触发条件

- verify 失败。
- 连续工具结果没有新信息。
- 重复相同工具调用模式且没有状态变化。
- 反复读相同文件或做相同搜索但没有新信号。
- 工具结果与当前计划冲突。
- 接近 step budget 或 tool-call budget。

### 7.5 无进展规则

- 连续三步没有新增候选文件、有效 diff 或更好的验证结果。
- 连续两次代码修改后，验证结果没有改善。
- 工具多次返回空结果且计划未更新。
- 重复相同工具调用并得到相同输出。

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
- `apply_patch`
- `run_command`
- `git_diff`

### 12.2 工具契约

每个工具定义应包含：

- name
- description
- argument schema
- execution handler
- permission constraints

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

MVP 架构选择故意偏保守，目标是在保证后续扩展点的同时，降低这些风险。
