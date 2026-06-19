# Harness 改进文档

这份文档用于记录 self-coding-agent harness 的进步史，重点沉淀上下文构建、模型重规划、工具调用、验证规则、失败诊断和报告可读性的改进过程。

## 使用规则

- 当你明确说“把这次改动写到 `harness_improvement_log` 中”或同义表达时，默认触发本文档记录规范：用 STAR 法则追加一条改进记录，必须覆盖背景/问题、采取的动作、真实 run 或测试结果、带来的收益和是否固化；除非你额外指定格式，否则不再反复确认。
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

### 2026-06-19：合并 `observe` 与 `reflect`，让 harness 只压缩事实而不替模型判断进展

- Situation（背景）：demo todo app 的真实 eval run `eval-demo_todo_app_complete_task_batch-20260619-180233/run-20260619-180233-2890e1a3` 暴露了一个典型问题：第 1 轮模型只执行 `read_file(todo_app.py)` 和 `read_file(tasks.json)`，这是合理的信息收集；第 2 轮模型尝试 `apply_patch`，但因为 `old_text_not_found` 失败，随后 `git_diff.changed_file_count = 0`。旧链路里 `observe` 会承担“是否有进展”的判断，容易把纯读取轮和真正失败的修改轮都粗糙归类为“无进展”。
- Task（目标）：把 loop 从 `plan -> act -> observe -> verify/reflect` 收敛为 `plan -> act -> reflect -> verify`，让 harness 负责保真地压缩事实，让 LLM 自己解释上一轮是否有效并重规划；同时避免把当前轮数、剩余轮数或最大轮数暴露给模型。
- Action（动作）：删除独立 `observe` 状态、`progress_observed` 事件和 `progress_made` 判断；每轮 `act` 后固定进入 `reflect`；`reflect_feedback` 只记录 `observation`、`signals`、`failed_tools`、`recent_tool_results`、`verification` 等事实。新增 `no_diff_after_edit_attempt` signal：只有本轮存在修改类工具且最新 `git_diff.changed_file_count == 0` 时才产生；纯读取/搜索轮不产生 no-diff signal。下一轮模型只接收 `runtime_feedback.previous_reflect`、兼容保留的 `previous_verification` 和 `previous_cross_round_plan`，并从模型请求中移除轮数预算字段。
- Result（结果）：在真实 run 中，第 1 轮纯读取被压缩为 `signals=[]`、`changed_files=[]`、`failed_tool_count=0`，没有被 harness 误判；第 2 轮 patch 失败被压缩为 `signals=["no_diff_after_edit_attempt", "failed_tool_observed"]`，并在 `recent_tool_results` 中保留 `read_file(todo_app.py, excerpt_reason=old_text_not_found_candidate)` 与 `apply_patch(todo_app.py, error=old_text_not_found)`，比旧的“无进展”判断更可解释。回归测试已通过：`tests/test_loop.py tests/test_model.py tests/test_cli.py -q` 为 `47 passed`，全量 `pytest -q` 为 `88 passed`。
- Benefit（收益）：上下文反馈从“harness 替模型下判断”变成“harness 保真压缩事实”，降低了纯读取/搜索轮被误判的风险；失败修改轮也能用更精确的 signal 表达“尝试编辑但没有 diff”。下一轮模型看到的是事实包而不是硬约束或预算提示，更符合真实 agent harness 的职责边界，也让 trace/report 的排查顺序稳定为 `plan -> act -> reflect -> verify`。
- 是否固化：已固化为当前 Phase 9 loop 内核行为，并同步更新 README、架构书、使用手册、RUN_CHAIN.html、当前状态和进度文档；后续观察重点是模型是否能更稳定利用 `previous_reflect.recent_tool_results` 中的源码片段与失败工具摘要完成重规划。

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

### 2026-06-19：结构摘要、指定行读取与文件上下文累计缓解重复读文件和 old_text_not_found
- Situation（背景）：真实 run 中反复出现两个相关问题：模型反复调用 `read_file`，以及 `apply_patch` 经常失败为 `old_text_not_found`。追根到底，两者都和上下文注入不足有关。harness 过去常只给文件前几十行摘要、总行数和少量片段，而模型做准确替换时需要真实源码证据，包括函数位置、相邻代码、缩进和完整 old_text。拿不到这些信息时，模型会反复读文件，或者根据摘要自行“编”一段看似合理但文件中不存在的 `old_text`。
- Task（目标）：目标不是简单禁止重复读文件，也不是用按行替换工具绕开所有 `old_text_not_found`。真正目标是让模型以可控方式拿到必要源码上下文，再基于真实代码做修改。同时，保留一个低摩擦编辑兜底，用来处理已经定位准确但文本精确匹配不可靠的场景。
- Action（动作）：初始 `context_snapshot.repo_context.selected_files` 增加 `structure_summary`，让模型第一轮就能看到 Python `def/class` 名称和行号；`read_file` 对非小文件返回 `content_mode="excerpt"` 和结构摘要；`read_file_range` 支持按行号读取具体片段，并限制单次只能读取 1-40 行，避免变相全文读取；`file_context_cache` 按文件累计最近 5 次读取片段，让同一文件跨轮已读源码继续可见。同时保留 `replace_lines`，但它定位为 fallback：根因修复仍然是让模型看到真实上下文；`replace_lines` 更适合在乱码、换行、不可见字符、编码差异等导致 `apply_patch.old_text` 明明逻辑正确却匹配不到时，作为按行号替换的兜底手段。
- Result（结果）：这次改进把问题从“模型总是重复读文件”推进为“模型能否根据结构摘要合理选择需要的上下文”。模型不再只能在摘要和全文之间二选一，而是可以先看结构，再按目标函数附近读取片段，并跨轮保留已读内容。这降低了乱编 `old_text` 的概率，也降低了 `old_text_not_found` 的发生概率。相关回归测试已通过：`tests/test_loop.py tests/test_model.py tests/test_context.py -q` 为 `38 passed`，全量 `pytest -q` 为 `108 passed`。
- Benefit（收益）：对于上下文不足导致的 `old_text_not_found`，根本解法是结构摘要、指定行读取和累计注入；对于编码或不可见字符导致的文本匹配失败，`replace_lines` 才是兜底工具。当前收益是源码证据供给更连续、更可控，trace 中也能看到模型究竟读过哪些文件片段。
- 是否固化：已固化为当前 harness 行为。仍需继续观察大型仓库任务中，模型是否能稳定判断“需要哪些上下文”而不是追求全部上下文；这部分是后续真实任务验证重点。
