# 阶段进度台账

## 总览

- 最后更新时间：2026-06-21
- 当前激活阶段：`Phase 9.x：Verify 收敛为末尾单次裁判`
- 当前阶段状态：`in_progress`

## 最新 Phase 9.x 收口：Verify 改为末尾单次裁判

- 当前 loop 已从 `ingest -> analyze -> (plan -> act -> reflect -> verify)* -> finalize` 调整为 `ingest -> analyze -> (plan -> act -> reflect)* -> verify -> finalize`。
- `verify` 现在只会在求解阶段退出后执行一次，验证结果不再回灌给后续模型轮次。
- `ModelDecision` 已新增 `loop_end`，用于让模型显式表达“当前是否真的已经不再需要任何后续工作”；只有后续不再读、改、跑命令、看 diff 或补充验证时才允许设为 `true`，并且同轮 `tool_calls` 必须为空。
- Runtime 已新增“连续两次空 `tool_calls`”收口信号；命中后会直接退出求解阶段并进入最终验证。
- trace 已新增 `solve_loop_exit_detected`，`run_finished.stop_reason.details` 已补充 `solve_loop_exit_reason`、`final_verification_passed` 和 `consecutive_empty_tool_call_count`。
- `previous_verification` 已从模型输入中移除，`previous_reflect.verification` 也已从事实反馈中移除。
- token diagnostics 仍会继续流入 `model_raw_response`、`model_decision`、`run_finished`、`report.md`、`summary.json`、`summary.md` 和 comparison delta；provider 缺失 `usage` 时不做本地估算。
- 当前产品定位继续向 `bug_fix` 主赛道收敛，其它任务类型保持兼容，但不再默认依赖过程内 verify 反馈。
- 当前已新增显式结构摘要工具 `read_file_structure_summary(path)`，让模型能先看结构、再按行号精读，而不是总从 `read_file` 间接触发大文件摘要。
- 当前已接入运行时记忆污染治理第一版：成功编辑过的文件会把旧读取缓存整文件标记为 `stale`，后续只有重新读取后才恢复为 `fresh`。
- `reflect_feedback` 现已补充 `stale_file_paths` 和最近缓存失效诊断，便于在 trace 中直接看出“为什么又读了一次这个文件”。

> 说明：下方按 Phase 保留历史推进记录，其中部分旧条目描述的是更早期的 loop 或 verify 形态；当前实现以上方“最新 Phase 9.x 收口”为准。


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
  - 当前支持 `always_keep`、`delete_on_success`、`keep_on_success`、`always_delete` 四种 sandbox 生命周期策略，默认 `delete_on_success`
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
  - 当前 OpenAI 兼容决策层会调用 `/chat/completions`，并要求模型返回 `summary`、`rationale`、`planned_actions`、`donelist`、`tool_calls` JSON
  - 当前模型工具计划只允许 `search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff`，且 `tool_input` 必须是对象，并会校验字段名、必填字段和字段类型
  - `src/loop.py` 的 `plan` 阶段现已捕获模型配置、请求和响应异常，并以 `stop_reason.code = model_error` 结束 run
  - `model_decision_failed` 已进入 trace，错误 details 包含 provider、model name、error type 和 error message，不记录 API key
  - `_run_planned_tools()` 已移除旧 Phase 3 固定工具序列回退逻辑，工具执行必须来自模型返回的合法 `tool_calls`
  - 所有 `configs/*.json` 已切到 `openai_compatible`，默认使用 DeepSeek endpoint，并通过 `.env` 或系统环境变量中的 `DEEPSEEK_API_KEY` 读取密钥
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

### Phase 9.x 本轮新增：运行时记忆污染治理 v1 + 显式结构摘要工具

- `src/file_structure.py` 已落地共享结构摘要 helper，统一服务于 `ContextBuilder` 与工具层，避免两套相近实现继续漂移。
- `src/tools.py` 已新增 `read_file_structure_summary(path)`；返回固定 `content_mode="structure_summary"`、`line_count`、`content_truncated=true` 和 `structure_summary`，不再附带大文件前 20 行摘录。
- `.py` 文件的结构摘要继续保留 `line_number`、`kind`、`name`、`indent`、`line`，便于模型直接配合 `read_file_range` 精读。
- `src/model.py` 已把 `read_file_structure_summary` 接入 `ALLOWED_TOOL_NAMES`、`TOOL_SCHEMAS` 和主提示词，并明确三者分工：
  - `read_file`：通用读取
  - `read_file_structure_summary`：先看结构
  - `read_file_range`：按行精读
- `src/loop.py` 已把文件缓存治理升级为“编辑后整文件失效”：
  - `apply_patch` / `replace_lines` 成功后，旧读取缓存整文件标记为 `stale`
  - 旧片段内容不再继续暴露为可直接复用源码
  - 只保留 `stale_reason`、`last_invalidated_step`、`stale_snippet_count`、`stale_covered_ranges` 等诊断字段
  - 后续重新读取同文件后，缓存恢复为 `fresh`
- `reflect_feedback` 与后续轮次 `runtime_feedback.previous_reflect` 已补充：
  - `file_context_cache[*].cache_status`
  - `file_context_cache[*].stale_reason`
  - `stale_file_paths`
  - `recent_file_context_invalidations`
- 本轮仍保持 v1 边界：不做片段级失效，不做编辑后行号偏移映射，不做局部缓存修补。

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

### Phase 9 本轮新增：结构化失败收口与 reflect feedback

- setup 失败已收口为 `stop_reason.code = setup_failed`，并在 details 中保留失败 setup command 的 returncode、stdout、stderr、cwd。
- verify 最终失败已收口为 `stop_reason.code = verification_failed`，并继续进入 `finalize` 生成完整 report。
- `run_finished.stop_reason.details.verification_failure` 已包含 failing checks、failed verify commands、failed rule types、verification mode、command/rule 数量。
- eval outcome / failure taxonomy 已扩展：`failed_setup`、`setup:command_returncode`、`verification:verify_command_returncode`、`verification:verify_rule:<check>`。
- reflect 阶段已生成 `reflect_feedback` trace，并把结构化反馈写入下一轮 `runtime_feedback.previous_reflect_feedback`。
- `eval_tasks/sample_batch.json` 已改为可读 UTF-8，并给两个任务加入真实 `verify_commands` 与结构化 `verify_rules` 示例。

### Phase 9 下一步更新

1. 继续把 reflect feedback 接入更明确的模型重规划提示，减少重复失败计划。
2. 用升级后的 sample batch 做 eval/comparison smoke，校验报告可读性和 taxonomy 聚合。
3. 根据真实任务需求继续补 regex、JSON key/length、diff text 等验证规则。
### Phase 9 本轮新增：reflect feedback 驱动重规划

- `reflect_feedback` 不再只是记录型反馈；最新一次反馈会被整理为 `replan_constraints` 并传入下一轮 `runtime_feedback.previous_reflect_feedback`。
- `replan_constraints` 当前覆盖失败原因、必须处理的关注点、失败检查名、失败工具摘要、建议工具和需要避免原样重复的上一轮工具序列。
- `model_decision` trace 新增 `has_reflect_feedback` 与 `reflect_feedback_summary`，便于 eval/comparison 回看第二轮 plan 是否拿到了反思证据。
- OpenAI compatible prompt 已明确要求模型在重规划时回应 `previous_reflect_feedback`，并避免无解释地重复完全相同的失败工具计划。
- 报告新增 `## 反思反馈` 小节；本轮边界仍保持不开放更高 `runtime.max_steps`、不新增 CLI 单次 verify 参数、不扩展新 verify rule。
### Phase 9 本轮新增：第四批 verify_rules

- `src/verify.py` 新增命令输出 regex 规则：`command_stdout_matches_regex`、`command_stderr_matches_regex`。
- `src/verify.py` 新增 JSON 结构规则：`json_path_exists`、`json_array_length_equals`、`json_array_length_at_least`、`json_array_length_at_most`、`json_object_key_exists`。
- `src/verify.py` 新增 diff 文本规则：`diff_contains_text`、`diff_not_contains_text`，规则只读取已有 `git_diff` 工具结果。
- `src/eval_runner.py` 的 `_normalize_verify_rules()` 已保留新增字段：`regex`、`expected_length`、`min_length`、`max_length`、`key`。
- 本轮边界保持不变：不改 loop，不改 reflect/model，不改 CLI 单次 verify 参数，不开放更高 `runtime.max_steps`。

### Phase 9 本轮新增：真实状态处理骨架

- `src/loop.py` 已移除 `_run_stub_state` 作为状态执行入口，改为 `_run_state` 分发到独立 per-state handler。
- `ingest` 阶段补齐真实任务输入证据，`state_result.result` 与新增 `task_ingested` trace 均包含 repo/workspace/verify/setup/model/config 摘要。
- `finalize` 阶段补齐真实收尾证据，`state_result.result` 与新增 `finalize_summary` trace 均包含验证、进展、reflect、轮数、工具调用和模型决策统计。
- 本轮是 loop 内核结构化重构，保持 plan/act/observe/reflect/verify 既有行为不变，不新增 CLI 参数，不扩展 `verify_rules`，不调整 `runtime.max_steps=2`。

### Phase 9 本轮新增：移除演示型 verify 回退

- `build_phase_4_verification()` 现在只接受显式任务级验证配置，不再自动回退到 `agent_notes.md` 演示检查。
- `verify_rules` 已可在没有 `verify_commands` 时独立运行，适合表达纯文件、JSON、diff、多文件聚合等结构化完成条件。
- 缺少 `verify_commands` 与 `verify_rules` 时会稳定失败为 `missing_task_verification`，便于 eval/comparison 识别任务不可判定。
- 本轮保持边界：不新增规则类型，不开放 CLI 单次 verify 参数，不修改 reflect/model prompt，不调整最大求解轮数。

### Phase 9 本轮新增：缺失任务级验证一等诊断

- eval failure taxonomy 已将 `verification_mode = missing_task_verification` 固定归类为 `verification:missing_task_verification`。
- failure taxonomy tags 已补充 `verification_mode:missing_task_verification`，并继续保留 `verification_check:task_verification_configured`。
- run 报告会在验证结果小节提示缺少 `verify_commands` / `verify_rules`，避免用户把任务不可判定误读为普通内容验证失败。
- comparison delta 不需要新增结构，沿用现有 `failure_taxonomy_counts_delta` 与 `failure_taxonomy_tag_counts_delta` 即可聚合该失败模式。

### Phase 9 本轮新增：Reflect Feedback 强制驱动重规划

- `previous_reflect_feedback.replan_constraints` 已从模型提示升级为 plan 后硬校验，模型必须可追踪地回应失败原因、失败检查和必须处理的关注点。
- 未回应 reflect 约束、或无解释重复上一轮失败工具序列时，会抛出 `ModelResponseError`，并沿用 plan 阶段 `model_error` 停止路径。
- `model_decision` trace 保留 `has_reflect_feedback` 与 `reflect_feedback_summary`，并新增 `reflect_constraints_acknowledged` 表示重规划约束已通过校验。
- OpenAI compatible prompt 已改为中文硬约束说明；本轮不修改 `runtime.max_steps=2`，不新增 `verify_rules`，不开放 CLI 单次 verify 参数。

### Phase 9 本轮新增：Eval/Comparison Smoke 与失败诊断统一

- `sample_batch` 已升级为全任务显式验证，使用现有 `verify_commands`、`file_contains`、`diff_contains_file`、`files_matching_count_at_least` 等能力表达最小验收。
- failure taxonomy 已统一覆盖 setup、model、verify command、verify rule、missing verification、max steps 六类 MVP 失败口径。
- failure taxonomy tags 已统一保留结果层、stop reason 层、验证模式、失败检查、模型错误类型和 runtime max steps 等诊断维度。
- run 报告新增 `失败诊断` 小节；eval summary 与 comparison delta 继续沿用现有 JSON 主结构聚合 taxonomy 和 tag。
- 本轮保持边界：不新增 verify rule 类型，不开放 CLI 单次 verify 参数，不放开 `runtime.max_steps=2`。

### Phase 9 本轮新增：真实 Loop 内核扫尾

- 删除旧 Phase 3 固定工具序列辅助函数，当前 `act` 阶段不再保留任何固定工具链回退入口。
- 当前代码中的初始化报告、runner 入口和测试 fake model 已改为真实 loop 语义，不再使用 stub/占位/Phase 3 工具闭环命名。
- `sample_batch` 和测试默认产物已统一为 `run_evidence.md`，避免继续以历史 `agent_notes.md` 演示文件作为完成标准。
- 新增源码层回归检查，防止 `build_phase_3_tool_sequence`、`_run_stub_state`、`Phase 3 工具闭环` 回流。

### Phase 9 本轮新增：模型接口与运行体验加固

- `ModelError.details` 已统一承载安全模型排障信息，trace/report 可展示错误类型、provider、model、base_url、timeout、字段路径和 HTTP 状态码。
- 配置层新增 `base_url` 协议校验；缺少 API key 的错误 details 包含 `api_key_env`，但不记录密钥值。
- 请求失败与响应失败已补齐安全摘要：HTTP body 截断、网络错误类别、fake response 解析失败、缺字段、未知工具和非法 `tool_input` 都能定位到具体字段或工具序号。
- 本轮不新增依赖，不改变 OpenAI compatible 主 schema，不恢复 `rule_based`。

### Phase 9 本轮新增：README/使用手册与 MVP 验收冻结

- README 已补齐从模型配置到 comparison 排障的最小使用路径，并链接到 `docs/USAGE_GUIDE.md` 与 `docs/MVP_ACCEPTANCE.md`。
- `docs/USAGE_GUIDE.md` 已固定 eval task 写法、report 阅读、eval summary 和 comparison delta 阅读方式。
- `docs/MVP_ACCEPTANCE.md` 已固定全量 pytest、sample eval、sample comparison 三类 MVP 验收命令和当前边界/backlog。
- 新增文档回归测试，防止关键使用命令、路径、限制和 backlog 在后续改动中丢失。

### Phase 9 本轮新增：跨轮计划与工具入参类型校验

- `ModelDecision.donelist` 当前已重定义为累计 done list，用于表达“到当前轮为止已经完成了什么”；`planned_actions` 明确收敛为本轮 `tool_calls` 的可读说明，不再承担跨轮任务队列职责。
- `runtime_feedback.previous_donelist` 当前回填的是上一轮累计 done list，而不是下一轮计划，第二轮及后续 plan 会据此减少重复兜圈。
- harness 会自动合并历史 done list 与本轮模型返回，避免模型漏写后把既有完成事项覆盖掉。
- OpenAI compatible 请求中的 `decision_schema` 已更新为：`tool_calls` 是唯一执行源、`planned_actions` 是本轮说明、`donelist` 是累计已完成事项。
- `model_decision` trace、plan state result、finalize 摘要、stop reason details 和 report 均会展示或保留跨轮计划。
- 工具 schema 校验已从字段名扩展到字段类型，非法类型会进入 `ModelResponseError` / `model_error`，例如 `apply_patch.new_text = null` 不会再导致工具层 traceback。
- `apply_patch` 工具本身也增加防御式非法输入返回，统一为 `ToolExecution(ok=false, error=invalid_tool_input)`。
- 本轮保持边界：不新增 verify rule，不修改 loop 轮数，不做 `planned_actions` 与 `tool_calls` 的一致性强诊断。

