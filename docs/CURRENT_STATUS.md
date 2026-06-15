# 当前状态

## 最后更新时间

- 日期：2026-06-15

## 当前阶段

- `Phase 8：策略对比`

## 当前情况

- `Phase 8` 已完成收口，策略对比链路现在可以稳定产出 `summary.json` 与 `summary.md`。
- comparison summary 已覆盖聚合指标 delta、failure taxonomy delta、verification failure delta、reflect trigger reason delta。
- comparison summary 已覆盖 `task_deltas`，可按任务展开 outcome、passed、steps、tool calls、verify、reflect、reflect reason、failure taxonomy、failing checks、diagnostic labels 差异。
- `task_deltas` 现已补齐代表性运行指针：`baseline_run_id`、`candidate_run_id`、`baseline_run_dir`、`candidate_run_dir`。
- `src/eval_runner.py` 已从损坏状态重建为可编译、可导入实现，并恢复 `eval` / `comparison` 全部已交付能力。
- 新增与保留的 comparison 回归测试已通过，当前 `python -m pytest -q` 结果为 `18 passed`。

## 已完成

- `Phase 1` 到 `Phase 7` 已完成。
- `Phase 8` 已完成：
  - baseline / candidate strategy comparison runner
  - context strategy variants
  - memory on/off strategy variants
  - reflect strategy variants
  - comparison delta summary
  - failure taxonomy / verification / reflect reason deltas
  - task-level deltas
  - representative run pointers in task deltas

## 下一步明确动作

- 进入下一阶段时，优先执行第一批真实策略实验：
  - `naive_recent_context` vs `file_recall_context`
  - `memory_off` vs `structured_memory_on`
  - `verify_failure_only_reflect` vs `low_progress_plus_verify_reflect`
- 在固定任务集上沉淀首批可复用基线结果，并根据结果决定下一轮指标细化方向。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先做可比较、可解释、可复现的实验结果，而不是过早扩展复杂策略。

## 新会话恢复指引

1. 阅读 `docs/SESSION_ENTRY.md`
2. 阅读 `docs/CURRENT_STATUS.md`
3. 阅读 `docs/PHASE_PROGRESS.md`
4. 优先查看 `src/eval_runner.py`、`src/cli.py`、`tests/test_eval.py`、`tests/test_eval_phase8_comparison.py`
5. 从“执行第一批策略实验并沉淀基线结果”继续推进
