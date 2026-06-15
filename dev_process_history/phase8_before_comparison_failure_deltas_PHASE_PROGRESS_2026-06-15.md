# 阶段进度台账

## 总览

- 最后更新时间：2026-06-15
- 当前激活阶段：`Phase 8：策略对比`
- 补充说明：`docs/SESSION_ENTRY.md` 已增加项目级行为约束，后续会话默认按第一性原理、根因优先和高信号输出执行。

## Phase 1：脚手架与控制面

- 状态：`completed`
- 目标：让仓库具备可运行、可扩展、结构稳定的基础。
- 已完成：
  - 创建 `pyproject.toml`
  - 创建 `src/` 源码目录结构
  - 创建 `tests/`、`configs/`、`eval_tasks/`、`runs/`
  - 增加基础 settings model
  - 增加 trace event model
  - 增加 trace writer
  - 增加 CLI skeleton
  - 验证单条命令可生成 run 目录、配置快照、trace 和 report
- 验收：
  - 已通过
- 备注：
  - 当前实现仍是最小骨架，模型调用、工具注册和状态机尚未接入。

## Phase 2：最小 Agent Loop

- 状态：`completed`
- 目标：让任务能沿着基线状态机 loop 跑通。
- 已完成：
  - 已具备可承载 loop 的基础 run/trace 骨架
  - 实现状态枚举
  - 实现运行时状态
  - 实现 stop reasons
  - 实现 loop orchestrator
  - 实现初步状态迁移流程
  - 实现一次条件触发的 reflect 占位逻辑
  - 实现最小无进展跟踪
- 验收：
  - 已通过
- 备注：
  - 当前仍是 stub loop，但控制面已经具备继续接工具与验证流程的条件。

## Phase 3：核心工具

- 状态：`completed`
- 目标：支持本地代码任务的核心仓库操作。
- 已完成：
  - 核心工具列表已固定。
  - Phase 2 loop 已为工具接入预留 trace 与执行骨架。
  - 实现 `search_text`
  - 实现 `read_file`
  - 实现 `apply_patch`
  - 实现 `run_command`
  - 实现 `git_diff`
  - 将所有工具交互写入 trace
  - 在 `act` 阶段接入受控最小工具序列
  - 扩充 CLI 测试，验证工具调用与工具产物
- 剩余：
  - 暂无
- 验收：
  - 已通过
- 备注：
  - 当前 `git_diff` 先基于运行前文本快照生成统一 diff，后续如需更贴近真实 git 语义可再增强。

## Phase 4：验证与报告

- 状态：`completed`
- 目标：让成功与失败具备可审计性。
- 已完成：
  - 验证需求已在文档中明确。
  - Phase 3 已提供稳定的工具 trace，可作为验证与报告输入。
  - 实现 verification result schema
  - 实现 verify 执行流程
  - 实现单次 run 的 Markdown 报告增强
  - 在报告中写出结构化 stop reason
  - 增加 `verification_result` trace 事件
  - 扩充 CLI 测试，验证报告与验证结果
- 剩余：
  - 暂无
- 验收：
  - 已通过
- 备注：
  - 验证规则应保持保守。

## Phase 5：Context 与 Recall

- 状态：`completed`
- 目标：让模型输入变得可控、可检查。
- 已完成：
  - Context 分层设计已记录。
  - 实现 task/repo/runtime/memory 四层 context model
  - 实现最小文件级召回
  - 实现 `context_snapshot` trace 事件
  - 在报告中展示上下文摘要
  - 扩充 CLI 测试，验证上下文快照与文件召回
  - 实现原文、摘要、索引三种实际注入内容
  - 实现最小上下文裁剪规则
  - 为文件上下文补充注入内容、保留行数、总行数和裁剪标记
  - 实现按任务类型区分的召回优先级
  - 扩充 CLI 测试，验证 `bug_fix` 任务的召回倾向
  - 实现上下文统计字段
  - 为 memory context 增加查询词、来源和命中条数接口位
  - 实现 `runtime memory manager` 最小接口
  - 让 context builder 通过统一入口读取 memory 结果
  - 将默认任务类型命名从 `ad_hoc` 收敛为更直白的 `general`
- 剩余：
  - 暂无
- 验收：
  - 已通过
- 备注：
  - 第一版保持以文件为中心，当前优先保证可检查、可解释、可裁剪，并先把 runtime memory 接口稳定下来。

## Phase 6：Memory

- 状态：`in_progress`
- 目标：在具备基本抗污染意识的前提下实现经验复用。
- 已完成：
  - Memory 范围和检索基线已确定。
  - 实现长期 memory entry schema
  - 实现验证通过后写入长期 memory 的最小流程
  - 增加 `memory_write_result` trace 事件
  - 扩充 CLI 测试，验证长期 memory 文件写入
  - 让 `runtime memory manager` 读取长期 memory store
  - 实现按 `task type`、`tags`、`keywords`、`file path` 的最小检索
  - 在 `memory_context` 中区分 `runtime_rule_entries` 和 `long_term_entries`
  - 实现最小 `conflict_evidence` 检测规则
  - 增加 `memory_conflict` 与 `memory_pollution` 诊断标签
  - 扩充 CLI 测试，验证长期 memory 读取与筛选
  - 扩充 CLI 测试，验证 memory 冲突证据与污染标签
  - 为长期 memory 写入补充稳定证据字段：`task_keywords`、`summary_keywords`、`task_summary_excerpt`、规范化 `selected_context_files`
  - 让长期 memory 检索优先使用显式证据字段，并兼容旧格式 memory 回退逻辑
  - 收紧最小 conflict evidence 规则，要求共享关键词和共享文件路径同时成立后再标记冲突
  - 扩充 CLI 测试，验证 memory 写入证据和单一弱线索不误报冲突
  - 增加独立 memory trace event：`memory_search_result`、`memory_conflict_detected`、`memory_entry_written`
  - 扩充 CLI 测试，验证 memory 检索事件、冲突事件和写入事件都会单独落入 trace
  - 增加长期 memory 命中摘要压缩规则，并记录 `original_summary_length`、`summary_was_compressed`
  - 增加 memory conflict severity 分级：`strong` / `weak`
  - 让强冲突触发 `memory_conflict` / `memory_pollution`，让单一线索冲突仅触发 `memory_conflict_warning`
  - 把强冲突接入长期 memory 注入策略，抑制与当前任务类型不一致的强冲突长期 memory
  - 增加 `suppressed_long_term_entries`，让被抑制条目也能在 trace、上下文和报告中检查
  - 把弱提醒接入长期 memory 检索排序，为异类长期 memory 增加 `ranking_penalty` 与 `adjusted_score`
  - 把 `weak_conflict_penalty` 提升为配置项，并增加高 penalty 配置样例
  - 把 `summary_max_length` 提升为配置项，并增加短摘要配置样例
- 剩余：
  - 评估是否需要让摘要压缩长度按事件类型、注入位置或任务类型分层配置
  - 评估是否需要把 penalty 继续按任务类型或线索数量细分
- 验收：
  - 成功且验证通过的 run 可以写入 memory，后续 run 可以读取。
- 备注：
  - MVP 不上 embedding 检索，先保证写入和读取接口稳定。

## Phase 7：Eval

- 状态：`completed`
- 目标：支持可重复评测与对比。
- 已完成：
  - Eval 结构与指标已经定义。
  - 实现最小 eval task schema，当前使用 `{"tasks": [...]}` 承载批量任务
  - 实现最小 eval runner，复用现有单次 run 内核批量执行任务
  - 实现 metrics 收集：成功率、平均步数、平均工具调用数
  - 实现最小 diagnostics 汇总：失败分布、memory 诊断标签计数
  - 实现 batch summary report：`summary.json`、`summary.md`
  - 提供 `eval_tasks/sample_batch.json` 示例任务文件
  - 扩充 CLI 测试，验证 eval batch 产物与聚合指标
  - 实现单条 run 结果分层：`passed_cleanly`、`passed_with_warnings`、`failed_verification`、`stopped_early`、`failed_unknown`
  - 在 eval summary 中增加干净成功数、带警告成功数、failure taxonomy 与验证失败检查项统计
  - 扩充 eval 测试，验证 diagnostics 分层、failure taxonomy 与 Markdown summary 输出
  - 为 eval task schema 增加最小 `expectation` 字段，支持 `passed`、`outcome`、必需/禁止诊断标签与 `failure_taxonomy`
  - 为单条 run 增加 `expectation_result`，记录 expectation 是否命中以及失配字段
  - 在 eval summary 中增加 expectation 定义数、命中数、失配数与失配字段统计
  - 更新 `eval_tasks/sample_batch.json`，提供 expectation 写法样例
  - 扩展 expectation 断言范围，支持步数区间、工具调用区间、必需/禁止失败检查项
  - 修正 expectation 可选字符串字段的解析边界，避免 `None` 被收敛成字符串
  - 扩展 failure taxonomy，新增 `failure_taxonomy_tags` 多维标签
  - 在 eval summary 中增加 `failure_taxonomy_tag_counts` 聚合与 `Failure Taxonomy Tags` 展示
  - 增加批量派生 rate 指标：`failure_rate`、`clean_pass_rate`、`warning_rate`、`verification_failure_rate`、`expectation_miss_rate`
  - 在 JSON summary 与 Markdown summary 中展示派生 rate 指标
- 剩余：
  - 暂无
- 验收：
  - 固定任务集可以批量运行，并输出聚合指标。
- 备注：
  - 必须同时覆盖 result、process、diagnostic 三类指标。
  - 当前 diagnostics 已能区分“干净成功”“带警告成功”和“真正失败”，taxonomy 已从单一主分类扩展为主分类加多维标签。
  - 当前 expectation 已能覆盖部分过程指标，但仍以轻量规则断言为主，不追求复杂 DSL。

## Phase 8：策略对比

- 状态：`in_progress`
- 目标：运行有意义的策略实验。
- 已完成：
  - 第一批实验方向已确定。
  - 增加最小 strategy comparison runner，复用现有 eval batch 能力按多套 config 重复执行同一任务集
  - 增加 comparison summary：`summary.json`、`summary.md`
  - 在 comparison summary 中增加相对 baseline 的关键指标 delta
  - 为 CLI 增加 `--compare-strategies` 入口，支持直接从命令行触发策略对比
  - 为 memory 策略增加 `enabled` 开关，支持显式切换 `memory_on` / `memory_off`
  - 增加 `configs/memory_off.json` 作为最小 memory 对照策略样例
  - 为 context 策略增加 `strategy` 开关，支持显式切换 `file_recall_context` / `naive_recent_context`
  - 增加 `configs/naive_recent_context.json` 作为最小 context 对照策略样例
  - 让 `ContextBuilder` 支持按最近修改时间选文件的 `naive_recent_context`
  - 保持 `naive_recent_context` 继续沿用现有注入模式规则，把实验差异优先收敛在文件选择层
  - 为 reflect 策略增加 `strategy` 开关，支持显式切换 `low_progress_plus_verify_reflect` / `verify_failure_only_reflect`
  - 增加 `configs/verify_failure_only_reflect.json` 作为最小 reflect 对照策略样例
  - 让 loop 支持在 `observe` 无进展或 `verify` 失败后按策略条件插入 reflect
  - 为 `run_finished` 增加 `reflect_trigger_reason`，便于区分反思是由无进展还是验证失败触发
  - 扩充自动化测试，验证 strategy comparison CLI 与 comparison summary 产物
  - 扩充自动化测试，验证 `naive_recent_context` 会稳定选中最近改动的文件
  - 扩充自动化测试，验证 `verify_failure_only_reflect` 在成功任务下不会触发 reflect，且在验证失败时会补触发 reflect
  - 修正 Windows 下 pytest 临时目录配置，避免策略对比测试被目录清理问题打断
  - 为 eval run 增加策略元数据字段：`config_name`、`context_strategy`、`reflect_strategy`、`memory_strategy`、`memory_enabled`
  - 为 eval run / batch summary 增加过程指标：`verify_count`、`reflect_count`、`reflect_triggered`、`reflect_trigger_reason`
  - 为 eval / comparison summary 增加平均 verify 次数、平均 reflect 次数、reflect 触发率与触发原因分布
  - 为 comparison delta 增加策略维度变化标记与 reflect 过程 delta，便于直接比较过程代价
  - 重写 `tests/test_eval.py`，移除历史乱码断言并补齐 Phase 7/8 聚合指标回归
- 剩余：
  - 评估 comparison summary 是否需要补充 failure taxonomy delta、代表性 trace 分析或按任务维度展开的策略差异
  - 评估是否把 verify / reflect 过程指标继续细化到 task-level expectation 或 failure taxonomy 分桶
- 验收：
  - 同一任务集上至少两种策略可比较，并输出 delta。
- 备注：
  - 第一批实验继续保持窄范围、强控制，优先验证“能不能稳定比较”，再扩展策略维度。
  - 当前已具备 context、memory 和 reflect 三个维度的最小可比策略，且 comparison summary 已能直接展示策略身份与过程 delta；下一步优先补强 failure taxonomy / trace 层面的解释力。
