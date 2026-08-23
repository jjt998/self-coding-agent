# 当前状态

## 最后更新时间

- 日期：2026-06-13

## 当前阶段

- `Phase 5：Context 与 Recall`

## 当前情况

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

## 已完成

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

## 进行中

- 继续推进 `Phase 5`，准备为长期 memory store 预留最小结构入口。

## 下一步明确动作

- 为召回结果补更多可解释字段，减少“为什么选中它”的歧义。
- 继续补齐不同任务类型下的召回优先级规则。
- 为长期 memory store 预留最小结构入口。
- 设计长期 memory entry schema。
- 设计成功 run 的 memory 写入时机。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，先把 context 与 recall 做成可检查控制面，再进入 memory 与更复杂 agent 行为。

## 新会话恢复指引

新会话恢复时建议：

1. 阅读 `docs/DEVELOPMENT_PLAYBOOK.md`。
2. 阅读 `docs/CURRENT_STATUS.md`。
3. 阅读 `docs/PHASE_PROGRESS.md`。
4. 检查 `src/context.py`、`src/tools.py`、`src/verify.py`、`src/loop.py`、`src/runner.py` 与 `tests/` 当前实现。
5. 从长期 memory store 的最小结构入口开始继续。
