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
- 已补上实验套件入口，当前支持通过 `--experiment-suite-file` 一键执行一组固定策略实验。
- 已新增 `src/experiment_runner.py` 与 `experiment_suites/first_batch.json`，把首批三组策略实验固化为可复用清单。
- 新增与保留的 comparison / experiment 回归测试已通过，当前 `python -m pytest -q` 结果为 `20 passed`。

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
  - experiment suite runner
  - first batch experiment manifest

## 下一步明确动作

- 直接使用 `experiment_suites/first_batch.json` 执行首批真实策略实验并沉淀结果。
- 为首批实验准备更稳定、更多样的固定任务集，避免只依赖 `eval_tasks/sample_batch.json`。
- 根据首批实验结果决定下一轮是继续细化 comparison 指标，还是扩展新的策略维度。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先做可比较、可解释、可复现的实验结果，而不是过早扩展复杂策略。

## 新会话恢复指引

1. 阅读 `docs/SESSION_ENTRY.md`
2. 阅读 `docs/CURRENT_STATUS.md`
3. 阅读 `docs/PHASE_PROGRESS.md`
4. 优先查看 `src/eval_runner.py`、`src/cli.py`、`tests/test_eval.py`、`tests/test_eval_phase8_comparison.py`
5. 优先查看 `src/experiment_runner.py`、`experiment_suites/first_batch.json`、`tests/test_experiment_runner.py`
6. 从“执行首批实验套件并沉淀基线结果”继续推进
