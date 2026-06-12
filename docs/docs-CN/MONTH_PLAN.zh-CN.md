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

## 延后工作

- Web UI。
- IDE integration。
- Multi-agent execution。
- Remote sandbox。
- Full symbol graph。
- Embedding memory。
- 专门的 memory 污染实验。
- 大型 benchmark 集成。
