# 阶段进度台账

## 总览

- 最后更新时间：2026-06-16
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
  - `src/tools.py` 仍保留固定 `build_phase_3_tool_sequence()` 辅助函数，但 `loop` 不再把它作为模型决策回退路径
  - 当前已接入第一版 OpenAI 兼容模型决策层，但尚未接入真正的多步任务求解推进回路
  - `src/verify.py` 已支持 `verify_commands`，但当前通过条件仍主要等价于“命令退出码是否成功”
  - eval task schema 已承载 `repo_subdir` / `workspace_mode` / `setup_commands` / `verify_commands`，后续还需继续增强 richer verify schema
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
  - `src/verify.py` 已支持“真实 verify command 优先、stub verify 回退”的双轨验证
  - `src/loop.py` 已接上 `RunSettings.verify_commands` 驱动的任务级验证
  - 回归测试新增覆盖：真实 verify command 成功、失败后保留 sandbox、stub verify 回退
  - `src/config.py` / `src/eval_runner.py` / `src/verify.py` 已补齐 `verify_rules` 第一版，支持把任务级通过条件结构化声明到 task schema
  - 当前 `verify_rules` 已支持首批规则类型：命令 stdout/stderr 包含检查、指定命令返回码检查、文件存在检查、文件包含/不包含文本检查
  - 回归测试新增覆盖：`verify_rules` 成功、`verify_rules` 失败、task spec 中 `verify_rules` 字段解析
  - 当前 `verify_rules` 第二版已补齐一批更贴近真实任务的断言：命令 stdout/stderr 不包含检查、文件不存在检查、文件最小/最大行数检查
  - 回归测试新增覆盖：负向命令输出检查、文件不存在检查、文件行数上下界检查，以及对应 task spec 字段解析
  - 已重构 `src/model.py`，移除 `rule_based` adapter，当前只支持 `openai_compatible` 决策层
  - 当前 OpenAI 兼容决策层会调用 `/chat/completions`，并要求模型返回 `summary`、`rationale`、`planned_actions`、`tool_calls` JSON
  - 当前模型工具计划只允许 `search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff`，且 `tool_input` 必须是对象
  - `src/loop.py` 的 `plan` 阶段现已捕获模型配置、请求和响应异常，并以 `stop_reason.code = model_error` 结束 run
  - `model_decision_failed` 已进入 trace，错误 details 包含 provider、model name、error type 和 error message，不记录 API key
  - `_run_planned_tools()` 已移除旧 Phase 3 固定工具序列回退逻辑，工具执行必须来自模型返回的合法 `tool_calls`
  - 所有 `configs/*.json` 已切到 `openai_compatible`，默认通过 `OPENAI_API_KEY` 读取密钥
  - 已新增 `tests/test_model.py`，并更新 `tests/test_loop.py` / `tests/test_cli.py` 适配真实模型决策层
  - 本轮已按测试环境规范使用 `D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe` 完成回归：`tests/test_loop.py tests/test_model.py` 为 `12 passed`，`tests/test_cli.py tests/test_eval.py tests/test_verify.py` 为 `23 passed`，全量 `pytest -q` 为 `40 passed`
  - `src/loop.py` 已将 `observe` 从固定 no-progress stub 替换为真实工具结果观察：`git_diff` 有变更或 `apply_patch` 成功都会被视为有进展
  - 当前 `progress_observed` trace 会记录 `progress_made`、`changed_files`、`successful_tools`、`failed_tools`、`failed_tool_count`
  - 默认 `low_progress_plus_verify_reflect` 现在只在 `observe` 后没有真实进展时触发 `no_progress_after_observe`
  - `run_finished.stop_reason.details` 和运行报告已补充进展观察信息，报告新增 `## 进展观察` 小节
  - 本轮测试已补充覆盖：有进展不触发默认 reflect、无进展触发默认 reflect、CLI 报告包含进展观察
  - `src/loop.py` 已从单轮执行升级为最小多轮求解，当前流程为 `ingest -> analyze -> (plan -> act -> observe -> verify/reflect)* -> finalize`
  - `runtime.max_steps` 现在解释为最大求解轮数，所有现有策略配置已统一从 `1` 调整为 `2`
  - 验证失败且仍有预算时会触发 reflect 后重新 plan；达到最大轮数仍失败时以 `stop_reason.code = max_steps_reached` 收口
  - 第二轮及以后模型 plan 会收到 `runtime_feedback`，包含上一轮观察、最近工具摘要和验证结果
  - `run_finished.stop_reason.details` 和报告已补充 `max_steps`、`iteration_count`、`reflect_count`、`reflect_trigger_reasons`
  - 回归测试新增覆盖：单轮成功、多轮失败后成功、无进展后重规划、达到最大轮数失败、第二轮 runtime feedback、模型错误路径
- 下一步实现顺序建议：
  1. 继续扩展 `verify_rules`，优先补 JSON / diff / 多文件聚合类验证语义。
  2. 把 setup / verify 失败都收口为结构化 stop reason 与更稳定的 failure taxonomy。
  3. 继续把 reflect 从占位记录替换成能辅助重规划的真实反思链路。

## 下一步

- 先围绕真实任务实验优先补“真实 loop + 更强真实 verify + 结构化失败收口”三件套。
- 在保留现有 comparison / experiment 外壳的前提下，把真实任务执行链路继续接深。
- 等最小闭环跑通后，再重新设计第二批更能区分 context 策略的研究任务集。

### Phase 9 本轮新增：第三批 verify_rules

- `src/verify.py` 新增 JSON 断言：`json_file_value_equals`，支持 `path`、`json_path`、`expected_value`，其中 `json_path` 使用 `a.b.0.name` 这类简单点号路径。
- `src/verify.py` 新增 diff 断言：`diff_changed_file_count_at_least`、`diff_changed_file_count_at_most`、`diff_contains_file`，只读取当前 run 已执行的 `git_diff` 工具结果。
- `src/verify.py` 新增多文件聚合断言：`files_matching_count_at_least`、`files_matching_count_at_most`，支持 repo root 内 glob、文本包含/不包含约束和数量上下界。
- `src/eval_runner.py` 的 `_normalize_verify_rules()` 已保留新增字段：`json_path`、`expected_value`、`glob`、`min_count`、`max_count`，并保持 `expected_value` 的 JSON 原始类型。
- 本轮新增/更新测试覆盖 JSON 成功与失败、diff 上下界与目标文件断言、缺失 `git_diff` 失败、多文件 glob 统计、eval task schema 字段保留。
- 本轮边界保持不变：不改 loop，不改 CLI 单次 verify 参数，不处理 setup / verify failure taxonomy。

### Phase 9 下一步

1. 把 setup / verify 失败收口成结构化 stop reason 和更稳定的 failure taxonomy。
2. 继续把 `reflect` 从占位记录替换成能辅助重规划的真实反思链路。
3. 继续根据真实 eval 任务补更高阶的验证规则。
