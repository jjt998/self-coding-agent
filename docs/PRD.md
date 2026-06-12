# Self Coding Agent 产品需求文档

## 1. 项目目标

构建一个面向本地代码仓库的 coding agent harness，用于研究和学习。系统需要可用，但首要目标不是做一个外观完整的产品，而是能够比较和迭代 agent loop、上下文管理、记忆系统、工具使用和评测策略。

一个月 MVP 要证明：这个 harness 能运行本地代码任务，记录结构化 trace，评估结果，并比较不同策略变体。

## 2. 产品定位

这是一个研究型 harness，不是一个成熟 IDE 插件或商业化 coding agent 产品。

它应该能回答这些问题：

- 哪种上下文策略能减少 `context_miss`？
- 结构化 memory 是否能减少重复探索？
- 条件触发 reflect 是否能减少 `repeated_no_progress`？
- 失败到底来自上下文、工具、loop、验证，还是 memory？

## 3. MVP 范围内

- 本地仓库 CLI。
- 单 agent 执行 loop。
- 可插拔模型适配接口。
- 本地代码工作的核心工具。
- 显式状态机 loop。
- 文件级上下文召回。
- 运行时记忆。
- 结构化长期记忆。
- JSONL trace。
- trace replay。
- Markdown run report。
- 批量 eval runner。
- 策略对比 report。

## 4. MVP 暂不做

- Web UI。
- IDE 插件。
- 多 agent 协作。
- 浏览器自动化。
- 远程沙箱或云端 runner。
- GitHub PR 自动化。
- 重型 AST/LSP 符号图。
- 向量数据库或 embedding memory。
- 大型公开 benchmark 复现。
- 复杂权限系统。
- 专门的 memory 污染 A/B 实验。

## 5. 目标任务类型

MVP 支持四类任务：

- `code_understanding`：定位并解释相关代码。
- `bug_fix`：修复小型、局部 bug。
- `test_generation`：新增或改进聚焦测试。
- `refactor`：执行局部、行为保持的重构。

## 6. 核心用户流程

### 6.1 单任务运行

输入：

- 仓库路径。
- 任务指令。
- 模型配置。
- 策略配置。
- 预算限制。

输出：

- 最终状态。
- 修改文件。
- 验证结果。
- JSONL trace。
- Markdown run report。

### 6.2 批量评测运行

输入：

- eval task set。
- 模型配置。
- 策略配置。
- 固定预算。

输出：

- 每个任务的 run report。
- 聚合 eval summary。
- 结果、过程、诊断指标。
- 策略对比 report。

## 7. Agent Loop 需求

第一版 loop 是固定 baseline：

- `ingest`
- `analyze`
- `plan`
- `act`
- `observe`
- `reflect`
- `verify`
- `finalize`

`fail` 不作为显式状态。失败通过结构化 `status` 和 `stop_reason` 表示。

规则：

- 第一次进入 `act` 前必须先经过 `plan`。
- 执行过程中允许 `act <-> observe` 多轮，不强制每一轮重新 plan。
- `reflect` 只在条件触发时执行，包括验证失败、重复低价值尝试、结果冲突或预算压力。
- `finalize` 前必须至少有一次验证尝试。
- 验证失败后先进入 `reflect`，再决定继续行动、重规划、终止或人工接管。

## 8. Context 需求

上下文系统分四层：

- `task_context`：目标、成功标准、任务类型、约束、禁止事项、预算。
- `repo_context`：repo map、相关文件、关键模块、构建/测试命令、与任务相关的代码事实。
- `runtime_context`：当前计划、最近工具调用、关键观察、diff 摘要、失败路径、活跃假设。
- `memory_context`：被选中的稳定跨任务知识。

上下文注入策略：

- 高精度信息保留原文。
- 大块或历史信息先摘要。
- 大型低概率信息只做索引或引用。
- 优先保留关键性信息，而不是机械保留最新信息。

## 9. Memory 需求

### 9.1 运行时记忆

运行时记忆服务单次 run，记录：

- 当前状态。
- 当前计划。
- 已读文件。
- 已修改文件。
- 候选文件。
- 已尝试路径。
- 关键工具结果。
- 关键错误。
- verify 状态。
- diff 摘要。
- 活跃假设。
- progress/no-progress 信号。

运行时记忆比模型上下文更大。只有被选中的切片会进入 prompt。

### 9.2 长期记忆

长期记忆服务跨 run 复用。

它应该存储稳定、低噪音、高复用价值的信息：

- repo 稳定事实。
- 构建和测试命令。
- 关键模块和入口点。
- 用户偏好。
- 成功修复模式。
- 当前 repo 上特定任务类型的经验。

默认写入规则：

- 只有任务成功且验证通过后，才写入长期记忆。

默认检索方式：

- 按 repo、任务类型、标签、路径、关键词做结构化过滤。
- MVP 不使用向量数据库或 embedding 检索。

### 9.3 Memory 污染范围

MVP 包含基础污染感知：

- 诊断标签：`memory_pollution`。
- 运行时证据：`memory_conflict`。
- schema 预留 confidence、conflict count、memory status 等字段。

MVP 不做专门的 memory 污染实验。

## 10. Tool 需求

MVP 核心工具：

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

工具要求：

- 结构化输入。
- 结构化输出。
- 记录 status、error、duration 和 metadata。
- 限制 workspace 路径。
- 命令超时。
- 阻断危险命令。
- 每次工具调用都写入 trace。

## 11. Eval 需求

eval 必须从第一周开始做。

指标分为：

- `result_metrics`：success、validation pass、expected files touched、unexpected changes。
- `process_metrics`：steps、tool calls、verify count、reflect count、duration。
- `diagnostic_metrics`：失败类型和证据。

MVP 任务集规模：

- 12 到 20 个任务。
- 每类目标任务 3 到 5 个。

## 12. 诊断标签

MVP 诊断标签：

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

每个诊断结果应该包含 evidence 和 source：

- `rule`
- `llm_judge`
- `human`

## 13. Stop Reasons

MVP stop reasons：

- `success`
- `step_budget_exceeded`
- `tool_budget_exceeded`
- `repeated_no_progress`
- `verification_failed`
- `unsafe_action_blocked`
- `environment_blocked`
- `need_human_input`

## 14. MVP 成功标准

一个月后项目应能做到：

- 通过 CLI 运行本地 repo 任务。
- 执行 plan、act、observe、reflect、verify、finalize。
- 通过受控工具修改文件。
- 生成 JSONL trace。
- 生成 Markdown run report。
- 运行固定 eval task set。
- 比较至少两种策略。
- 输出失败类型分布。
- 至少产出一条关于 context、memory 或 reflect 策略的可解释实验结论。
