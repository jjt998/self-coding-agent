# 2026-06-11 项目规划对话导出

## 1. 对话目的

本次对话围绕一个新的 `coding agent` 项目展开，目标是在一个月内构建一个可研究、可迭代、可比较的本地代码仓 `coding agent harness`，而不是只做一个一次性 demo。

本次对话重点不是开始编码，而是：

- 明确项目定位
- 收敛 MVP 范围
- 固定关键技术决策
- 设计可持续迭代的文档体系
- 为未来新会话恢复开发上下文

## 2. 项目定位

项目最终定位被确定为：

> 一个面向本地代码仓的研究型 coding agent harness，用于系统研究 agent loop、上下文管理、记忆系统、tool use、trace、replay 和 eval，并支持可比较、可迭代的实验。

重点不是：

- 做最强 agent
- 做 IDE 插件
- 做浏览器自动化 agent
- 做大而全的平台

重点是：

- 可观测
- 可评测
- 可复盘
- 可替换策略
- 可比较不同设计

## 3. 用户明确给出的需求方向

用户明确确认了以下方向：

- 目标偏研究/学习，同时应具备可使用性，而不是花瓶。
- agent 任务尽量全面，覆盖：
  - 代码理解
  - 小 bug 修复
  - 补测试
  - 重构
- 第一版运行环境先支持本地仓库 CLI。
- 重点研究：
  - agent loop
  - 上下文管理
  - 记忆系统
  - tool use
  - eval
- 模型采用可插拔设计。
- 成品目标是一套可比较、可迭代的 harness 框架。

## 4. 对 Agent Loop 的收敛结论

经过多轮解释与追问，最终固定第一版 loop baseline 为显式状态机：

- `ingest`
- `analyze`
- `plan`
- `act`
- `observe`
- `reflect`
- `verify`
- `finalize`

额外规则：

- `fail` 不作为显式状态，而作为结构化结束结果存在。
- 第一次 `act` 前必须先 `plan`。
- 执行过程中允许 `act <-> observe` 多轮，不要求每轮都重新计划。
- `reflect` 不是每步固定执行，而是条件触发。
- `finalize` 前必须至少经过一次 `verify`。
- `verify` 失败优先进入 `reflect`，由 `reflect` 决定继续、重计划、终止或人工接管。

### 4.1 Reflect 的定位

`reflect` 被明确定位为：

- 不是形式化总结
- 而是条件触发的元决策阶段

主要触发条件：

- 验证失败
- 连续低进展
- 工具结果没有新信息
- 同一路径反复尝试无改善
- 计划与结果冲突
- 接近预算上限

### 4.2 停止条件

第一版硬限制收敛为：

- `step budget`
- `tool call budget`

建议 stop reason：

- `success`
- `step_budget_exceeded`
- `tool_budget_exceeded`
- `repeated_no_progress`
- `verification_failed`
- `unsafe_action_blocked`
- `environment_blocked`
- `need_human_input`

## 5. 对 Context 的收敛结论

Context 被明确定义为独立模块，而不是简单 prompt 拼接。

采用四层结构：

- `task_context`
- `repo_context`
- `runtime_context`
- `memory_context`

### 5.1 Task Context

应包含：

- 用户目标
- 成功标准
- 任务类型标签
- 任务摘要
- 约束条件
- 禁止事项
- 预算要求

结论：

- 这些内容仍属于 task 层
- 不建议额外再拆一层
- 但在 task 层内部应结构化分字段

### 5.2 Repo Context

应包含：

- 仓库结构摘要
- 关键模块
- 入口点
- 构建/测试命令
- 与当前任务相关的候选文件和模块事实

### 5.3 Runtime Context

应包含：

- 当前阶段计划
- 最近几步工具调用
- 关键工具结果摘要
- 当前 diff 摘要
- 已尝试路径
- 最近错误信息
- 待验证假设

期间曾讨论是否改名为 `progress_context`，最终建议实现层优先保持 `runtime_context` 或 `progress_context` 这种更稳的命名。

### 5.4 Memory Context

应包含：

- 跨任务稳定事实
- 高价值 repo 知识
- 用户偏好
- 成功经验的结构化条目

### 5.5 上下文注入策略

对于进入模型上下文的内容，确定了三种处理方式：

- 原文注入
- 摘要注入
- 只做索引，按需再取

原文适合：

- 当前任务目标
- 最近 verify 错误
- 当前活跃代码片段
- 当前测试片段

摘要适合：

- 大文件
- 长工具输出
- 历史尝试
- diff 汇总

索引适合：

- 全 repo 文件列表
- 全量 trace
- 长期记忆库全量内容
- 低概率相关大块代码

## 6. 对 Recall 的收敛结论

第一版明确采用：

- 文件级召回
- 辅以轻量关键词搜索和轻量符号搜索

不做：

- 重型 AST/LSP 符号图
- 多语言深分析索引系统

文件级召回流程确定为：

1. 从任务、错误、测试、最近结果中提取线索
2. 将线索映射到候选文件
3. 对候选文件按相关性排序
4. 读取 top-k 文件的摘要或命中片段
5. 只把高价值片段注入当前上下文

## 7. 对 Memory 的收敛结论

Memory 被明确拆成两类：

- 运行时记忆
- 长期记忆

### 7.1 运行时记忆

服务于单次 run，应结构化记录：

- 当前计划
- 已读文件
- 已改文件
- 候选文件
- 已尝试路径
- 关键工具结果
- 关键错误
- 当前 diff
- verify 状态
- 当前假设
- progress/no-progress 信号

### 7.2 长期记忆

服务于跨 run 复用，应只记录稳定、高价值、低噪音信息：

- repo 稳定事实
- 构建和测试命令
- 关键模块说明
- 用户偏好
- 成功修复模式

### 7.3 长期记忆检索策略

第一版不采用向量库和 embedding 检索。

采用：

- 结构化条目
- 标签过滤
- 任务类型过滤
- 路径过滤
- 关键词搜索

原因：

- 第一版记忆量不大
- 结构化检索更易诊断和对比
- embedding 会过早增加复杂度

### 7.4 Memory 污染策略

结论是：

- 第一版要有 memory 污染感知
- 但不把 memory 污染处理做成核心实验

第一版纳入：

- `memory_pollution` 诊断标签
- `memory_conflict` 运行时证据
- 结构化字段预留：
  - `verified`
  - `confidence`
  - `conflict_count`
  - `status`

第一版不纳入：

- 专门的 memory 污染 A/B 实验
- 错误记忆注入 benchmark
- 复杂自动隔离和过期策略

## 8. 对 Tool Layer 的收敛结论

第一版核心工具固定为 5 个：

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

工具层要求：

- 结构化输入
- 结构化输出
- 记录状态、错误、耗时、元数据
- 工作区路径限制
- 命令超时
- 危险命令阻断
- 所有调用进入 trace

## 9. 对 Eval 的收敛结论

Eval 被明确要求从第一周就进入设计与实现，而不是最后补。

### 9.1 任务类型

第一版任务集包含四类：

- `code_understanding`
- `bug_fix`
- `test_generation`
- `refactor`

### 9.2 任务集规模

第一版建议：

- 每类 3 到 5 个
- 总计 12 到 20 个任务

### 9.3 指标分类

Eval 指标分三类：

- `result_metrics`
- `process_metrics`
- `diagnostic_metrics`

### 9.4 诊断标签

第一版诊断标签固定为：

- `context_miss`
- `context_noise`
- `wrong_plan`
- `wrong_tool_choice`
- `tool_failure`
- `edit_failure`
- `verification_gap`
- `repeated_no_progress`
- `budget_exhausted`
- `memory_pollution`

并要求记录：

- `primary_failure`
- `secondary_failures`
- `evidence`
- `diagnosis_source`

### 9.5 实验策略

第一版建议的三组核心实验：

1. `context` 策略对比
2. `memory off/on` 对比
3. `reflect` 触发规则对比

## 10. 对 Trace / Replay / Report 的收敛结论

第一版 trace 使用：

- `JSONL`

一行一个结构化事件。

主要事件类型包括：

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

Report 采用：

- Markdown

包括：

- 单次 run report
- batch eval summary

Replay 第一版优先支持：

- trace replay

## 11. 对一个月计划的收敛结论

项目被压成 4 周：

### 第 1 周

目标：

- 单任务最小闭环
- CLI、trace、状态机骨架、工具接口

### 第 2 周

目标：

- context 与 memory
- 文件级召回
- 条件 reflect

### 第 3 周

目标：

- eval task schema
- eval runner
- metrics 与 diagnostics

### 第 4 周

目标：

- 策略对比实验
- baseline 报告
- 研究问题的初步结论

## 12. 关于“是否直接开始编码”的结论

明确结论为：

- 不是直接开始大段写 agent 逻辑
- 而是先搭“可迭代的控制面骨架”

建议顺序：

1. 固化开发基线
2. 搭项目骨架
3. 先做 trace 与 config snapshot
4. 先做最小 eval runner
5. 给 loop/context/memory 留策略接口
6. 再逐步补 agent 功能

## 13. 本次对话中产出的文档体系

### 13.1 第一批文档

最先确定并创建了：

- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/MONTH_PLAN.md`
- `docs/DEVELOPMENT_PLAYBOOK.md`

这些文档用于固定：

- 项目目标与范围
- 技术架构
- 一个月节奏
- 实现顺序与恢复规则

### 13.2 中英文补齐

后续又补充了中英文文档体系，形成：

- `PRD` / `PRD.zh-CN`
- `ARCHITECTURE` / `ARCHITECTURE.zh-CN`
- `MONTH_PLAN` / `MONTH_PLAN.zh-CN`
- `DEVELOPMENT_PLAYBOOK` / `DEVELOPMENT_PLAYBOOK.zh-CN`

### 13.3 控制面文档

为了支撑未来会话恢复与持续推进，又新增：

- `docs/DECISIONS.md`
- `docs/DECISIONS.zh-CN.md`
- `docs/CURRENT_STATUS.md`
- `docs/CURRENT_STATUS.zh-CN.md`
- `docs/PHASE_PROGRESS.md`
- `docs/PHASE_PROGRESS.zh-CN.md`

用途：

- `DECISIONS`：记录已拍板技术决策
- `CURRENT_STATUS`：记录当前做到哪
- `PHASE_PROGRESS`：记录各阶段进度台账

### 13.4 轻量入口文档

为避免未来新会话一开始加载过多文档，又增加了：

- `docs/SESSION_ENTRY.md`
- `docs/SESSION_ENTRY.zh-CN.md`

用途：

- 告诉新会话先读什么
- 告诉新会话不要预加载全部文档
- 告诉新会话当前应该继续哪个 phase

## 14. 对未来新会话提示词策略的收敛结论

明确结论为：

- 不应让新会话一开始加载 11 份文档
- 应采用轻量加载策略

默认新会话只需先读：

- `SESSION_ENTRY`
- `CURRENT_STATUS`
- `PHASE_PROGRESS`
- `DEVELOPMENT_PLAYBOOK`

其他文档按需再读。

## 15. 关于“将这套过程做成可复用 skill”的讨论结果

用户提出，希望将“从需求讨论到文档落地”的长流程沉淀为一个可复用 skill，以便未来开发新产品时不再重复经历同样长对话。

因此创建了一个 skill 草案：

- `skills/requirements-to-delivery-planning/SKILL.md`
- `skills/requirements-to-delivery-planning/references/document-set.md`

该 skill 的目的在于：

- 驱动结构化需求讨论
- 冻结关键 MVP 决策
- 产出最小必要文档集
- 设计新会话恢复方式
- 在文档足够后切换到实现，而不是无限扩文档

## 16. 本次对话结束时的建议下一步

到当前阶段为止，明确建议为：

- 停止继续扩文档
- 进入 `Phase 1：脚手架与控制面`

优先实现：

- `pyproject.toml`
- `src/self_coding_agent/`
- `tests/`
- `configs/`
- `eval_tasks/`
- `runs/`

然后实现：

- 基础 config models
- trace event models
- trace writer
- CLI entrypoint

## 17. 当前仓库中与本次对话相关的重要产物

### 文档

- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/MONTH_PLAN.md`
- `docs/DEVELOPMENT_PLAYBOOK.md`
- `docs/DEVELOPMENT_PLAYBOOK.zh-CN.md`
- `docs/DECISIONS.md`
- `docs/DECISIONS.zh-CN.md`
- `docs/CURRENT_STATUS.md`
- `docs/CURRENT_STATUS.zh-CN.md`
- `docs/PHASE_PROGRESS.md`
- `docs/PHASE_PROGRESS.zh-CN.md`
- `docs/SESSION_ENTRY.md`
- `docs/SESSION_ENTRY.zh-CN.md`

### Skill 草案

- `skills/requirements-to-delivery-planning/SKILL.md`
- `skills/requirements-to-delivery-planning/references/document-set.md`

## 18. 备注

这份导出文件是基于本次对话生成的高信号摘要，不是逐字聊天记录。

它的用途是：

- 帮助未来快速恢复本次对话的核心结论
- 为新会话、新项目或文档审计提供上下文
- 保留从需求讨论到文档落地的全过程结果
