# 阶段进度台账

## 总览

- 最后更新时间：2026-06-15
- 当前激活阶段：`Phase 9：真实任务最小闭环`
- 当前阶段状态：`in_progress`

## Phase 1：脚手架与控制面

- 状态：`completed`
- 结果：已完成 Python 项目骨架、基础 settings、trace writer、CLI skeleton。

## Phase 2：最小 Agent Loop

- 状态：`completed`
- 结果：已完成显式状态机 loop、stop reason、基础 reflect 插入链路。

## Phase 3：核心工具

- 状态：`completed`
- 结果：已完成 `search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff` 与 trace 接入。

## Phase 4：验证与报告

- 状态：`completed`
- 结果：已完成结构化 verification、`verification_result` trace 与单次 run 报告增强。

## Phase 5：Context 与 Recall

- 状态：`completed`
- 结果：已完成四层 context、文件级召回、注入模式、裁剪规则、上下文统计与 runtime memory 接口对齐。

## Phase 6：Memory

- 状态：`completed`
- 结果：已完成 long-term memory 写入/读回、冲突证据、污染诊断、强弱冲突分级、注入抑制与排序降权。

## Phase 7：Eval

- 状态：`completed`
- 结果：已完成 eval task schema、batch runner、result/process/diagnostic 指标、expectation、failure taxonomy 与派生 rate 指标。

## Phase 8：策略对比

- 状态：`completed`
- 已完成：
  - comparison runner 与 CLI `--compare-strategies`
  - `memory_off` / `structured_memory_on`
  - `naive_recent_context` / `file_recall_context`
  - `verify_failure_only_reflect` / `low_progress_plus_verify_reflect`
  - comparison summary 基础 delta
  - failure taxonomy / taxonomy tags / verification failure / reflect reason 聚合 delta
  - task-level delta 展开
  - task delta 中的代表性运行指针：
    - `baseline_run_id`
    - `candidate_run_id`
    - `baseline_run_dir`
    - `candidate_run_dir`
  - comparison markdown 中的 `Task Delta` 展示
  - `src/eval_runner.py` 重建与回归恢复
  - 实验套件 runner 与 CLI `--experiment-suite-file`
  - `experiment_suites/first_batch.json` 首批实验清单
  - `eval_tasks/sample_batch.json` 已升级为覆盖五类任务的固定研究任务集
  - 已完成 `experiment_suites/first_batch.json` 首次实跑，产出第一版 baseline 结果目录
  - 自动化验收：`python -m pytest -q` 通过，结果为 `21 passed`

## Phase 9：真实任务最小闭环

- 状态：`in_progress`
- 目标：
  - 让 agent 从“固定 stub 演示链路”进入“真实代码任务求解链路”。
  - 让 eval task 从“任务描述集”升级为“可复现实验任务集”。
  - 让 verify 从“演示型检查”升级为“真实任务完成性验证”。
  - 让批量实验具备任务级隔离，固定采用“每题独立 sandbox 目录”。
- 当前已识别缺口：
  - `src/loop.py` 仍依赖 `_run_stub_state`
  - `src/tools.py` 仍依赖固定 `build_phase_3_tool_sequence()`
  - `src/verify.py` 仍是 `agent_notes.md` 演示验证
  - 当前还缺少真实模型/策略决策层本体，尚未接入真正的任务级模型决策、工具选择与步骤推进回路
  - eval task schema 尚未承载 sandbox / setup / verify / pass criteria
- 下一步实现顺序建议：
  1. 定义真实任务最小 schema。
  2. 落地每题独立 sandbox 目录。
 3. 接入真实模型/策略决策层本体。
 4. 重写任务级 verify。
 5. 把 loop 从 stub 逐步替换为真实求解链路。

## 下一步

- 先围绕真实任务实验补“schema + sandbox + verify”三件套。
- 在保留现有 comparison / experiment 外壳的前提下，把真实任务执行链路接进去。
- 等最小闭环跑通后，再重新设计第二批更能区分 context 策略的研究任务集。
