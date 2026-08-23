# 当前状态

## 最后更新时间

- 日期：2026-06-15

## 当前阶段

- `Phase 8：策略对比`

## 当前情况

- 已在 `docs/SESSION_ENTRY.md` 增加项目级行为约束，要求以第一性原理思考、目标不清先讨论、路径不优时主动指出、遇到问题追根因、输出只保留决策相关信息。
- `Phase 1` 最小骨架已经落地，仓库现在具备可运行的 Python 项目结构。
- 已建立 `pyproject.toml`、`src/`、`tests/`、`configs/`、`eval_tasks/`、`runs/`。
- 已实现基础 settings model、trace event model、trace writer 与 CLI skeleton。
- 已实现 `Phase 2` 最小状态机 loop，CLI 现在可完整跑过一条 stub 状态链路。
- 已完成 `Phase 3` 最小核心工具闭环，`act` 阶段现在会执行真实工具序列。
- trace 中已可看到结构化状态迁移、状态结果、工具调用与工具结果事件。
- repo 根目录下会生成 `agent_notes.md` 作为 Phase 3 的最小工具操作结果。
- 已完成结构化验证结果与报告增强，run 结束后可看到工具摘要、验证结论与 stop reason。
- 已完成 `Phase 5` 第一版 context 控制面，`analyze` 阶段会生成四层 `context_snapshot`。
- 已接入最小文件级召回，当前会按任务关键词和文件规则选出少量相关文件进入上下文。
- 已补上原文、摘要、索引三种实际注入内容，选中文件现在会记录真正放进上下文的文本。
- 已补上最小裁剪规则，trace 和 report 里现在能看到保留行数、总行数和是否裁剪。
- report 现在会展示上下文摘要，包括任务关键词、扫描文件数、注入方式和选中文件原因。
- 已接入按任务类型区分的召回倾向，不同任务现在会优先看到不同类型的文件。
- 已补上上下文统计摘要，当前可看到选中文件数、保留总行数、原始总行数和裁剪文件数。
- 已为 memory 接入预留明确接口位，当前上下文里会记录 memory 查询词、来源和命中条数。
- 已落地 `runtime memory manager` 最小接口，`analyze` 阶段现在会通过统一入口拿到 memory 提示。
- 当前 memory 结果已经接入 `context_snapshot` 和报告，可看到 query、source 与命中条目。
- 已把默认任务类型从 `ad_hoc` 改成更直白的 `general`，避免继续扩散不友好命名。
- 已落地长期 memory 的最小写入口，验证通过的 run 现在会写入 `.agent_memory/long_term_memory.jsonl`。
- trace 和报告现在会记录 memory 写入结果，便于后续检查长期 memory 何时被写入。
- 已让 `runtime memory manager` 读取长期 memory store，并把命中结果接回分析阶段。
- 已实现基于 `task type`、`tags`、`keywords`、`selected_context_files` 的最小长期 memory 筛选。
- 已在 `memory_context` 中区分运行时规则 memory 与长期 memory 命中结果。
- 已为 `memory conflict evidence` 增加最小字段，当前先记录为空列表占位。
- 报告现在会展示运行时规则条数、长期 memory 条数和 conflict evidence 条数。
- 已实现最小 `memory conflict evidence` 检测，当前会识别“共享关键词或文件路径，但任务类型不同”的长期 memory 命中对。
- 已增加 `memory_conflict` 与 `memory_pollution` 两个最小诊断标签，并接入 `memory_context` 与报告。
- 报告现在会展示 memory 诊断标签和冲突证据摘要，便于快速排查潜在污染。
- 已为长期 memory 写入补充稳定证据字段，当前会持久化 `task_keywords`、`summary_keywords`、`task_summary_excerpt` 与规范化后的 `selected_context_files`。
- 长期 memory 检索现在会优先读取已落盘证据关键词，旧数据缺字段时再回退到 `task + summary` 现算关键词。
- 已收紧最小 conflict evidence 规则，当前要求“共享关键词”和“共享文件路径”两类线索同时成立，才标记为潜在 memory 冲突。
- 已补上 `Phase 6` 的第四轮 CLI 自动化测试扩展，覆盖 memory 写入证据与弱线索误判回归。
- 已增加独立 memory trace event，当前会单独记录 `memory_search_result`、`memory_conflict_detected` 与 `memory_entry_written`。
- 现在即使不展开 `context_snapshot`，也能直接从 trace 回放一次 run 的 memory 检索、冲突和写入证据。
- 已增加长期 memory 命中摘要压缩规则，当前会把注入上下文和 trace 的长期 memory 摘要裁到稳定长度。
- memory 命中证据里现在会额外记录 `original_summary_length` 与 `summary_was_compressed`，便于后续观察事件体积与信息损失。
- 已把 memory conflict evidence 分成“强冲突”和“弱提醒”两档，当前会在证据里记录 `severity`。
- 现在只有强冲突才会触发 `memory_conflict` / `memory_pollution`，单一线索冲突只会打 `memory_conflict_warning`。
- 已把冲突强弱接入长期 memory 注入策略，当前会抑制“与当前任务类型不一致且落入强冲突”的长期 memory 注入。
- 被抑制的长期 memory 现在会单独记录到 `suppressed_long_term_entries`，trace、上下文和报告都能直接看到抑制原因。
- 弱提醒现在不再只是标签，当前会对异类长期 memory 施加排序降权，并把 `ranking_penalty`、`adjusted_score` 和原因写进证据。
- 弱提醒降权力度现在已支持配置，当前会从 `configs/*.json` 的 `memory.weak_conflict_penalty` 读取，不再写死在代码里。
- 长期 memory 摘要压缩长度现在也已支持配置，当前会从 `configs/*.json` 的 `memory.summary_max_length` 读取。
- 已进入 `Phase 7` 最小 eval 闭环，当前支持从任务文件批量执行 run，并输出聚合 `summary.json` 与 `summary.md`。
- 已落地最小 eval task schema，当前使用 `{"tasks": [...]}` 结构描述批量任务。
- 已落地最小 eval runner，当前会复用单次 run 内核并聚合成功率、平均步数、平均工具调用数、失败分布和诊断标签统计。
- 已为单条 eval run 增加结果分层，当前会区分 `passed_cleanly`、`passed_with_warnings`、`failed_verification`、`stopped_early` 与 `failed_unknown`。
- 已为 eval summary 增加更明确的 diagnostics 流程，当前会单独统计干净成功数、带警告成功数、failure taxonomy 与验证失败检查项。
- eval 运行明细现在会直接写出结果分层、诊断标签和失败检查，便于区分“成功但有风险提示”和“真正失败”。
- 已为 eval task schema 增加最小 `expectation` 字段，当前支持声明 `passed`、`outcome`、`required_diagnostic_labels`、`forbidden_diagnostic_labels` 与 `failure_taxonomy`。
- eval 现在会对每条任务产出 `expectation_result`，明确记录该任务是否命中预期，以及失配的是哪些字段。
- batch summary 现在会额外聚合 expectation 定义数、命中数、失配数与失配字段分布，便于把“实际跑出了什么”和“本来希望它跑成什么”放在一起比较。
- 已把 expectation 扩展到更细粒度断言，当前支持 `min_step_count`、`max_step_count`、`min_tool_call_count`、`max_tool_call_count`、`required_failing_checks` 与 `forbidden_failing_checks`。
- eval task 现在不只可断言“结果像不像”，也能断言“过程有没有落在合理区间内”，例如步数过多、工具调用过多或失败检查项不符合预期时会直接记为 expectation miss。
- 已修正 expectation 解析边界，当前不会再把空值或 `None` 错误收敛成字符串。
- 已把 failure taxonomy 从单一 primary key 扩展成多维 `failure_taxonomy_tags`，当前会保留 outcome、stop reason、失败检查项数量、每个失败检查项与诊断标签等维度。
- batch summary 现在会同时输出 `failure_taxonomy_counts` 和 `failure_taxonomy_tag_counts`，既保留兼容用的主分类，也能按细粒度标签聚合排查。
- Markdown summary 已增加 `Failure Taxonomy Tags` 小节，运行明细里也会展示单条 run 的 taxonomy tags。
- 已增加 eval 批量派生指标，当前 summary 会直接输出 `failure_rate`、`clean_pass_rate`、`warning_rate`、`verification_failure_rate` 与 `expectation_miss_rate`。
- Markdown summary 现在会展示失败率、干净成功率、警告率、验证失败率和 expectation 失配率，便于快速判断一批任务的健康度。
- 已进入 `Phase 8` 最小策略对比闭环，当前支持对同一批 eval 任务按多套 config 重复执行，并输出 comparison 级 `summary.json` 与 `summary.md`。
- 已为 CLI 增加 `--compare-strategies` 入口，当前可直接传入逗号分隔的 config 名列表触发策略对比。
- 已落地最小 strategy comparison runner，当前会以首个 strategy 作为 baseline，并聚合各策略的成功率、失败率、干净成功率、警告率、验证失败率、expectation 失配率、平均步数和平均工具调用数。
- comparison summary 现在会额外输出相对 baseline 的 delta，便于直接比较不同策略的收益和代价。
- 已为 memory 策略增加最小 `enabled` 开关，当前支持通过 `configs/*.json` 显式切换 `memory.enabled`。
- 已增加 `configs/memory_off.json`，可作为 `structured_memory_on` 对照的最小 `memory_off` 样例。
- 已修正 Windows 下 pytest 临时目录配置，当前统一使用 `.pytest_tmp/run`，避免 `pytest_tmp/run` 清理失败影响回归。
- 已为 context 策略增加最小 `strategy` 开关，当前支持通过 `configs/*.json` 显式切换 `context.strategy`。
- 已增加 `configs/naive_recent_context.json`，作为 `file_recall_context` 的第一版对照策略样例。
- `ContextBuilder` 现在已支持 `file_recall_context` 与 `naive_recent_context` 两种选择策略。
- `naive_recent_context` 当前会按最近修改时间选取文本文件，并沿用原有注入模式规则，尽量把差异收敛在“选哪些文件”而不是“怎么注入内容”。
- 已补充 CLI 自动化测试，当前可验证 `naive_recent_context` 确实会选中最近改动的文件，而不是继续走关键词召回。
- 已为 reflect 策略增加最小 `strategy` 开关，当前支持通过 `configs/*.json` 显式切换 `reflect.strategy`。
- 已增加 `configs/verify_failure_only_reflect.json`，作为默认反思策略的第一版对照样例。
- 当前默认 reflect 策略为 `low_progress_plus_verify_reflect`，会在 `observe` 无进展时触发一次 reflect，并在验证失败时也保留触发能力。
- 已增加 `verify_failure_only_reflect`，当前只会在验证失败时触发 reflect，不再因为 `observe` 无进展而自动插入。
- `run_finished` 的 stop reason details 现在会额外记录 `reflect_trigger_reason`，便于区分这次 reflect 是由无进展还是验证失败触发的。
- 已补充 CLI 与 loop 自动化测试，当前可分别验证“成功任务下不触发 reflect”和“验证失败后会补触发 reflect”。
- 已增强 eval / comparison 汇总，当前会在单条 run、batch summary 与 comparison summary 中直接记录 `config_name`、`context_strategy`、`reflect_strategy`、`memory_strategy` 与 `memory_enabled`。
- 已把 `verify_count`、`reflect_count`、`reflect_triggered`、`reflect_trigger_reason` 纳入 eval 结果采集，当前 summary 会聚合平均 verify 次数、平均 reflect 次数、reflect 触发率与触发原因分布。
- comparison summary 现在除了结果指标 delta，还会展示策略维度变化和 reflect 过程 delta，便于直接看“换了哪种策略”和“过程上付出了什么代价”。
- 已重写 `tests/test_eval.py` 的 Phase 7/8 覆盖用例，移除历史乱码断言，并补齐策略元数据与 reflect 聚合指标回归。

## 已完成

- 完成 `SESSION_ENTRY` 行为约束更新，补充第一性原理、目标澄清、最短路径提醒、根因优先和高信号输出要求。
- 完成 Python 项目骨架初始化。
- 完成最小可运行 CLI 入口。
- 完成 run 目录初始化逻辑。
- 完成配置快照写入。
- 完成 JSONL trace 基础事件写入。
- 完成 Markdown report 基础输出。
- 完成基础自动化测试，验证最小 run 产物创建成功。
- 完成状态枚举与运行时状态模型。
- 完成 stop reason model。
- 完成 loop orchestrator。
- 完成 stub 状态迁移链路：
  - `ingest`
  - `analyze`
  - `plan`
  - `act`
  - `observe`
  - `reflect`
  - `verify`
  - `finalize`
- 完成状态迁移事件与状态结果事件 trace 写入。
- 完成 `search_text`。
- 完成 `read_file`。
- 完成 `apply_patch`。
- 完成 `run_command`。
- 完成 `git_diff`。
- 完成工具输入输出 trace 写入。
- 完成 `Phase 3` 的 CLI 自动化测试扩展。
- 完成 verification result schema。
- 完成 `verify` 阶段的结构化验证流程。
- 完成 `verification_result` trace 事件写入。
- 完成单次 run 的 Markdown 报告增强。
- 完成 `Phase 4` 的 CLI 自动化测试扩展。
- 完成 task/repo/runtime/memory context models。
- 完成最小文件级召回。
- 完成 `context_snapshot` trace 事件写入。
- 完成上下文摘要报告输出。
- 完成 `Phase 5` 的第一轮 CLI 自动化测试扩展。
- 完成原文、摘要、索引三种注入内容生成。
- 完成最小上下文裁剪规则。
- 完成上下文字段扩展，包含注入内容、保留行数、总行数和裁剪标记。
- 完成 `Phase 5` 的第二轮 CLI 自动化测试扩展。
- 完成按任务类型区分的召回优先级。
- 完成 `bug_fix` 任务类型的召回策略测试。
- 完成上下文统计字段。
- 完成 memory context 预留接口字段。
- 完成 `Phase 5` 的第三轮 CLI 自动化测试扩展。
- 完成 `runtime memory manager` 最小接口。
- 完成 context builder 与 memory manager 对齐。
- 完成 `Phase 5` 的第四轮 CLI 自动化测试扩展。
- 完成默认任务类型命名收敛：`ad_hoc` -> `general`。
- 完成长期 memory entry schema。
- 完成验证通过后写入长期 memory 的最小流程。
- 完成 `memory_write_result` trace 事件。
- 完成 `Phase 6` 的第一轮 CLI 自动化测试扩展。
- 完成长期 memory store 读取流程。
- 完成按 `task type`、`tags`、`keywords`、`file path` 的最小检索。
- 完成 memory context 字段扩展：`runtime_rule_entries`、`long_term_entries`、`conflict_evidence`。
- 完成 `Phase 6` 的第二轮 CLI 自动化测试扩展。
- 完成最小 memory conflict evidence 检测规则。
- 完成最小 `memory_conflict` / `memory_pollution` 诊断标签。
- 完成 `Phase 6` 的第三轮 CLI 自动化测试扩展。
- 完成长期 memory 稳定证据写入：`task_keywords`、`summary_keywords`、`task_summary_excerpt`、规范化 `selected_context_files`。
- 完成基于显式证据字段优先的长期 memory 检索兼容逻辑。
- 完成更保守的 memory 冲突判定规则，降低单一弱线索导致的误判。
- 完成 `Phase 6` 的第四轮 CLI 自动化测试扩展。
- 完成独立 memory trace event：`memory_search_result`、`memory_conflict_detected`、`memory_entry_written`。
- 完成长期 memory 命中摘要压缩与压缩证据记录。
- 完成 memory conflict severity 分级：`strong` / `weak`。
- 完成基于强冲突的长期 memory 注入抑制策略。
- 完成基于弱提醒的长期 memory 排序降权策略。
- 完成弱提醒降权力度配置化，并增加 `high_weak_conflict_penalty` 配置样例。
- 完成摘要压缩长度配置化，并增加 `short_memory_summary` 配置样例。
- 完成最小 eval task schema。
- 完成最小 eval runner。
- 完成 batch summary report：`summary.json`、`summary.md`。
- 完成 `Phase 7` 的第一轮 CLI 自动化测试扩展。
- 完成 eval 结果分层：`passed_cleanly`、`passed_with_warnings`、`failed_verification`、`stopped_early`、`failed_unknown`。
- 完成 eval failure taxonomy 第一版聚合。
- 完成验证失败检查项统计与 Markdown summary 展示。
- 完成 `Phase 7` 的第二轮 eval diagnostics 自动化测试扩展。
- 完成 eval task-level expectation 第一版 schema。
- 完成 expectation 对照结果：`expectation_result`。
- 完成 expectation 聚合统计与 Markdown summary 展示。
- 完成 `Phase 7` 的第三轮 eval expectation 自动化测试扩展。
- 完成 expectation 第二版细粒度断言：步数、工具调用数、失败检查项。
- 完成 expectation 解析边界修正，避免 `None` 被错误解析成字符串。
- 完成 `Phase 7` 的第四轮 eval expectation 自动化测试扩展。
- 完成 failure taxonomy tags 第一版多维分类。
- 完成多维 taxonomy 聚合统计与 Markdown summary 展示。
- 完成 `Phase 7` 的第五轮 eval taxonomy 自动化测试扩展。
- 完成 eval 批量派生 rate 指标。
- 完成派生 rate 指标的 JSON summary 与 Markdown summary 展示。
- 完成 `Phase 7` 的第六轮 eval derived metrics 自动化测试扩展。

## 进行中

- 继续推进 `Phase 8`，下一步优先评估是否补充 failure taxonomy delta、代表性 trace 链接或更细粒度的过程指标。

## 下一步明确动作

- 评估 comparison summary 是否需要补充 failure taxonomy delta、代表性 trace 链接或按任务维度展开的策略差异。
- 评估是否需要把 verify / reflect 过程指标继续细化到 task-level expectation 或 failure taxonomy 分桶。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，先把 context 与 recall 做成可检查控制面，再进入 memory 与更复杂 agent 行为。

## 新会话恢复指引

新会话恢复时建议：

1. 阅读 `docs/DEVELOPMENT_PLAYBOOK.md`。
2. 阅读 `docs/CURRENT_STATUS.md`。
3. 阅读 `docs/PHASE_PROGRESS.md`。
4. 检查 `src/context.py`、`src/tools.py`、`src/verify.py`、`src/loop.py`、`src/runner.py` 与 `tests/` 当前实现。
5. 优先查看 `src/eval_runner.py`、`src/loop.py`、`tests/test_eval.py` 与 `tests/test_loop.py`，从 comparison summary 的 failure taxonomy / trace 可解释性增强继续推进。
## 2026-06-15 补充更新

- 已补充 comparison summary 的 failure 解释力，当前会输出 failure_taxonomy_counts_delta、failure_taxonomy_tag_counts_delta 和 verification_failure_counts_delta。
- 已把上述差异接入 strategy comparison Markdown，当前可以直接看到 failure taxonomy delta、verification checks delta 和 reflect 原因 delta。
- 已新增独立的 Phase 8 comparison 回归测试文件，避免继续在历史乱码测试文件上叠加修改。
- 当前 pytest -q 已通过，结果为 18 passed。