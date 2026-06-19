# Harness 改进文档

这份文档用于记录 self-coding-agent harness 的进步史，重点沉淀上下文构建、模型重规划、工具调用、验证规则、失败诊断和报告可读性的改进过程。

## 使用规则

- 当一次改进已经通过真实 run 或测试观察到效果后，由你明确说“更新到改进文档中”，再追加记录。
- 未经确认的想法只放在“待观察问题”里，不写成已固化结论。
- 记录里可以保留稳定机器字段，例如 `runtime_feedback`、`old_text_not_found`、`verify_rules`。
- 不记录 API key、Authorization header 或任何真实密钥。

## 固定记录格式

```markdown
### YYYY-MM-DD：改进主题

- 问题现象：
- 改进动作：
- 预期改善：
- 实际反馈：
- 是否固化：
```

## 当前已知问题

- `read_file` 关键片段反馈已经在 demo bugfix 任务中观察到正向效果，但还需要更多任务验证它对不同文件长度、不同 patch 形态是否稳定。
- `planned_actions` 已重新定位为本轮 `tool_calls` 的可读说明，不再作为下一轮计划来源；仍需继续观察模型是否能稳定把跨轮安排写入 `cross_round_plan`。
- `run_command` 与 `git_diff` 的下一轮摘要仍偏轻量，后续可以继续补 stdout 关键行和 diff 短摘要，帮助模型修复“patch 成功但语义仍错”的情况。
- Windows CLI 任务中，模型仍可能输出 emoji 或中文符号，导致 GBK 控制台出现 `UnicodeEncodeError`；后续应把“默认使用 ASCII stdout/stderr”固化到 prompt 或 runtime rule。

## 下一步观察指标

- 第二轮模型的 `runtime_feedback.recent_tool_results` 是否包含目标文件 `path` 和短源码片段。
- `old_text_not_found` 后，下一轮反馈是否包含 `failed_old_text_excerpt` 和候选源码片段。
- 模型是否减少编造 `apply_patch.old_text` 的情况。
- 同一个 demo bugfix 任务是否更容易在第二轮产生真实 diff。
- `trace.jsonl` 是否保持可读，没有被大段文件全文淹没。
- `cross_round_plan` 是否能稳定承接跨轮安排，并通过 `runtime_feedback.previous_cross_round_plan` 影响下一轮 plan。
- 工具入参类型校验是否能稳定把非法工具输入收口为 `ModelResponseError/model_error`，避免 Python traceback 泄漏到工具层。

## 改进记录

### 2026-06-19：`read_file` 关键片段与 `old_text_not_found` 反馈驱动重规划

- 问题现象：demo todo bugfix 任务中，模型多次读取了 `todo_app.py`，但旧版 `runtime_feedback.recent_tool_results` 只告诉下一轮“读了多少行”，没有给出可复制的源码片段；当 `apply_patch` 返回 `old_text_not_found` 后，下一轮仍容易猜错 `old_text` 或误判修复方式。
- 改进动作：增强 `recent_tool_results`，让 `read_file` 摘要携带 `path`、短 `content_excerpt`、片段行号和 `excerpt_reason`；让 `apply_patch old_text_not_found` 摘要携带 `failed_old_text_excerpt` 与 `new_text_excerpt`；在 `reflect_feedback.replan_constraints.must_address` 中加入 `use_exact_old_text_from_read_file`。
- 预期改善：模型在下一轮 plan 中能直接引用最近 `read_file` 片段中的真实源码行，减少编造 `apply_patch.old_text`，并更容易产生真实 diff。
- 实际反馈：真实 eval run `run-20260619-140710-ffa68ca3` 通过。第 3 轮 `apply_patch` 仍因 `old_text_not_found` 失败，但 reflect 明确写入 `use_exact_old_text_from_read_file`；第 4 轮模型引用真实源码 `status = "todo" if task.get("done") else "done"`，成功 patch 为 `status = "done" if task.get("done") else "todo"`，`git_diff` 检测到 `todo_app.py` 变更，最终 `success_rate=1.0`、`outcome=passed_cleanly`、`stop_reason=completed`。
- 是否固化：已作为当前 harness 的有效改进固化，并通过本次 demo bugfix 真实 run 验证；后续仍需用更多任务观察泛化稳定性。

### 2026-06-19：多轮 reflect 反馈帮助模型从 patch 失败和 Windows 编码失败中恢复

- 问题现象：demo todo complete 任务 `run-20260619-155525-12419f63` 中，模型第 1 轮只读文件没有产生进展；第 2 轮两次 `apply_patch` 因 `old_text_not_found` 失败；第 3 轮成功实现 `complete` 子命令后，验证仍因 Windows GBK 控制台无法输出 emoji 触发 `UnicodeEncodeError`；第 4 轮尝试修复非 ASCII 输出时又遇到一次 `old_text_not_found`。
- 改进动作：现有 harness 将每轮 `model_raw_response`、`model_decision`、`recent_tool_results`、`progress_observed`、`reflect_feedback`、失败验证检查和失败工具证据持续写入 trace，并通过 `runtime_feedback.previous_reflect_feedback` 与 `previous_cross_round_plan` 传给下一轮 plan；`reflect_feedback.replan_constraints.must_address` 持续要求模型处理 `fix_failing_verification_checks`、`fix_failed_tool_or_command` 和 `use_exact_old_text_from_read_file`。
- 预期改善：模型即使前几轮只读文件、patch 失败或实现后验证失败，也能通过下一轮反馈看到明确失败原因和源码证据，继续重规划而不是停在一次失败上；报告和 trace 能解释每一轮为什么失败、下一轮如何调整。
- 实际反馈：真实 eval run `run-20260619-155525-12419f63` 最终通过。该 run 共 5 轮、4 次 reflect、18 次工具调用、5 次验证，最终 `success_rate=1.0`、`outcome=passed_cleanly`、`stop_reason=completed`。第 5 轮模型读取真实源码后成功把 `✅ 已完成任务` / `❌ 错误` 等非 ASCII 输出替换为 `Completed task #{task_id}: ...` 与 `Error: task #{task_id} not found`，`python todo_app.py complete 1` 返回 0，`json_file_value_equals` 与 diff 规则也全部通过。
- 是否固化：已确认这是一次明确的 harness 改进成功案例，说明多轮 reflect、最近工具结果摘要、原始模型返回日志和跨轮计划能支撑真实任务从连续失败中恢复；新增待固化经验是 Windows CLI 任务默认应优先使用 ASCII stdout/stderr，除非任务明确要求 Unicode。

### 2026-06-19：结构化工具 schema、跨轮计划与工具入参校验固化

- 问题现象：模型曾把 `read_file` 入参写成不存在的 `limit`，也曾把 `apply_patch.new_text` 返回为 `null`，导致非法工具输入一路打到工具层甚至触发 Python traceback；同时，旧 prompt 主要用自然语言描述工具约束，模型不容易稳定理解每个工具的准确入参。另一个语义混淆是 `planned_actions` 被误当作跨轮计划，但它本质更适合表达本轮工具调用意图。
- 改进动作：模型请求中加入结构化 `decision_schema` 与结构化可用工具列表/入参 schema，而不是只依赖自然语言约束；新增 `cross_round_plan` 表示跨轮整体计划，并通过 `runtime_feedback.previous_cross_round_plan` 传给下一轮模型；明确 `planned_actions` 只描述本轮 `tool_calls` 实际要做的事情，主要用于 trace/report 可读性，不作为下一轮 plan 的状态来源；新增工具入参类型校验，使 `apply_patch.new_text = null` 这类非法输入收口为 `ModelResponseError/model_error`；`CoreToolRunner.apply_patch()` 也增加防御式 `invalid_tool_input` 返回；`model_decision` trace、plan state result 和 report 模型摘要均展示 `cross_round_plan`。
- 预期改善：模型更容易按准确 schema 调用工具，非法输入能在模型响应层被清晰诊断，不再变成底层 traceback；跨轮规划和本轮行动分工更清楚，下一轮模型可以从 `previous_cross_round_plan` 继承整体安排，而不是误读上一轮 `planned_actions`。
- 实际反馈：相关改动后，全量测试已通过 `89 passed`；后续真实 demo complete run 中，`cross_round_plan` 在每轮模型决策和报告里可见，并与 `runtime_feedback.previous_cross_round_plan` 一起支撑第 5 轮继续修复直到验证通过。工具输入非法时现在会以模型响应错误收口，避免 `apply_patch.new_text = null` 继续打到 `Path.write_text()` 产生 `TypeError` traceback。
- 是否固化：已固化为当前 harness 的模型接口与工具执行安全边界；后续继续观察结构化 schema 是否能减少未知入参、空值入参和本轮计划/跨轮计划混淆。

### 2026-06-19：Windows CLI 输出默认 ASCII 的 prompt/runtime rule 候选

- 问题现象：demo todo complete 任务中，模型实现 `complete` 子命令时加入 `✅`、`❌` 和中文提示文本，验证命令在 Windows GBK 控制台下触发 `UnicodeEncodeError`，导致实现逻辑已经接近正确但任务验证失败。
- 改进动作：建议在 prompt 或 runtime rule 中加入明确约束：Windows CLI 工具默认使用 ASCII stdout/stderr，除非任务明确要求 Unicode；例如优先输出 `Completed task #1: ...`、`Error: task #1 not found`，避免 emoji、全角符号和非必要中文输出。
- 预期改善：减少 Windows 控制台编码导致的非业务失败，让模型把注意力集中在功能语义和验证规则上；对于 CLI demo、eval task 和真实 Windows 仓库任务，验证通过率应更稳定。
- 实际反馈：本次 run 的第 5 轮人工观察到模型将非 ASCII 输出替换为 ASCII 后，`python todo_app.py complete 1` 返回 0，验证全部通过。该经验还未正式写入 prompt/runtime rule，因此作为待固化改进项继续观察。
- 是否固化：尚未固化到模型提示或 runtime rule；已作为明确 backlog 记录，下一轮可实施并用同类 Windows CLI 任务回归验证。
