# 阶段进度台账

## 总览

- 最后更新时间：2026-06-12
- 当前激活阶段：`Phase 5：Context 与 Recall`

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

- 状态：`in_progress`
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
