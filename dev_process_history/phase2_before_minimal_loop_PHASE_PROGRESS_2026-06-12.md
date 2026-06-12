# 阶段进度台账

## 总览

- 最后更新时间：2026-06-12
- 当前激活阶段：`Phase 2：最小 Agent Loop`

## Phase 1：脚手架与控制面

- 状态：`completed`
- 目标：让仓库具备可运行、可扩展、结构稳定的基础。
- 已完成：
  - 创建 `pyproject.toml`
  - 创建 `src/self_coding_agent/` 包结构
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

- 状态：`in_progress`
- 目标：让任务能沿着基线状态机 loop 跑通。
- 已完成：
  - 已具备可承载 loop 的基础 run/trace 骨架
- 剩余：
  - 实现状态枚举
  - 实现运行时状态
  - 实现 stop reasons
  - 实现 loop orchestrator
  - 实现初步状态迁移流程
- 验收：
  - 一次 run 可以完成状态迁移并发出状态迁移事件。
- 备注：
  - 这是当前下一步实现目标。

## Phase 3：核心工具

- 状态：`not_started`
- 目标：支持本地代码任务的核心仓库操作。
- 已完成：
  - 核心工具列表已固定。
- 剩余：
  - 实现 `search_text`
  - 实现 `read_file`
  - 实现 `apply_patch`
  - 实现 `run_command`
  - 实现 `git_diff`
  - 将所有工具交互写入 trace
- 验收：
  - 五个工具都有结构化输入输出，并可在一次 run 中被调用。
- 备注：
  - 依赖 Phase 1 的 model 与 trace。

## Phase 4：验证与报告

- 状态：`not_started`
- 目标：让成功与失败具备可审计性。
- 已完成：
  - 验证需求已在文档中明确。
- 剩余：
  - 实现 verification result schema
  - 实现 verify 执行流程
  - 实现单次 run 的 Markdown 报告增强
  - 在报告中写出结构化 stop reason
- 验收：
  - 一次完成的 run 能产出状态、验证结果和可读报告。
- 备注：
  - 验证规则应保持保守。

## Phase 5：Context 与 Recall

- 状态：`not_started`
- 目标：让模型输入变得可控、可检查。
- 已完成：
  - Context 分层设计已记录。
- 剩余：
  - 实现 context models
  - 实现文件级召回
  - 实现原文/摘要/索引注入规则
  - 实现裁剪策略
- 验收：
  - Trace 中可以看到 context snapshot 和文件召回决策。
- 备注：
  - 第一版保持以文件为中心。

## Phase 6：Memory

- 状态：`not_started`
- 目标：在具备基本抗污染意识的前提下实现经验复用。
- 已完成：
  - Memory 范围和检索基线已确定。
- 剩余：
  - 实现 runtime memory manager
  - 实现 long-term memory store
  - 实现结构化 memory entry
  - 实现 tag/path/keyword 检索
  - 实现 memory conflict evidence
- 验收：
  - 成功且验证通过的 run 可以写入 memory，后续 run 可以读取。
- 备注：
  - MVP 不上 embedding 检索。

## Phase 7：Eval

- 状态：`not_started`
- 目标：支持可重复评测与对比。
- 已完成：
  - Eval 结构与指标已经定义。
- 剩余：
  - 实现 task spec schema
  - 实现 eval runner
  - 实现 metrics 收集
  - 实现 diagnostics 流程
  - 实现 batch summary report
- 验收：
  - 固定任务集可以批量运行，并输出聚合指标。
- 备注：
  - 必须同时覆盖 result、process、diagnostic 三类指标。

## Phase 8：策略对比

- 状态：`not_started`
- 目标：运行有意义的策略实验。
- 已完成：
  - 第一批实验方向已确定。
- 剩余：
  - 增加 strategy configs
  - 增加 context strategy variants
  - 增加 memory on/off 开关
  - 增加 reflect trigger variants
  - 增加 comparison summary
- 验收：
  - 同一任务集上至少两种策略可比较，并输出 delta。
- 备注：
  - 第一批实验应保持窄范围、强控制。
