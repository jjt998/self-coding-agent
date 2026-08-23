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
- 已把 `eval_tasks/sample_batch.json` 从演示样例升级成更像真实研究集的固定任务集，当前覆盖 `general`、`bug_fix`、`code_understanding`、`test_generation`、`refactor` 五类任务。
- 已完成首批实验套件实跑，结果目录位于 `runs/research_batch_20260615_full/experiment-suite-first_batch/`。
- 首批实验当前得到三条初步结论：
  - `naive_recent_context` 相比 `file_recall_context` 在现有固定任务集上没有拉开差异，说明这批任务还不足以区分两种 context 策略。
  - `memory_off` 相比默认 memory 策略保留了同样的成功率，但把 `warning_rate` 从 `1.0` 降到了 `0.0`，同时把 `clean_pass_rate` 从 `0.0` 提升到 `1.0`，当前默认 memory 在这批任务上主要带来了冲突/污染类诊断噪声。
  - `verify_failure_only_reflect` 相比默认 reflect 策略没有降低成功率，但把平均步数从 `8` 降到 `7`，把平均 reflect 次数从 `1` 降到 `0`，说明“observe 无进展就反思”在当前任务集上更像额外开销。
- 新增与保留的 comparison / experiment / task set 回归测试已通过，当前 `python -m pytest -q` 结果为 `21 passed`。

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
  - research-like fixed sample task set

## 下一步明确动作

- 基于首批结果补第二版固定任务集，重点加入更能区分 context 策略收益的任务。
- 评估是否把默认 memory 策略暂时收紧，避免在当前任务集上稳定制造 warning 而不带来收益。
- 评估是否把默认 reflect 策略从 `low_progress_plus_verify_reflect` 调整为更保守的版本，或至少下放为可选 baseline。

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
