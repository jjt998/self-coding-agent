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
  - eval task schema 已承载 `repo_subdir` / `workspace_mode` / `setup_commands` / `verify_commands`，但 `verify_commands` 还未真正驱动任务级 verify
- 本轮已完成：
  - `src/config.py` 补齐 `source_repo_root`、`workspace_mode`、`sandbox_dir`、`setup_commands`、`verify_commands`
  - `src/eval_runner.py` 补齐真实任务最小 schema 第一版，并默认让 eval task 走 `per_task_sandbox`
  - `src/runner.py` 补齐每题独立 sandbox 目录准备、路径忽略规则和 setup trace 事件
  - sandbox 工作区改为更短的临时目录，绕开 experiment suite 下 Windows `cwd` 过长问题
  - 回归测试新增覆盖：schema 解析、sandbox 隔离、setup command 执行
  - `src/config.py` / `src/eval_runner.py` / `src/runner.py` 补齐 sandbox 保留策略字段与执行逻辑
  - 当前支持 `always_keep`、`delete_on_success`、`always_delete` 三种 sandbox 生命周期策略，默认 `delete_on_success`
  - `sandbox_cleanup_result` 已进入 trace，报告中已新增 `Sandbox 清理` 小节
  - 回归测试新增覆盖：默认成功后删除 sandbox、显式保留 sandbox
  - 自动化验收：`python -m pytest -q` 通过，结果为 `23 passed`
- 下一步实现顺序建议：
  1. 把 `verify_commands` 和通过条件真正接入任务级 verify。
  2. 接入真实模型/策略决策层本体。
  3. 把 loop 从 stub 逐步替换为真实求解链路。
  4. 把 setup / verify 失败都收口为结构化 stop reason 与 failure taxonomy。

## 下一步

- 先围绕真实任务实验补“真实 verify + 决策层 + loop”三件套。
- 在保留现有 comparison / experiment 外壳的前提下，把真实任务执行链路继续接深。
- 等最小闭环跑通后，再重新设计第二批更能区分 context 策略的研究任务集。
