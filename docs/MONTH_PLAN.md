# 一个月开发计划

## 第 1 周：单任务 Loop

目标：跑通一个本地任务闭环，并留下结构化 trace。

交付物：

- CLI skeleton。
- Agent state enum 和状态机 loop。
- Model adapter base interface。
- 初始模型 provider 实现或 stub。
- Tool registry。
- 核心工具：
  - `search_text`
  - `read_file`
  - `apply_patch`
  - `run_command`
  - `git_diff`
- Runtime memory。
- JSONL trace writer。
- 最小 Markdown run report。

验收标准：

- 一个简单 code understanding 或 bug fix 任务能跑过 `ingest -> analyze -> plan -> act -> observe -> verify -> finalize`。
- 工具调用和状态转移写入 trace。
- 生成 run report。

## 第 2 周：Context 和 Memory

目标：让模型输入变得可控，并接入 memory。

交付物：

- `task_context`、`repo_context`、`runtime_context`、`memory_context`。
- 文件级召回。
- 原文、摘要、索引三类上下文策略。
- 上下文预算和裁剪规则。
- 结构化长期 memory store。
- memory read/write trace 事件。
- 条件 reflect 触发规则。
- memory conflict evidence 记录。

验收标准：

- 可以配置不同 context 策略。
- 成功且验证通过的 run 能写入长期 memory。
- 后续 run 能检索相关 memory。
- 验证失败或重复低进展时能触发 reflect。

## 第 3 周：Eval 闭环

目标：从单次运行进入可重复评测。

交付物：

- Eval task spec schema。
- Eval runner。
- Result metrics。
- Process metrics。
- Diagnostic labels。
- 基于规则的诊断 pass。
- 批量 Markdown eval summary。
- 初始 12 到 20 个任务。

验收标准：

- 一条命令可以运行固定 eval task set。
- summary 包含成功率、平均 step、平均 tool call、reflect count、verify count 和失败类型分布。
- 失败任务包含 primary failure、secondary failures 和 evidence。

## 第 4 周：策略对比

目标：证明 harness 能支持有意义的迭代。

交付物：

- Baseline strategy config。
- Context 策略对比：
  - `naive_recent_context`
  - `file_recall_context`
  - `file_recall_plus_summary`
- Memory 对比：
  - `memory_off`
  - `structured_memory_on`
- Reflect 对比：
  - `verify_failure_only_reflect`
  - `low_progress_plus_verify_reflect`
- 策略对比 report。
- 代表性 trace 分析。
- README 和设计文档整理。

验收标准：

- 至少两种策略能在同一 task set 上比较。
- report 展示结果、成本、失败类型分布的差异。
- 项目能回答至少三个研究问题：
  - 文件级召回是否减少 `context_miss`？
  - 结构化 memory 是否减少重复探索？
  - 条件触发 reflect 是否减少 `repeated_no_progress`？

补充现状：

- `Phase 8` 已暂定完结，上述策略对比外壳已经具备。
- 但当前 agent 仍主要运行 stub 执行链路，不能把这些结果直接视为“真实代码任务实验结论”。
- 当前还缺少真实模型/策略决策层本体，尚未进入真正的任务级模型决策与工具选择闭环。

## 第 5 周：真实任务最小闭环补缺口

目标：把项目从“可做策略对比的 harness”推进到“可跑真实任务实验的 harness”。

交付物：

- 真实任务最小 schema。
- eval task 中的 sandbox / setup / verify / pass criteria 字段。
- 每题独立 sandbox 目录执行模式。
- 真实模型/策略决策层接入。
- 任务级真实 verify runner。
- 至少一类真实任务的最小求解闭环。
- 与现有 eval / comparison / experiment 外壳的兼容接入。

验收标准：

- 单题运行默认在独立 sandbox 目录中进行。
- batch eval 中不同任务互不污染，输入态可复现。
- 任务执行不再依赖固定 stub 工具序列，而是由真实模型/策略决策层推进。
- verify 来自真实任务检查，而不是演示型 `agent_notes.md` 校验。
- 至少一类真实任务能跑通“读代码、改代码、验证代码”闭环。

## 第 6 周：真实任务实验基线

目标：基于真实任务闭环，重建更可信的实验基线。

交付物：

- 第一版真实任务固定实验集。
- 更能区分 context 策略的 context-sensitive 任务。
- 真实任务上的 baseline comparison 结果。
- 对 memory / reflect 默认策略是否调整的结论。

验收标准：

- `naive_recent_context` 与 `file_recall_context` 至少在部分任务上能拉开差异，或能明确证明当前差异仍不成立。
- 真实任务结果可以支持是否收紧默认 memory / reflect baseline 的判断。
- 实验结论建立在隔离 sandbox 与真实 verify 之上。

## MVP 完成标准

一个月 MVP 完成时应做到：

- 本地 CLI 能启动任务。
- agent 能 plan、use tools、modify files、verify、finalize。
- 每次 run 生成 JSONL trace。
- 每次 run 生成 Markdown report。
- 固定 eval set 能批量运行。
- 能做策略对比。
- 失败能带证据分类。
- memory 污染能通过诊断标签和冲突证据被检测到。

补充说明：

- 上述“一个月 MVP”目标已大体完成到 `Phase 8`。
- 当前新增的收口目标是：在此基础上补齐真实任务最小闭环，让策略实验从“演示链路比较”升级为“真实任务比较”。

## 延后工作

- Web UI。
- IDE integration。
- Multi-agent execution。
- Remote sandbox。
- Full symbol graph。
- Embedding memory。
- 专门的 memory 污染实验。
- 大型 benchmark 集成。
