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
- 当模型计划里写了要执行 `apply_patch` / `git_diff`，但实际 `tool_calls` 只返回读取或搜索工具时，当前 harness 还没有把这种“计划与实际工具调用不一致”作为一等诊断。
- `run_command` 与 `git_diff` 的下一轮摘要仍偏轻量，后续可以继续补 stdout 关键行和 diff 短摘要，帮助模型修复“patch 成功但语义仍错”的情况。

## 下一步观察指标

- 第二轮模型的 `runtime_feedback.recent_tool_results` 是否包含目标文件 `path` 和短源码片段。
- `old_text_not_found` 后，下一轮反馈是否包含 `failed_old_text_excerpt` 和候选源码片段。
- 模型是否减少编造 `apply_patch.old_text` 的情况。
- 同一个 demo bugfix 任务是否更容易在第二轮产生真实 diff。
- `trace.jsonl` 是否保持可读，没有被大段文件全文淹没。

## 改进记录

### 2026-06-19：`read_file` 关键片段与 `old_text_not_found` 反馈驱动重规划

- 问题现象：demo todo bugfix 任务中，模型多次读取了 `todo_app.py`，但旧版 `runtime_feedback.recent_tool_results` 只告诉下一轮“读了多少行”，没有给出可复制的源码片段；当 `apply_patch` 返回 `old_text_not_found` 后，下一轮仍容易猜错 `old_text` 或误判修复方式。
- 改进动作：增强 `recent_tool_results`，让 `read_file` 摘要携带 `path`、短 `content_excerpt`、片段行号和 `excerpt_reason`；让 `apply_patch old_text_not_found` 摘要携带 `failed_old_text_excerpt` 与 `new_text_excerpt`；在 `reflect_feedback.replan_constraints.must_address` 中加入 `use_exact_old_text_from_read_file`。
- 预期改善：模型在下一轮 plan 中能直接引用最近 `read_file` 片段中的真实源码行，减少编造 `apply_patch.old_text`，并更容易产生真实 diff。
- 实际反馈：真实 eval run `run-20260619-140710-ffa68ca3` 通过。第 3 轮 `apply_patch` 仍因 `old_text_not_found` 失败，但 reflect 明确写入 `use_exact_old_text_from_read_file`；第 4 轮模型引用真实源码 `status = "todo" if task.get("done") else "done"`，成功 patch 为 `status = "done" if task.get("done") else "todo"`，`git_diff` 检测到 `todo_app.py` 变更，最终 `success_rate=1.0`、`outcome=passed_cleanly`、`stop_reason=completed`。
- 是否固化：已作为当前 harness 的有效改进固化，并通过本次 demo bugfix 真实 run 验证；后续仍需用更多任务观察泛化稳定性。
