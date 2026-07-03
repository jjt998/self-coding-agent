# 当前状态

## 最后更新时间

- 日期：2026-06-24

## 当前阶段

- `Phase 9.x：Context 双层输入与可读性固化`

## 当前情况

- 最新 loop 形态已收敛为 `ingest -> analyze -> (plan -> act -> observe)* -> verify -> finalize`；`verify` 不再在每轮 `act` 后执行，而是在求解阶段退出后只执行一次末尾最终验证。
- 当前 `verify` 已明确退回纯裁判角色：同一次 run 最多执行一次，只负责最终通过/失败判定、报告展示和 eval 聚合，不再把验证结果反馈给后续模型轮次。
- 当前求解阶段的默认退出信号已收敛为：本轮 `tool_calls` 为空、达到 `runtime.max_steps`、或遇到 `model_error / setup_failed / internal_error`。
- 当前不再要求模型显式输出结束字段；harness 仅根据本轮 `tool_calls` 是否为空来决定是否继续求解。
- `trace.jsonl` 会继续记录 `solve_loop_exit_detected`、单次 `verification_result`，以及 `run_finished.stop_reason.details.solve_loop_exit_reason`。
- 后续模型轮次现在接收 `initial_guide` 与每轮重建的 `context_snapshot`；`context_snapshot.working_memory` 会把上一轮模型返回的四字段结构化工作记忆回灌给下一轮，并额外注入 `last_rational` 承接上一轮 `rationale`；旧跨轮反馈字段与过程内 verification 反馈已从链路中移除。
- `observe` 仍保留在 loop 内，但职责已收敛为事实压缩：最近工具结果、失败工具、文件读取缓存、diff 状态、变更文件和轻量 `signals`，不再承担“响应 verify failure”职责。
- 当前单任务 run 仍保留 token diagnostics：聚合 `prompt_tokens`、`completion_tokens`、`total_tokens`、`request_count`、`missing_usage_count` 和 `complete`；provider 缺少 `usage` 时不做本地估算，而是保留为“不完整但真实”。
- 当前 harness 的默认主赛道已进一步收敛到 `bug_fix`；`refactor`、`test_generation`、`code_understanding` 仍兼容，但默认不再依赖 loop 内 verify 反馈。
- 当前已新增显式结构摘要工具 `read_file_structure_summary(path)`，用于只读取指定文件的结构摘要；`.py` 文件会继续暴露 `class` / `def` 的起始行号，供后续 `read_file_range` 精读。
- 当前已落地运行时记忆污染治理第一版：文件一旦被 `apply_patch` 或 `replace_lines` 成功编辑，旧读取缓存会按整文件标记为 `stale`；只有后续重新读取后才恢复为 `fresh`。
- 当前 `observe_feedback` 已改名为 `observe_content`；后续轮次通过 `context_snapshot.fresh_context` 与 `context_snapshot.stale_context` 区分当前可信片段和已失效片段。
- 当前 stale 文件信息统一放在 `context_snapshot.stale_context`：`details` 记录每个文件的失效原因和旧覆盖范围，`reason`、`recommended_sequence`、`suggest` 作为所有 stale 文件共享的重读原则。
- 当前 `context_snapshot.stale_context.stale_file_paths` 的语义已收紧为“当前仍处于 stale 的文件列表”；如果某个文件已经完成重读恢复为 `fresh`，它应进入 `fresh_context.file_snippets` 而不是继续留在 stale 列表里。
- 当前 `ContextBuilder` 已补充白话中文注释，说明 `initial_guide`、`context_snapshot`、fresh/stale 文件片段、diff/command 压缩和召回策略的边界，符合 `docs/代码可读性规范.md` 的注释要求。
- 当前 `bug_fix` 提示词已补充收口规则：一旦当前 diff 已命中任务目标修改点，且针对任务描述的核心验证命令已经符合预期，模型应优先准备结束求解，而不是继续扩展读取外围函数。
- 当前模型返回的 `working_memory` 已收紧为更偏收口的四字段结构：`confirmed_facts`、`invalidated_beliefs`、`completed_actions`、`next_risks`；`context_snapshot.working_memory` 会额外带有 harness 注入的 `last_rational`；不再保留 `open_questions`，避免模型围绕“待确认问题”继续发散读取。

> 说明：下面保留了 Phase 8/Phase 9 早期推进记录，其中部分段落描述的是历史状态；当前行为以上方最新条目为准。

- `Phase 8` 已暂定完结，策略对比链路现在可以稳定产出 `summary.json` 与 `summary.md`。
- comparison summary 已覆盖聚合指标 delta、failure taxonomy delta、verification failure delta、observe trigger reason delta。
- comparison summary 已覆盖 `task_deltas`，可按任务展开 outcome、passed、steps、tool calls、verify、observe、observe reason、failure taxonomy、failing checks、diagnostic labels 差异。
- `task_deltas` 现已补齐代表性运行指针：`baseline_run_id`、`candidate_run_id`、`baseline_run_dir`、`candidate_run_dir`。
- `src/eval_runner.py` 已从损坏状态重建为可编译、可导入实现，并恢复 `eval` / `comparison` 全部已交付能力。
- 已补上实验套件入口，当前支持通过 `--experiment-suite-file` 一键执行一组固定策略实验。
- 已新增 `src/experiment_runner.py` 与 `experiment_suites/first_batch.json`，把首批三组策略实验固化为可复用清单。
- 已把 `eval_tasks/sample_batch.json` 从演示样例升级成更像真实研究集的固定任务集，当前覆盖 `general`、`bug_fix`、`code_understanding`、`test_generation`、`refactor` 五类任务。
- 已完成首批实验套件实跑，结果目录位于 `runs/research_batch_20260615_full/experiment-suite-first_batch/`。
- 首批实验当前得到三条初步结论：
  - `naive_recent_context` 相比 `file_recall_context` 在现有固定任务集上没有拉开差异，说明这批任务还不足以区分两种 context 策略。
  - `memory_off` 相比默认 memory 策略保留了同样的成功率，但把 `warning_rate` 从 `1.0` 降到了 `0.0`，同时把 `clean_pass_rate` 从 `0.0` 提升到 `1.0`，当前默认 memory 在这批任务上主要带来了冲突/污染类诊断噪声。
  - `verify_failure_only_observe` 相比默认 observe 策略没有降低成功率，但把平均步数从 `8` 降到 `7`，把平均 observe 次数从 `1` 降到 `0`，说明“observe 无进展就观察”在当前任务集上更像额外开销。
- `Phase 8` 交付时新增与保留的 comparison / experiment / task set 回归测试已通过；在本轮 `Phase 9` 补齐 schema 与 sandbox 后，当前全量 `python -m pytest -q` 结果为 `22 passed`。
- 当前已经具备“固定任务集上的策略实验外壳”，但还不具备“真实代码任务求解闭环”；现有 `loop`、`tools`、`verify` 仍以 stub 演示链路为主。
- `Phase 9` 第一块缺口已开始落地：现已支持在 eval task schema 中声明 `repo_subdir`、`workspace_mode`、`setup_commands`、`verify_commands`，并默认按“每题独立 sandbox 目录”执行 eval task。
- 当前 sandbox 工作区会在更短的临时目录下创建，避免 experiment suite 多层目录叠加后触发 Windows `cwd` 路径过长问题。
- 当前 `run_started` / `workspace_prepared` / `task_setup_started` / `task_setup_result` 已进入 trace，可回看每题原始仓库、实际执行仓库和准备命令结果。
- 当前 eval batch 已验证：任务内文件修改与 setup 产物会留在 sandbox 内，不再污染源仓库。
- 当前已补上 sandbox 清理/保留策略：支持 `always_keep`、`delete_on_success`、`keep_on_success`、`always_delete` 四种模式，默认使用 `delete_on_success`。
- 当前默认行为已改为“验证通过就删除 sandbox，验证失败则保留 sandbox”，兼顾磁盘占用与失败复盘。
- 当前 `sandbox_cleanup_result` 已进入 trace，运行报告中也会明确展示 sandbox 的保留策略、清理结果和目录位置。
- 当前 `verify_commands` 已真正接入验证链路：有任务级验证命令时优先执行真实验证，没有时才回退到旧的 `agent_notes.md` 演示验证。
- 当前真实验证结果会记录 `verification_mode` 与逐条 `verify_command_results`，可以在 trace 中直接看到每条验证命令的返回码与输出。
- 当前已验证：`verify_commands` 会直接影响 sandbox 保留决策，默认策略下“验证成功删 sandbox，验证失败留 sandbox”已经生效。
- 当前任务级验证已补上第一版 `verify_rules`：除 `verify_commands` 外，任务现在还可声明结构化通过条件，用于检查命令输出、文件存在性、文件是否包含或不包含指定文本。
- 当前真实验证已从“只看 verify 命令退出码”升级到“命令执行结果 + 结构化规则联合判定”，失败时会直接落到 `verification_result.checks`，便于 eval 和 trace 解释具体未满足条件。
- 当前 `verify_rules` 第二批规则类型已补齐：除首批正向包含/存在检查外，现已支持命令输出“不包含”检查、文件“不存在”检查、文件最小/最大行数检查，能更自然表达“错误输出不应出现”“临时文件应被删除”“测试文件至少补到几行”等真实任务通过条件。
- 当前已补上强制真实模型决策层第一版：`src/model.py` 不再保留 `rule_based` adapter，配置层只支持 `openai_compatible` provider。
- 当前模型如果不再需要继续读、改、查，直接返回空 `tool_calls` 即可进入最终验证。
- 当前模型工具计划已做 schema 校验：只允许 `search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff`，且 `tool_input` 必须是对象，并会校验字段名、必填字段和字段类型。
- 当前 `plan` 阶段模型配置、请求或响应失败会写入 `model_decision_failed` trace，并以 `stop_reason.code = model_error` 结束 run，不再回退到本地规则决策。
- 当前所有 `configs/*.json` 已统一切到 `openai_compatible`，默认使用 DeepSeek endpoint，并通过 `.env` 或系统环境变量中的 `DEEPSEEK_API_KEY` 提供密钥；无 API key 是预期的模型配置错误。
- 本轮已按测试环境规范使用 `D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe` 完成回归：`tests/test_loop.py tests/test_model.py` 为 `12 passed`，`tests/test_cli.py tests/test_eval.py tests/test_verify.py` 为 `23 passed`，全量 `pytest -q` 为 `40 passed`。

## 已完成

- `Phase 1` 到 `Phase 8` 已完成。
- `Phase 8` 已完成：
  - baseline / candidate strategy comparison runner
  - context strategy variants
  - memory on/off strategy variants
  - observe strategy variants
  - comparison delta summary
  - failure taxonomy / verification / observe reason deltas
  - task-level deltas
  - representative run pointers in task deltas
  - experiment suite runner
  - first batch experiment manifest
  - research-like fixed sample task set

## 当前最小闭环缺口

- 当前 `tool_calls` 仍是唯一执行源；`planned_actions` 和 `working_memory` 只承担可读说明与跨轮记忆职责。
- `verify` 已经更接近纯裁判，但任务级 `verify_rules` 设计仍需继续加强，尤其是面向 `bug_fix` 的“修好了没有、回归没回归”这类行为级验证。
- 过程诊断信息已经能从 `trace.jsonl` 反推，但当前 trace 查看体验仍偏原始；后续仍需继续加强 `trace_view.html`、报告摘要和高信号定位能力。
- `refactor`、`test_generation`、`code_understanding` 目前仍更适合作为兼容研究题；当前主要评测赛道仍应继续聚焦更难但可客观裁判的 `bug_fix` 任务。
- 文件缓存污染治理当前只做第一版整文件失效，还没有做“编辑后行号映射修补”或“片段级局部失效”；复杂编辑场景下仍可能带来额外重读成本。

## 下一步明确动作

- 继续扩充 `bug_fix` 任务和末尾最终 verify 规则，优先保证“是否修复”和“是否回归”可稳定裁判。
- 继续加强 trace、report 和 `trace_view.html`，重点提升 `model_decision`、收口信号、最终验证和 diff 快照的可读性。
- 当前主链路已把“是否继续 loop”的判断从模型侧结束字段收回到 harness，降低提示词歧义。
- 在拿到更多真实 trace 后，再决定是否把文件缓存治理从“整文件全失效”升级为“按区间失效 + 行号映射”。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先补齐“真实任务可运行、可验证、可复现”的最小闭环，再继续扩展更复杂的策略和指标。

## 本轮新增进展

- `observe` 已从固定 stub 替换为基于工具结果的真实进展判断。
- 当前进展判定规则：`git_diff.changed_file_count > 0` 视为有文件变更进展；任意 `apply_patch.tool_output.ok == true` 视为有成功编辑进展。
- `RuntimeState` 已新增 `progress_made`、`changed_files`、`failed_tool_count`、`observation_summary`，并在 `progress_observed` trace 事件中记录观察证据。
- 默认 `after_act_observe` 策略现在只在 `observe` 后未观察到进展时触发 `no_progress_after_observe`；验证失败后的 observe 逻辑保持不变。
- `run_finished.stop_reason.details` 已补充进展观察字段，运行报告已新增 `## 进展观察` 小节。
- 本轮未扩展 `verify_rules`，未处理 setup / verify failure taxonomy，未改 CLI 单次 verify 参数，也未删除 `build_phase_3_tool_sequence()`。
- `loop` 已从单轮执行升级为最小多轮求解：`runtime.max_steps` 现在表示最大求解轮数，默认配置已统一改为 `2`。
- 验证失败且仍有预算时，当前会进入 `observe`，再重新 `plan -> act -> observe -> verify`；验证通过则提前 finalize。
- 达到最大轮数仍未通过时，run 会以 `stop_reason.code = max_steps_reached` 收口，并继续执行 `finalize` 写完整报告。
- 第二轮 `plan` 现在会收到 `context_snapshot`，其中 `recent_facts` 包含上一轮观察摘要、最近工具结果摘要和失败工具摘要。
- `run_finished.stop_reason.details` 和报告已补充 `max_steps`、`iteration_count`、`observe_count`、`observe_trigger_reasons` 等多轮字段。

## 下一步顺序

1. 继续扩展任务级 `verify_rules`。
2. 把 setup / verify 失败收口成结构化 stop reason 和更稳定的 failure taxonomy。
3. 继续把 `observe` 从占位记录替换成能辅助重规划的真实观察链路。

## 新会话恢复指引

1. 阅读 `docs/SESSION_ENTRY.md`
2. 阅读 `docs/CURRENT_STATUS.md`
3. 阅读 `docs/PHASE_PROGRESS.md`
4. 优先查看 `src/loop.py`、`src/tools.py`、`src/verify.py`、`src/runner.py`
5. 再查看 `src/eval_runner.py`、`src/experiment_runner.py`、`eval_tasks/sample_batch.json`
6. 从“结构化任务级 verify 增强 + 真实模型/策略决策层 + stub loop 替换”继续推进

## Phase 9 本轮新增进展：第三批 verify_rules

- `src/verify.py` 已扩展第三批任务级 `verify_rules`，支持 JSON、diff、多文件聚合三类更贴近真实任务的断言。
- JSON 规则新增 `json_file_value_equals`，使用简单点号路径语法，例如 `a.b.0.name`，严格比较 `expected_value` 的原始 JSON 类型和值。
- diff 规则新增 `diff_changed_file_count_at_least`、`diff_changed_file_count_at_most`、`diff_contains_file`，只消费本次 run 已有的 `git_diff` 工具结果；没有 `git_diff` 时规则失败，不在 verify 阶段隐式重新生成 diff。
- 多文件聚合规则新增 `files_matching_count_at_least`、`files_matching_count_at_most`，支持 `glob`、`contains`、`not_contains`、`min_count`、`max_count`，并且只统计 repo root 内可按 UTF-8 读取的文本文件。
- `src/eval_runner.py` 的 task schema 清洗已保留 `json_path`、`expected_value`、`glob`、`min_count`、`max_count`；其中 `expected_value` 不被字符串化，保留字符串、数字、布尔、对象、数组等原始 JSON 类型。
- 本轮未修改 loop、CLI 单次 verify 参数、setup/verify failure taxonomy，也未删除 `build_phase_3_tool_sequence()`。

## Phase 9 下一步顺序

1. 把 setup / verify 失败收口成结构化 stop reason 和更稳定的 failure taxonomy。
2. 继续把 `observe` 从占位记录替换成能辅助重规划的真实观察链路。
3. 视真实任务需要继续扩展更高阶的 `verify_rules`。

## Phase 9 本轮新增进展：结构化失败收口与 observe content

- setup command 失败现在会在进入 loop 前停止 run，并写入 `stop_reason.code = setup_failed`；`stop_reason.details` 包含全部 setup 结果和失败命令，不再把 setup 失败混入普通模型/验证流程。
- verify 最终失败现在会以 `stop_reason.code = verification_failed` 收口，并继续执行 `finalize` 写完整报告；details 中包含失败检查名、失败 verify command、失败规则类别和 verify mode。
- eval outcome / failure taxonomy 已补稳定分类：setup 失败归为 `failed_setup` / `setup:command_returncode`，verify command 失败归为 `failed_verification` / `verification:verify_command_returncode`，verify rule 失败归为 `verification:verify_rule:<check>`。
- observe 现在会生成 `observe_content` trace 事件，并把工具结果、失败工具和轻量 signals 压缩进下一轮 `context_snapshot.recent_facts`。
- `eval_tasks/sample_batch.json` 已升级为 UTF-8 可读任务集，并给两个样例任务加入真实 `verify_commands` 与已实现的结构化 `verify_rules`。
- 本轮仍不新增 CLI 单次 verify 参数，不放开默认 `runtime.max_steps=2`。

## Phase 9 下一步顺序更新

1. 继续提升 `observe_content` 的事实压缩质量，减少下一轮 plan 重复读取或重复失败计划。
2. 基于升级后的 sample batch 做一轮 eval/comparison smoke，观察新 taxonomy 和 observe content 在报告里的可读性。
3. 只有在真实任务暴露需求后，再补 regex、JSON key/length、diff text 等更高阶 `verify_rules`。
## Phase 9 本轮新增进展：observe content 驱动上下文快照

- `observe_content` 现在是 `context_snapshot.recent_facts` 的事实来源，保留最近工具结果、失败工具和 signals。
- 第二轮及后续 `plan` 的 `model_decision` trace 会记录是否带有 `context_snapshot` 和 `observe_content`，用于确认模型是否收到上一轮事实快照。
- OpenAI compatible 请求依赖 `context_snapshot` 承载重规划证据，不再注入旧式跨轮 observe feedback。
- 单次 run 报告保留 observe 次数、触发原因和失败工具摘要，避免把 observe 误解为硬约束阶段。
- 本轮未开放 `runtime.max_steps > 2`，未新增 CLI 单次传 `verify_commands` / `verify_rules`，也未继续扩展新的 `verify_rules`。
## Phase 9 本轮新增进展：第四批 verify_rules

- `src/verify.py` 已扩展第四批任务级 `verify_rules`，覆盖命令输出 regex、JSON path/长度/key 结构断言，以及 diff 文本包含/不包含断言。
- 新增命令输出规则：`command_stdout_matches_regex`、`command_stderr_matches_regex`，使用 Python 标准库 `re.search`，非法 regex 会作为失败检查返回。
- 新增 JSON 结构规则：`json_path_exists`、`json_array_length_equals`、`json_array_length_at_least`、`json_array_length_at_most`、`json_object_key_exists`，继续复用简单点号路径语法。
- 新增 diff 文本规则：`diff_contains_text`、`diff_not_contains_text`，只消费当前 run 已有 `git_diff.tool_output.diffs[].diff`，不在 verify 阶段隐式生成 diff。
- `src/eval_runner.py` 的 task schema 清洗已保留 `regex`、`expected_length`、`min_length`、`max_length`、`key`，其中长度字段会归一化为整数。
- 本轮仍不修改 loop、observe、model prompt、CLI 单次 verify 参数、`runtime.max_steps` 或 setup/verify failure taxonomy。

## Phase 9 本轮新增进展：真实状态处理骨架

- `src/loop.py` 已将原 `_run_stub_state` 拆分为 `_run_ingest`、`_run_analyze`、`_run_plan`、`_run_act`、`_run_observe`、`_run_observe`、`_run_verify`、`_run_finalize` 等独立状态处理方法。
- `ingest` 阶段现在会输出真实输入摘要，并写入 `task_ingested` trace，包含任务类型、repo 路径、workspace mode、setup/verify 数量、verify rule 数量、max steps、配置 key 和模型配置摘要。
- `finalize` 阶段现在会输出真实结束摘要，并写入 `finalize_summary` trace，包含验证是否通过、是否观察到进展、变更文件、失败工具数、observe 次数、实际轮数、工具调用数和模型决策数。
- 本轮保持现有多轮 loop、模型决策、observe、observe、verify、stop reason 和 CLI 参数行为兼容；未扩展新的 `verify_rules`，未开放更高 `runtime.max_steps`。

## Phase 9 本轮新增进展：移除演示型 verify 回退

- `src/verify.py` 已移除默认 `stub_tool_chain` 回退，不再使用固定工具顺序、`agent_notes.md` 或演示 diff 判断任务完成。
- 当前验证入口支持三种显式任务级验证形态：仅 `verify_commands`、仅 `verify_rules`、以及二者组合。
- 当任务未配置 `verify_commands` 且未配置 `verify_rules` 时，验证会以 `verification_mode = missing_task_verification` 失败，并返回稳定检查项 `task_verification_configured`。
- 本轮未新增 `verify_rules` 类型，未修改 CLI 单次传 verify 参数、模型 prompt、observe、多轮 loop 或 `runtime.max_steps=2`。

## Phase 9 本轮新增进展：缺失任务级验证一等诊断

- `missing_task_verification` 现在会在 eval failure taxonomy 中稳定归类为 `verification:missing_task_verification`，不再只表现为普通检查项失败。
- eval failure taxonomy tags 会保留 `verification_mode:missing_task_verification`，同时继续保留 `verification_check:task_verification_configured`，便于 comparison 同时统计失败模式和具体检查项。
- 单次 run 报告的验证结果小节会明确说明任务未配置 `verify_commands` 或 `verify_rules`，因此当前 run 无法判定任务是否完成。
- 本轮只增强诊断归类和报告展示，未修改 loop、observe、model prompt、CLI 单次 verify 参数或 `verify_rules` 类型。

## Phase 9 本轮新增进展：Observe Feedback 强制驱动重规划

- 第二轮及后续 `plan` 现在通过 `context_snapshot.recent_facts` 接收上一轮事实，不再校验旧式 observe 硬约束。
- 模型是否回应上一轮事实由 `rationale`、`planned_actions`、`working_memory` 和后续工具行为共同体现，不再通过 harness 强制匹配失败约束字段。
- 如果模型重复上一轮失败路径，当前主要依赖 trace、report 和 eval 诊断暴露问题，而不是在 plan 阶段直接判为非法响应。
- `model_decision` trace 保留上下文可见性字段，用于确认带 `context_snapshot` 的重规划已经进入模型请求。
- OpenAI compatible prompt 继续说明 `context_snapshot` 的使用方式，不再注入旧式 observe feedback 硬约束。

## Phase 9 本轮新增进展：Eval/Comparison Smoke 与失败诊断统一

- `eval_tasks/sample_batch.json` 已补齐显式 `verify_commands` / `verify_rules`，当前样例任务不再依赖缺失验证或演示型回退判定完成。
- eval failure taxonomy 已统一覆盖 `setup:command_returncode`、`model:<error_type>`、`verification:verify_command_returncode`、`verification:verify_rule:<check>`、`verification:missing_task_verification`、`runtime:max_steps_reached`。
- failure taxonomy tags 已补齐 `model_error_type:*` 与 `runtime:max_steps_reached`，并继续保留 `outcome:*`、`stop_reason:*`、`verification_mode:*`、`verification_check:*` 等诊断维度。
- 单次 run 报告新增 `## 失败诊断` 小节，展示 stop reason、模型错误类型、setup 失败命令数或验证失败摘要。
- 回归测试已覆盖升级后的 sample batch eval smoke、comparison smoke、以及新增失败 taxonomy/tag 口径。

## Phase 9 本轮新增进展：真实 Loop 内核扫尾

- `src/tools.py` 已删除旧的 `build_phase_3_tool_sequence()`，当前 loop 工具执行只来自模型返回的合法 `tool_calls`。
- `src/trace.py` 和 `src/runner.py` 已移除当前代码中的 stub/占位报告命名，改为初始化报告和真实 loop 运行语义。
- 测试 fake model 与 `sample_batch` 默认产物已从 `agent_notes.md` 切换为 `run_evidence.md`，不再把历史演示文件作为当前完成标准。
- 新增回归断言确保 `src/` 不再出现 `build_phase_3_tool_sequence`、`_run_stub_state`、`Phase 3 工具闭环` 等旧内核标记。
- 本轮不改变多轮 loop 行为、不开放更高 `runtime.max_steps`、不新增 CLI verify 参数或 verify rule 类型。

## Phase 9 本轮新增进展：模型接口与运行体验加固

- `ModelError` 已新增安全 `details`，用于记录 provider、model、base_url、timeout、字段路径、HTTP 状态码等排障信息，不记录 API key 值。
- `OpenAICompatibleModelAdapter` 现在会校验 `base_url` 必须以 `http://` 或 `https://` 开头；缺少 API key 时 details 会显示 `api_key_env`。
- HTTP 非 2xx、URL 错误、超时、OS 网络错误、fake model 非法 JSON、模型响应缺字段或工具计划非法都会携带可定位的安全摘要。
- `model_decision_failed` trace、`run_finished.stop_reason.details` 和报告 `失败诊断` 小节都会展示模型错误摘要，方便真实运行失败后定位配置、网络或响应问题。
- README 已新增“模型配置与排障”说明；本轮未改变模型请求/响应主 schema，也未恢复 `rule_based`。

## Phase 9 本轮新增进展：README/使用手册与 MVP 验收冻结

- README 已补齐最小使用路径入口：配置模型、单次 run、eval task、report、eval、comparison、排障。
- 新增 `docs/USAGE_GUIDE.md`，固定 OpenAI compatible 配置、eval task 写法、report 阅读方式、eval summary 和 comparison delta 阅读方法。
- 新增 `docs/MVP_ACCEPTANCE.md`，固定全量测试、sample eval smoke、sample comparison smoke 的验收命令和预期产物。
- 新增 `tests/test_mvp_acceptance_docs.py`，确保 README、使用手册、MVP 验收文档持续包含关键命令、路径和边界说明。
- MVP 当前边界已明确记录：不支持 `rule_based`、无 API key 会 `model_error`、CLI 单次运行暂不传 verify 参数、默认 `runtime.max_steps=2`、回归测试使用 fake model。

## Phase 9 本轮新增进展：跨轮计划与工具入参类型校验

- 模型决策 JSON 中的 `working_memory` 已升级为结构化运行时记忆对象，固定包含 `confirmed_facts`、`invalidated_beliefs`、`completed_actions`、`next_risks` 四个字段；每个字段允许 `str | list[str]`。
- 当前 `working_memory` 只作为模型自维护的记忆文档；是否继续 loop 仍只看 `tool_calls` 是否为空。
- 下一轮 `context_snapshot.working_memory` 会把上一轮模型返回的工作记忆对象回填给模型，并额外注入 `last_rational`；如果上一轮判断被推翻，需要由模型自己改写对应字段，而不是依赖 harness 自动补写。
- harness 不再合并上一轮 done list 与本轮返回结果；每轮只保存模型最新返回的四字段工作记忆，再由 `ContextBuilder` 在下一轮快照中补入 `last_rational`。
- `model_decision` trace、plan state result、`finalize_summary` 和 `run_finished.stop_reason.details` 均会保留当前模型返回的 `working_memory`；报告的“模型返回摘要”仍按四类模型自维护工作记忆展示。
- OpenAI compatible 请求中的结构化 `decision_schema` 已明确：`tool_calls` 是唯一执行源、`planned_actions` 是本轮说明、`working_memory` 是模型维护的结构化工作记忆，而不是 harness 维护的累计 done list。
- 工具入参校验从“字段名/必填项”扩展到类型校验，覆盖 `string`、`integer`、`null`、`array` 以及数组元素类型；例如 `apply_patch.new_text = null` 会以 `ModelResponseError` / `model_error` 收口。
- `CoreToolRunner.apply_patch()` 增加防御式输入检查，即使绕过模型校验传入非法值，也会返回结构化 `invalid_tool_input`，不再抛出 `TypeError` traceback。
- 本轮不新增 `verify_rules`，不改变 `runtime.max_steps=2`，不做 `planned_actions` 与 `tool_calls` 的一致性硬诊断，继续交给 prompt 和模型自觉对齐。

# 2026-06-22 补充记录

- 已新增 `live_trace_view.html`、`live_trace_snapshot.json` 和 `live_trace_snapshot.js`，run 启动后即可查看实时对话式执行过程。
- 已新增 `model_request_prepared` trace 事件，用于落地每轮真实的模型请求快照，右侧 viewer 直接显示该 payload。

