# 开发执行手册

## 1. 目的

本文档用于指导 `self-coding-agent` 项目第一版 MVP 的实际开发执行。

它服务于以下目标：

- 支持迭代式开发。
- 支持上下文压缩后的恢复。
- 支持新 AI 会话接手。
- 固定清晰的实现顺序。
- 提供稳定的进度判断标准。

未来如果需要在新会话中继续推进本项目，应优先把本文件与以下文档一起作为当前事实来源：

- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/MONTH_PLAN.md`

## 2. 项目意图

这个项目不是一次性的 coding agent demo。

这个项目是一个面向本地代码仓的研究型 coding agent harness，核心价值在于：

- 可比较
- 可观测
- 可回放
- 可诊断
- 可迭代实验

第一版 MVP 应优先保证 harness 质量，而不是单纯追求 bug 修复成功率。

补充说明：

- `Phase 8` 已暂定完结。
- 当前项目已经具备“固定任务集上的策略对比实验外壳”。
- 但当前还没有完成“真实代码任务求解闭环”。
- 因此后续开发重点不再是继续堆 comparison 指标，而是先补齐真实任务最小闭环。

## 3. 已确定且早期不应重开的 MVP 决策

以下决策已经确认，除非实现过程中出现强阻塞，否则早期开发不再重开讨论。

### 3.1 Loop 基线

采用显式状态机 loop：

- `ingest`
- `analyze`
- `plan`
- `act`
- `observe`
- `reflect`
- `verify`
- `finalize`

规则：

- 第一次 `act` 必须发生在 `plan` 之后。
- `reflect` 是条件触发，不是每步固定执行。
- `verify` 是 `finalize` 前的必要条件。
- 失败通过结构化 `status` 和 `stop reason` 表示，不单独建 `fail` 状态。

### 3.2 Context 基线

采用四层上下文：

- `task_context`
- `repo_context`
- `runtime_context`
- `memory_context`

第一版优先采用文件级召回，不做重型符号系统。

### 3.3 Memory 基线

采用：

- 运行时记忆
- 结构化长期记忆

第一版不使用向量记忆或 embedding 检索。

长期记忆只在任务成功且验证通过后写入。

### 3.4 Eval 基线

Eval 从第一阶段就开始进入设计与实现。

目标任务类型：

- `code_understanding`
- `bug_fix`
- `test_generation`
- `refactor`

### 3.5 Memory 污染范围

MVP 必须包含：

- `memory_pollution` 诊断标签
- `memory_conflict` 证据记录
- 为后续抗污染策略预留的 schema 字段

MVP 不包含专门的 memory 污染对比实验。

## 4. 实现顺序

不要按“哪个功能看起来更智能”来实现，而要按“哪个控制面先落地”来实现。

推荐顺序：

1. 项目脚手架。
2. 运行时数据模型与配置模型。
3. Trace writer 与 run 目录结构。
4. CLI 入口。
5. 工具注册表与五个核心工具。
6. 基线状态机 loop。
7. 验证流程。
8. Context builder 与文件级召回。
9. 运行时记忆。
10. 长期记忆存储与检索。
11. Eval task schema 与 batch runner。
12. Markdown 报告。
13. 策略开关与对比实验。
14. 真实任务最小 schema。
15. 任务级隔离执行环境。
16. 任务级真实 verify。
17. 从 stub loop 过渡到真实求解 loop。

## 5. 阶段拆分

### Phase 1：脚手架与控制面

目标：

- 让仓库具备可运行、可扩展、结构稳定的基础。

交付：

- `pyproject.toml`
- `src/` 源码目录结构
- `tests/`
- `configs/`
- `eval_tasks/`
- `runs/`
- 基础 settings model
- trace event model
- trace writer
- CLI skeleton

完成定义：

- 一条命令可以启动 run，并生成 run 目录、配置快照，以及空的 trace/report 占位文件。

### Phase 2：最小 Agent Loop

目标：

- 让任务能沿着固定状态机骨架运行。

交付：

- 状态枚举
- 运行时状态对象
- stop reason model
- loop orchestrator
- 无进展跟踪
- reflect 触发占位逻辑

完成定义：

- 即使模型行为仍是 stub，也可以完整跑出状态流，并生成状态迁移事件。

### Phase 3：核心工具

目标：

- 支撑最小本地代码任务闭环。

交付：

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

完成定义：

- 每个工具都有结构化输入输出，并且工具调用会进入 trace。

### Phase 4：验证与报告

目标：

- 让成功与失败具备审计能力。

交付：

- verification result schema
- verify 执行流程
- 单次 run 的 Markdown 报告
- 结构化 stop reason

完成定义：

- 一次 run 结束后，报告能展示状态、使用过的工具和验证结果。

### Phase 5：Context 与 Recall

目标：

- 让模型输入变成可控系统，而不是临时拼 prompt。

交付：

- task/repo/runtime/memory context models
- 文件级召回
- 原文/摘要/索引三种注入策略
- 上下文裁剪规则

完成定义：

- Trace 里能看到 context snapshot，候选文件召回过程可检查。

### Phase 6：Memory

目标：

- 在不引入重型检索的前提下实现经验复用。

交付：

- runtime memory manager
- long-term memory store
- 结构化 memory entry
- 基于 tags、task type、file path、keywords 的过滤检索
- conflict evidence tracking

完成定义：

- 成功且验证通过的 run 可以写入长期记忆，后续任务可以读取相关记忆。

### Phase 7：Eval

目标：

- 从单次运行提升为可重复评测。

交付：

- task spec schema
- eval runner
- result metrics
- process metrics
- diagnostic labels
- 基于规则的初步诊断流程
- batch Markdown summary

完成定义：

- 固定任务集可以批量运行，并输出成功率、平均步数、平均工具调用数和失败分布。

### Phase 8：策略对比

目标：

- 让 harness 真正进入实验用途。

交付：

- baseline strategy config
- context strategy variants
- memory on/off 开关
- reflect trigger variants
- comparison summary

完成定义：

- 同一任务集上至少两种策略可比较，并且能输出 delta。

### Phase 9：真实任务最小闭环

目标：

- 让 agent 从“固定 stub 演示链路”进入“真实代码任务求解链路”。
- 让 eval task 从“任务描述集”升级为“可复现实验任务集”。
- 让 verify 从“演示型检查”升级为“真实任务完成性验证”。
- 让批量实验具备任务级隔离，固定采用“每题独立 sandbox 目录”。

交付：

- 真实任务最小 schema
- sandbox task spec 字段
- 每题独立 sandbox 目录执行模式
- setup / verify / pass criteria 字段与执行链路
- 真实任务 verify runner
- stub loop 到真实任务 loop 的替换方案

完成定义：

- 单题运行可以在独立 sandbox 目录中执行，不污染其他任务。
- eval task 可以显式声明准备步骤、验证命令和通过标准。
- verify 结果来自真实任务检查，而不是 `agent_notes.md` 演示验证。
- 至少一类真实任务可以跑通“读代码、改代码、验证代码”的最小闭环。

## 5.1 Phase 9 开始前的事实约束

当前代码库里已经确认的约束如下：

- `src/loop.py` 仍以 `_run_stub_state` 为主。
- `src/tools.py` 仍以固定 `build_phase_3_tool_sequence()` 为主。
- `src/verify.py` 仍主要验证 `agent_notes.md`、固定工具顺序和演示型 diff。
- 当前还缺少真实模型/策略决策层本体，尚未接入真正的任务级模型决策、工具选择和步骤推进回路。
- 当前实验结果可以比较策略差异，但还不能代表真实代码任务求解能力。

因此，`Phase 9` 的主目标不是再扩展新策略，而是先把真实任务执行闭环补齐。

## 6. 实现过程中的工程规则

### 6.1 优先使用稳定结构模型

以下对象应尽量采用结构化 Python model：

- config
- runtime state
- trace events
- tool outputs
- eval specs
- 能结构化的 report 数据

### 6.2 接口保持小而稳

不要过早抽象。

但以下接口应尽早存在：

- model adapter base
- tool registry base
- trace writer
- memory manager interface
- context builder interface

### 6.3 避免过早追求“智能”

早期不要把时间花在：

- 高级 prompt 调优
- 重型 planning 框架
- embedding 检索
- 富 UI
- 多 agent 自治执行

### 6.4 重要动作必须留证据

Trace 最少应记录：

- config snapshot
- state transitions
- context build result
- model request/response summary
- tool calls/results
- reflect result
- verify result
- stop reason

### 6.5 测试环境规范

本项目在当前 Windows 开发环境中统一使用以下虚拟环境执行测试：

- `D:\jt\ANACONDA\envs_dirs\learn-claude-code`

执行测试时应显式调用该环境的 Python：

- `D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m pytest ...`
- `D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m compileall src tests`

不要默认使用系统 PATH 中的 `python` / `py`，也不要切到 Codex 内置 Python 作为首选测试环境。若该虚拟环境缺少测试依赖，应在结果中明确说明缺失依赖，而不是静默换用其他 Python。

## 7. 建议里程碑

### Milestone A

仓库可以通过：

- `python -m cli ...`

启动，并生成：

- run directory
- config snapshot
- JSONL trace
- Markdown report

### Milestone B

仓库可以在一个受控 run 中完成：

- 搜索
- 读文件
- 打补丁
- 执行命令
- 收集 diff

### Milestone C

仓库可以完成：

- 一个简单 `code_understanding` 任务
- 一个简单 `bug_fix` 任务

并生成 trace 与 report。

### Milestone D

仓库可以批量运行小型 eval 集，并输出：

- success rate
- average steps
- average tool calls
- failure distribution

### Milestone E

仓库可以在“每题独立 sandbox 目录”中运行真实任务，并具备：

- 任务级准备步骤
- 任务级验证命令
- 任务级通过标准
- 可复现实验输入态

### Milestone F

仓库可以在真实任务集上完成：

- 至少一类任务的稳定求解
- 真实 verify
- 与现有 comparison / experiment 外壳的对接

## 8. 第一批应执行的实验

在 MVP 基础设施到位后，优先比较：

### Experiment 1

`naive_recent_context` vs `file_recall_context`

问题：

- 文件级召回是否降低 `context_miss`？

### Experiment 2

`memory_off` vs `structured_memory_on`

问题：

- memory 是否减少重复探索？

### Experiment 3

`verify_failure_only_reflect` vs `low_progress_plus_verify_reflect`

问题：

- 条件 reflect 是否减少 repeated no-progress loops？

补充说明：

- 上述首批实验已经完成，可作为 `Phase 8` 基线结果保留。
- 在 `Phase 9` 完成前，不建议继续大量扩展新的策略维度。
- 更高优先级是构造“真实任务 + sandbox + 真实 verify”的实验底座。

## 9. 新会话应先做什么

如果未来要在新 AI 会话中继续本项目，建议先做：

1. 阅读：
   - `docs/DEVELOPMENT_PLAYBOOK.md`
   - `docs/DEVELOPMENT_PLAYBOOK.zh-CN.md`
   - `docs/PRD.md`
   - `docs/ARCHITECTURE.md`
   - `docs/MONTH_PLAN.md`
2. 检查当前仓库结构。
3. 确认当前已完成到哪一个 phase。
4. 从下一个未完成 phase 继续实现。
5. 除非实现现实强迫改变，否则不要重开已经确定的 MVP 决策。

## 10. 当前推荐下一步

当前推荐下一步应进入：

- 真实任务最小 schema
- 每题独立 sandbox 目录
- 任务级真实 verify
- 真实模型/策略决策层本体
- stub loop 到真实求解 loop 的替换

在这些最小闭环到位前，不要误把现有策略对比结果当成真实任务求解实验结论。
