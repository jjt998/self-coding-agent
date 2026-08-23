# 当前状态

## 最后更新时间

- 日期：2026-06-15

## 当前阶段

- `Phase 9：真实任务最小闭环`

## 当前情况

- `Phase 8` 已暂定完结，策略对比链路现在可以稳定产出 `summary.json` 与 `summary.md`。
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
- 当前已经具备“固定任务集上的策略实验外壳”，但还不具备“真实代码任务求解闭环”；现有 `loop`、`tools`、`verify` 仍以 stub 演示链路为主。

## 已完成

- `Phase 1` 到 `Phase 8` 已完成。
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

## 当前最小闭环缺口

- 缺少真实任务决策内核：当前 `src/loop.py` 仍是 `_run_stub_state`，`plan`、`act`、`observe` 还没有进入“按任务自主读代码、改代码、再验证”的真实求解闭环。
- 缺少真实任务验证机制：当前 `src/verify.py` 主要验证 `agent_notes.md`、固定工具顺序和演示型 diff，不足以判断 bug fix、重构、测试补全等真实任务是否完成。
- 缺少真实任务 task schema：现有 eval task 更像“任务描述 + expectation”，还没有把 repo 子目录、sandbox 目录、准备步骤、验证命令、通过条件这些真实实验必需字段结构化下来。
- 缺少任务级隔离/重置能力：后续固定采用“每题绑定一个独立 sandbox 目录”的方案，避免任务之间互相污染，并保证批量实验可复现。
- 缺少真实模型驱动的决策层：当前策略对比主要比较 context / memory / reflect 外壳，还没有接入真正的任务级模型决策与工具选择回路。

## 下一步明确动作

- 先定义真实任务最小 schema，补齐任务文本之外的实验字段，至少覆盖 sandbox 目录、准备步骤、验证命令、通过标准和作用范围。
- 落地“每题独立 sandbox 目录”执行模式，让单题运行和 batch eval 都能在隔离目录中完成。
- 重写 `verify`，让验证从“演示链路检查”切换为“按任务定义执行真实验证”。
- 在不破坏现有 trace / summary / comparison 结构的前提下，把 `loop` 从 stub 链路逐步替换成真实任务求解链路。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先补齐“真实任务可运行、可验证、可复现”的最小闭环，再继续扩展更复杂的策略和指标。

## 新会话恢复指引

1. 阅读 `docs/SESSION_ENTRY.md`
2. 阅读 `docs/CURRENT_STATUS.md`
3. 阅读 `docs/PHASE_PROGRESS.md`
4. 优先查看 `src/loop.py`、`src/tools.py`、`src/verify.py`、`src/runner.py`
5. 再查看 `src/eval_runner.py`、`src/experiment_runner.py`、`eval_tasks/sample_batch.json`
6. 从“真实任务最小 schema + 每题独立 sandbox 目录 + 真实 verify”继续推进
