# 任务生成指南

## 目的

本文档用于在新会话中快速恢复“下一批开发任务应该怎么生成”的规则。

当用户在新会话中艾特本文档，或说“根据任务生成指南继续生成下一批任务”时，AI 应把本文档作为任务生成入口，而不是直接从零猜测项目方向。

本文档不替代 `docs/CURRENT_STATUS.md`、`docs/PHASE_PROGRESS.md`、`docs/ARCHITECTURE.md` 或 `docs/HARNESS_IMPROVEMENT_LOG.md`。它的作用是把这些事实源转成下一轮可执行任务计划。

## 新会话使用方式

用户可以直接说：

```text
请阅读 docs/TASK_GENERATION_GUIDE.md，帮我生成下一批开发任务。
```

AI 应按以下顺序执行：

1. 阅读 `docs/TASK_GENERATION_GUIDE.md`。
2. 阅读 `docs/CURRENT_STATUS.md` 和 `docs/PHASE_PROGRESS.md`，确认当前阶段和最近改动。
3. 阅读 `docs/HARNESS_IMPROVEMENT_LOG.md`，只提取已经固化或正在观察的 harness 改进方向。
4. 必要时阅读 `docs/ARCHITECTURE.md`、`docs/RUN_CHAIN.html`、`docs/USAGE_GUIDE.md`，确认架构边界和用户使用路径。
5. 查看最近真实 run 的 `trace.jsonl`、`report.md` 或 eval summary，把真实失败现象转成任务主题。
6. 生成一批完整任务，每个任务都应包含 Summary、Key Changes、Test Plan、Docs And Process、Assumptions。

## 任务生成总原则

- 任务必须服务于真实 coding agent harness 的可观测、可诊断、可复现、可迭代。
- 优先解决真实 run 暴露的问题，不优先追逐“看起来智能”的功能。
- 每轮任务应该是一个完整主题，而不是过小切片；但也不能大到同时改动无关系统。
- 每轮任务必须尽量闭环：代码、测试、文档、回归命令、边界说明一起给出。
- harness 负责保真压缩事实，LLM 负责解释事实并重规划。不要把过多主观判断硬编码到 harness。
- 对真实任务失败的处理优先追根因，不做只遮住报错的补丁。
- 新增能力要能在 trace、report、eval 或 comparison 中被观察到，否则难以判断是否真的改善。

## 当前项目边界

生成任务时默认遵守以下边界，除非用户明确要求突破：

- 不恢复 `rule_based` 模型。
- 不把 API key 写入代码、trace、report 或文档示例。
- 不新增第三方依赖，除非收益非常明确且用户同意。
- 不实现 CLI 单次传 `verify_commands` / `verify_rules`，除非用户明确排期。
- 不随意放开 `runtime.max_steps` 的默认语义；可以配置测试，但不要把轮数预算暴露给模型。
- 不把完整大文件无条件塞进模型上下文。
- 不把 `docs/HARNESS_IMPROVEMENT_LOG.md` 当作普通进度文档随手追加；只有用户明确说“写入/更新到改进文档”时才追加。
- 新增或修改注释、docstring、说明性文案默认使用 UTF-8 中文；稳定机器字段、枚举值、trace event、JSON key 保持英文。

## 优先任务来源

生成下一批任务时，优先从以下来源提炼主题：

1. 最近真实 run 的失败链路。
2. `trace.jsonl` 中反复出现的模型错误、工具失败、验证失败。
3. `report.md` 中用户难以理解或定位的诊断信息。
4. `docs/HARNESS_IMPROVEMENT_LOG.md` 中标记为仍需观察的问题。
5. `docs/CURRENT_STATUS.md` 与 `docs/PHASE_PROGRESS.md` 中最新阶段的下一步。
6. sample eval/comparison smoke 中暴露的 taxonomy、report、sandbox 或验证口径问题。

不要优先从早期历史计划里机械抽任务。历史文档只能作为背景，当前行为以最新状态和真实 run 为准。

## 任务主题选择规则

每批任务建议生成 3 到 5 个主题。主题之间应有清晰顺序。

优先级从高到低：

1. 阻止真实 run 继续执行的硬错误，例如 Python traceback、非法工具输入未收口、模型响应解析失败。
2. 导致模型反复失败的上下文问题，例如缺少源码片段、范围读取不足、feedback 压缩丢失关键信息。
3. 影响任务完成判断的验证问题，例如 verify 规则不足、failure taxonomy 不稳定、missing verification 诊断不清晰。
4. 影响排障体验的问题，例如 trace 难读、report 缺关键摘要、comparison delta 不可读。
5. 使用手册和实验脚手架问题，例如 demo task 不够真实、sample batch 覆盖不足。
6. 架构清理和命名问题，例如旧 stub 语义、过期文档、状态图不一致。

## 任务粒度标准

一个好任务应该满足：

- 能用一句话说明要解决的真实问题。
- 能在一次开发回合内完成实现、测试和文档更新。
- 有明确不做什么，避免范围蔓延。
- 有可执行回归命令。
- 有真实 run 或测试可以验证收益。

一个任务太小的信号：

- 只改一个字段名，但没有用户可见收益。
- 只补一条测试，不触及真实问题。
- 只写文档，却没有把文档接入当前工作流。

一个任务太大的信号：

- 同时改 loop、model、tools、verify、eval、CLI 和 docs，且不是同一个根因。
- 同时引入新工具、新验证规则、新 CLI 参数和新实验体系。
- 没有明确回归命令能证明改动稳定。

## 标准任务格式

每个任务必须使用以下结构：

```markdown
# Phase 9：任务标题

## Summary

用 2 到 4 句话说明本轮解决什么真实问题、为什么现在做、明确不做什么。

## Key Changes

- 改动点 1。
- 改动点 2。
- 改动点 3。

## Test Plan

- 更新或新增哪些测试。
- 需要覆盖哪些成功路径和失败路径。
- 回归命令。

## Docs And Process

- 修改前需要归档哪些文档。
- 需要更新哪些当前文档。
- 是否需要更新 `docs/HARNESS_IMPROVEMENT_LOG.md`。

## Assumptions

- 本轮不做的范围。
- 关键默认值。
- 兼容性约束。
```

如果任务只涉及文档或实验目录，也要保留 Test / Verification 与 Assumptions，但可以更轻量。

## 生成任务时必须检查的问题

生成每个任务前，AI 应先在心里回答：

- 这个任务来自哪个真实问题或当前状态缺口？
- 它是否会改变 loop、model、tools、verify、eval、CLI、docs 中的哪一层？
- 它是否会引入新的 trace 字段、report 展示或 failure taxonomy？
- 它是否需要更新 `docs/RUN_CHAIN.html` 或 `docs/ARCHITECTURE.md`？
- 它是否需要新增 fake model 测试，避免调用真实模型？
- 它是否会影响 sandbox 保留/删除策略？
- 它是否可能泄露 API key、原始大文件内容或过长模型响应？
- 它的成功能否通过 pytest、sample eval、comparison smoke 或真实 demo run 观察到？

## 常见任务方向

### 上下文与文件读取

适合在真实 run 中出现以下问题时生成：

- 模型反复读取同一文件。
- 模型不知道目标函数在哪一行。
- `apply_patch.old_text` 总是猜错。
- 大文件摘要不足，模型需要具体范围。
- 跨轮已读取片段没有被保留。

任务可围绕 `context_snapshot`、`read_file`、`read_file_range`、`file_context_cache`、`previous_reflect.recent_tool_results` 生成。

### 工具调用与编辑可靠性

适合在真实 run 中出现以下问题时生成：

- 模型传入未知参数。
- `tool_input` 类型错误。
- 工具层抛 Python traceback。
- 文本匹配失败但行号定位明确。
- Windows 命令或编码问题导致非业务失败。

任务可围绕 `TOOL_SCHEMAS`、工具入参校验、`ToolExecution` 结构化失败、`replace_lines`、`run_command` 摘要生成。

### Reflect 与重规划

适合在真实 run 中出现以下问题时生成：

- 下一轮模型没有利用上一轮失败事实。
- feedback 过度主观，替模型下判断。
- feedback 缺少关键源码、失败工具、验证失败细节。
- `donelist` 没有承接跨轮意图。

任务应遵守原则：harness 压缩事实，LLM 解释事实。

### Verify 与任务完成判断

适合在真实 run 中出现以下问题时生成：

- 任务缺少显式验证。
- verify rule 表达不了真实完成条件。
- 验证失败在 report 中不可读。
- failure taxonomy 聚合不稳定。

任务可围绕 `verify_commands`、`verify_rules`、`VerificationResult`、eval taxonomy、comparison delta 生成。

### Trace、Report 与实验体验

适合在真实 run 中出现以下问题时生成：

- trace 太难读。
- report 看不出模型为什么失败。
- comparison delta 无法定位策略差异。
- sample batch 不够真实。
- sandbox 输出难以复盘。

任务可围绕 `model_raw_response`、`model_decision`、`reflect_feedback`、`report.md`、`summary.json`、`summary.md`、`docs/RUN_CHAIN.html` 生成。

## 任务排序建议

如果同时发现多个问题，建议按以下顺序组织：

1. 先修会导致进程崩溃或 traceback 的问题。
2. 再修模型上下文不足导致的重复失败。
3. 再修验证和诊断口径。
4. 再补 report、comparison 和文档体验。
5. 最后做样例任务扩展和实验沉淀。

## 输出下一批任务时的推荐格式

AI 给用户输出下一批主题时，先给简短排序说明，再给任务清单：

```markdown
建议下一批按这个顺序推进：

1. 任务一标题
   解决什么问题，为什么先做。

2. 任务二标题
   解决什么问题，依赖任务一的哪些结果。

3. 任务三标题
   解决什么问题，如何验证。
```

如果用户要求“展开第 N 个任务”，再输出完整的 `PLEASE IMPLEMENT THIS PLAN` 格式。

如果用户要求“直接生成完整计划”，则一次性输出 3 到 5 个完整计划，但要避免过长。优先输出最值得做的 1 到 2 个完整计划，其余给标题和摘要。

## 任务计划中的回归命令约定

默认使用当前 Windows 虚拟环境：

```powershell
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m pytest -q
```

针对局部任务，应给出更小回归命令，例如：

```powershell
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m pytest tests\test_loop.py tests\test_model.py -q
```

真实 demo run 命令可使用：

```powershell
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_complete_task_batch.json `
  --repo-root sandbox_experiments\repos\demo_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default
```

测试任务默认使用 fake model 或 mock，不应依赖真实 API。

## 归档与文档规则

涉及代码行为变化的开发任务，通常需要：

- 修改前归档 `docs/CURRENT_STATUS.md` 到 `dev_process_history/`。
- 修改前归档 `docs/PHASE_PROGRESS.md` 到 `dev_process_history/`。
- 更新 `docs/CURRENT_STATUS.md`。
- 更新 `docs/PHASE_PROGRESS.md`。
- 如果影响架构，更新 `docs/ARCHITECTURE.md`。
- 如果影响使用路径，更新 `README.md` 和 `docs/USAGE_GUIDE.md`。
- 如果影响链路理解或上下文窗口，更新 `docs/RUN_CHAIN.html`。

`docs/HARNESS_IMPROVEMENT_LOG.md` 的特殊规则：

- 只有用户明确说“写入/更新到 harness 改进文档/日志”时才追加。
- 追加时默认使用 STAR 法则。
- 必须写清楚背景、改之前的问题、改了什么、真实结果、收益、是否固化。

## 生成任务时不要做的事

- 不要把“想法”写成“已经验证的收益”。
- 不要用单个真实 run 过度宣称泛化能力。
- 不要把历史 Phase 3 stub 语义当作当前能力。
- 不要生成只有自然语言提示词修改、没有验证方式的任务。
- 不要把用户的 API key、真实密钥或授权头写进任务计划。
- 不要建议删除 sandbox、runs 或未提交改动，除非用户明确要求。
- 不要为了追求智能感而引入向量库、浏览器自动化或复杂 planner，除非当前问题确实需要。

## 当前可优先生成的后续主题候选

以下只是候选，不是必须执行。新会话应结合最新 run 再取舍：

1. 大文件上下文策略真实 run 复盘：验证 `structure_summary`、`read_file_range`、`file_context_cache` 是否减少重复读文件和 `old_text_not_found`。
2. `run_command` 反馈增强：把关键 stdout/stderr、返回码、命令失败原因压缩进 `previous_reflect`，避免模型重复运行无效命令。
3. Trace 可读性工具：生成按事件折叠的本地 HTML/Markdown trace viewer，降低人工复盘成本。
4. Verify rule 下一批扩展：围绕真实 demo 任务补充更贴近代码行为的断言，但不滥加规则类型。
5. Sandbox 与实验任务治理：让 demo task、preserved sandbox、实验输出更容易复用和清理。
6. 大仓库任务上下文选择实验：观察模型是否能基于结构摘要选择必要上下文，而不是追求全文。

## 一句话准则

下一批任务不是从功能清单里“挑一个好看的”，而是从真实 run 的失败证据里提炼一个能被测试和文档固化的 harness 改进闭环。

