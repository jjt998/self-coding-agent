# 会话入口

## 目的

本文档是新 AI 会话进入本项目时使用的轻量入口文档。

不要一开始就加载全部项目文档。应从这里进入，再根据当前阶段只读取最少必要文档。

## 当前默认工作流

1. 先阅读：
   - `docs/CURRENT_STATUS.md`
   - `docs/PHASE_PROGRESS.md`
   - `docs/DEVELOPMENT_PLAYBOOK.md`
2. 检查当前仓库结构。
3. 识别当前激活阶段。
4. 从下一个未完成实现步骤继续。
5. 只有在当前阶段确实需要时，才继续读取其他文档。

## 当前阶段

- `Phase 1：脚手架与控制面`

## 当前下一步

搭建 Python 项目脚手架与控制面骨架。

当前直接实现目标是：

- `pyproject.toml`
- `src/self_coding_agent/`
- `tests/`
- `configs/`
- `eval_tasks/`
- `runs/`

然后实现：

- 基础 config models
- trace event models
- trace writer
- CLI entrypoint

## 这些文档必须先读

默认优先阅读：

- `docs/CURRENT_STATUS.md`
- `docs/PHASE_PROGRESS.md`
- `docs/DEVELOPMENT_PLAYBOOK.md`

## 这些文档按需再读

只有在需要时再读取：

- `docs/ARCHITECTURE.md`
  - 当实现包结构、模块边界、trace、context、memory 或 eval 结构时
- `docs/DECISIONS.md`
  - 当某个设计选择变得不清晰，或你想重开旧决策时
- `docs/PRD.md`
  - 当范围、任务类型或 MVP 边界需要澄清时
- `docs/MONTH_PLAN.md`
  - 当需要回看一个月里程碑安排时

## 默认不要加载

除非用户明确要求做完整文档回顾，否则不要在会话开始时加载全部文档。

## 完成工作后需要更新

更新：

- `docs/CURRENT_STATUS.md`
- `docs/PHASE_PROGRESS.md`

如果关键设计决策发生变化，还要更新：

- `docs/DECISIONS.md`

如果执行顺序发生变化，还要更新：

- `docs/DEVELOPMENT_PLAYBOOK.md`

## 新会话提示词

新会话建议使用下面这段提示词：

```text
继续开发这个项目。先只阅读 docs/SESSION_ENTRY.md、docs/CURRENT_STATUS.md、docs/PHASE_PROGRESS.md 和 docs/DEVELOPMENT_PLAYBOOK.md，不要预加载全部项目文档。检查仓库，识别当前 phase，并从下一个未完成实现步骤继续。只有在当前阶段确实需要时，再读取 ARCHITECTURE、DECISIONS、PRD 或 MONTH_PLAN。完成工作后更新 CURRENT_STATUS 和 PHASE_PROGRESS。更新前的CURRENT_STATUS 和 PHASE_PROGRESS放到文件夹dev_process_history里面，并且CURRENT_STATUS 和 PHASE_PROGRESS的命名需要符合其工作阶段。更新后的CURRENT_STATUS 和 PHASE_PROGRESS代替之前的CURRENT_STATUS 和 PHASE_PROGRESS放在原地。
```
