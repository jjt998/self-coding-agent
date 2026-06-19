# 当前状态

## 最后更新时间

- 日期：2026-06-19

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
- 当前 OpenAI 兼容决策层会调用 `/chat/completions`，要求模型返回结构化 JSON：`summary`、`rationale`、`planned_actions`、`cross_round_plan`、`tool_calls`。
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
  - reflect strategy variants
  - comparison delta summary
  - failure taxonomy / verification / reflect reason deltas
  - task-level deltas
  - representative run pointers in task deltas
  - experiment suite runner
  - first batch experiment manifest
  - research-like fixed sample task set

## 当前最小闭环缺口

- 决策层已切到强制真实模型接口，`loop` 已具备最小多轮求解能力；但当前仍缺更完整的真实任务求解内核，`src/loop.py` 仍有大段 `_run_stub_state`，`reflect` 仍主要是占位记录而不是会生成修正策略的真实反思。
- 缺少真实任务验证机制：当前 `src/verify.py` 主要验证 `agent_notes.md`、固定工具顺序和演示型 diff，不足以判断 bug fix、重构、测试补全等真实任务是否完成。
- 真实任务 task schema 已补上第一版最小字段，`verify_commands` 也已接入执行，但还缺“通过条件”的更细粒度结构化解释与 richer verification schema。
- 真实任务 task schema 已补上 `verify_rules` 第二版，但当前仍缺更高层的结构化断言，例如面向 JSON / diff / 多文件聚合结果的验证语义。
- 任务级隔离/重置能力已补上第一版：当前固定采用“每题绑定一个独立 sandbox 目录”的方案，并补上了基础清理/保留策略；后续可继续补配额控制与更精细的保留规则。
- 当前已接入第一版 OpenAI 兼容模型决策层，但模型 prompt、工具选择策略和多步推进回路仍是最小版本。

## 下一步明确动作

- 继续把 `loop` 从 stub 链路替换成真实任务求解链路，下一步重点是让 `reflect` 和后续 plan 更稳定地利用验证失败证据。
- 继续扩展任务级 `verify_rules`，优先补 JSON / diff / 多文件聚合类验证语义，把“通过条件更可解释的结构化验证”做成更完整 schema。
- 在 sandbox 中补任务级准备步骤之后的真实执行/失败收口，让 setup 失败、verify 失败都能沉淀为结构化 stop reason，并进一步稳定 failure taxonomy。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先补齐“真实任务可运行、可验证、可复现”的最小闭环，再继续扩展更复杂的策略和指标。

## 本轮新增进展

- `observe` 已从固定 stub 替换为基于工具结果的真实进展判断。
- 当前进展判定规则：`git_diff.changed_file_count > 0` 视为有文件变更进展；任意 `apply_patch.tool_output.ok == true` 视为有成功编辑进展。
- `RuntimeState` 已新增 `progress_made`、`changed_files`、`failed_tool_count`、`observation_summary`，并在 `progress_observed` trace 事件中记录观察证据。
- 默认 `low_progress_plus_verify_reflect` 策略现在只在 `observe` 后未观察到进展时触发 `no_progress_after_observe`；验证失败后的 reflect 逻辑保持不变。
- `run_finished.stop_reason.details` 已补充进展观察字段，运行报告已新增 `## 进展观察` 小节。
- 本轮未扩展 `verify_rules`，未处理 setup / verify failure taxonomy，未改 CLI 单次 verify 参数，也未删除 `build_phase_3_tool_sequence()`。
- `loop` 已从单轮执行升级为最小多轮求解：`runtime.max_steps` 现在表示最大求解轮数，默认配置已统一改为 `2`。
- 验证失败且仍有预算时，当前会进入 `reflect`，再重新 `plan -> act -> observe -> verify`；验证通过则提前 finalize。
- 达到最大轮数仍未通过时，run 会以 `stop_reason.code = max_steps_reached` 收口，并继续执行 `finalize` 写完整报告。
- 第二轮 `plan` 现在会收到 `runtime_feedback`，包含上一轮观察摘要、最近工具结果摘要和上一轮验证结果。
- `run_finished.stop_reason.details` 和报告已补充 `max_steps`、`iteration_count`、`reflect_count`、`reflect_trigger_reasons` 等多轮字段。

## 下一步顺序

1. 继续扩展任务级 `verify_rules`。
2. 把 setup / verify 失败收口成结构化 stop reason 和更稳定的 failure taxonomy。
3. 继续把 `reflect` 从占位记录替换成能辅助重规划的真实反思链路。

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
2. 继续把 `reflect` 从占位记录替换成能辅助重规划的真实反思链路。
3. 视真实任务需要继续扩展更高阶的 `verify_rules`。

## Phase 9 本轮新增进展：结构化失败收口与 reflect feedback

- setup command 失败现在会在进入 loop 前停止 run，并写入 `stop_reason.code = setup_failed`；`stop_reason.details` 包含全部 setup 结果和失败命令，不再把 setup 失败混入普通模型/验证流程。
- verify 最终失败现在会以 `stop_reason.code = verification_failed` 收口，并继续执行 `finalize` 写完整报告；details 中包含失败检查名、失败 verify command、失败规则类别和 verify mode。
- eval outcome / failure taxonomy 已补稳定分类：setup 失败归为 `failed_setup` / `setup:command_returncode`，verify command 失败归为 `failed_verification` / `verification:verify_command_returncode`，verify rule 失败归为 `verification:verify_rule:<check>`。
- reflect 现在会生成 `reflect_feedback` trace 事件，并把上一轮 observation、verify failure、失败工具摘要、建议关注点传入下一轮 `runtime_feedback.previous_reflect_feedback`。
- `eval_tasks/sample_batch.json` 已升级为 UTF-8 可读任务集，并给两个样例任务加入真实 `verify_commands` 与已实现的结构化 `verify_rules`。
- 本轮仍不新增 CLI 单次 verify 参数，不放开默认 `runtime.max_steps=2`。

## Phase 9 下一步顺序更新

1. 继续把 reflect feedback 从“结构化建议”接到更真实的模型提示/策略约束，减少重复失败计划。
2. 基于升级后的 sample batch 做一轮 eval/comparison smoke，观察新 taxonomy 和 reflect feedback 在报告里的可读性。
3. 只有在真实任务暴露需求后，再补 regex、JSON key/length、diff text 等更高阶 `verify_rules`。
## Phase 9 本轮新增进展：reflect feedback 驱动重规划

- `runtime_feedback.previous_reflect_feedback` 现在会携带模型可直接消费的 `replan_constraints`，包括 `failure_reason`、`must_address`、`avoid_exact_tool_sequence`、`failed_check_names`、`suggested_tools` 等字段。
- 第二轮及后续 `plan` 的 `model_decision` trace 会记录 `has_reflect_feedback` 和 `reflect_feedback_summary`，用于确认模型是否收到上一轮反思约束。
- OpenAI compatible 请求增加了重规划提示：存在 `previous_reflect_feedback` 时，模型必须在 `rationale` / `planned_actions` 中回应失败证据，并避免无解释地重复完全相同的失败工具序列。
- 单次 run 报告新增 `## 反思反馈` 小节，展示最近一次 reflect trigger、失败检查、建议关注点和需要避免重复的工具序列。
- 本轮未开放 `runtime.max_steps > 2`，未新增 CLI 单次传 `verify_commands` / `verify_rules`，也未继续扩展新的 `verify_rules`。
## Phase 9 本轮新增进展：第四批 verify_rules

- `src/verify.py` 已扩展第四批任务级 `verify_rules`，覆盖命令输出 regex、JSON path/长度/key 结构断言，以及 diff 文本包含/不包含断言。
- 新增命令输出规则：`command_stdout_matches_regex`、`command_stderr_matches_regex`，使用 Python 标准库 `re.search`，非法 regex 会作为失败检查返回。
- 新增 JSON 结构规则：`json_path_exists`、`json_array_length_equals`、`json_array_length_at_least`、`json_array_length_at_most`、`json_object_key_exists`，继续复用简单点号路径语法。
- 新增 diff 文本规则：`diff_contains_text`、`diff_not_contains_text`，只消费当前 run 已有 `git_diff.tool_output.diffs[].diff`，不在 verify 阶段隐式生成 diff。
- `src/eval_runner.py` 的 task schema 清洗已保留 `regex`、`expected_length`、`min_length`、`max_length`、`key`，其中长度字段会归一化为整数。
- 本轮仍不修改 loop、reflect、model prompt、CLI 单次 verify 参数、`runtime.max_steps` 或 setup/verify failure taxonomy。

## Phase 9 本轮新增进展：真实状态处理骨架

- `src/loop.py` 已将原 `_run_stub_state` 拆分为 `_run_ingest`、`_run_analyze`、`_run_plan`、`_run_act`、`_run_observe`、`_run_reflect`、`_run_verify`、`_run_finalize` 等独立状态处理方法。
- `ingest` 阶段现在会输出真实输入摘要，并写入 `task_ingested` trace，包含任务类型、repo 路径、workspace mode、setup/verify 数量、verify rule 数量、max steps、配置 key 和模型配置摘要。
- `finalize` 阶段现在会输出真实结束摘要，并写入 `finalize_summary` trace，包含验证是否通过、是否观察到进展、变更文件、失败工具数、reflect 次数、实际轮数、工具调用数和模型决策数。
- 本轮保持现有多轮 loop、模型决策、observe、reflect、verify、stop reason 和 CLI 参数行为兼容；未扩展新的 `verify_rules`，未开放更高 `runtime.max_steps`。

## Phase 9 本轮新增进展：移除演示型 verify 回退

- `src/verify.py` 已移除默认 `stub_tool_chain` 回退，不再使用固定工具顺序、`agent_notes.md` 或演示 diff 判断任务完成。
- 当前验证入口支持三种显式任务级验证形态：仅 `verify_commands`、仅 `verify_rules`、以及二者组合。
- 当任务未配置 `verify_commands` 且未配置 `verify_rules` 时，验证会以 `verification_mode = missing_task_verification` 失败，并返回稳定检查项 `task_verification_configured`。
- 本轮未新增 `verify_rules` 类型，未修改 CLI 单次传 verify 参数、模型 prompt、reflect、多轮 loop 或 `runtime.max_steps=2`。

## Phase 9 本轮新增进展：缺失任务级验证一等诊断

- `missing_task_verification` 现在会在 eval failure taxonomy 中稳定归类为 `verification:missing_task_verification`，不再只表现为普通检查项失败。
- eval failure taxonomy tags 会保留 `verification_mode:missing_task_verification`，同时继续保留 `verification_check:task_verification_configured`，便于 comparison 同时统计失败模式和具体检查项。
- 单次 run 报告的验证结果小节会明确说明任务未配置 `verify_commands` 或 `verify_rules`，因此当前 run 无法判定任务是否完成。
- 本轮只增强诊断归类和报告展示，未修改 loop、reflect、model prompt、CLI 单次 verify 参数或 `verify_rules` 类型。

## Phase 9 本轮新增进展：Reflect Feedback 强制驱动重规划

- 第二轮及后续 `plan` 现在会校验模型是否真正响应 `previous_reflect_feedback.replan_constraints`，不再只把 reflect feedback 作为提示和展示信息。
- 模型决策必须在 `rationale`、`summary` 或 `planned_actions` 中回应 `failure_reason`、`failed_check_names`、`must_address`；否则 plan 阶段以 `ModelResponseError` 收口为 `model_error`。
- 如果模型完全重复 `avoid_exact_tool_sequence` 中上一轮失败工具序列，必须在 `rationale` 中说明重复原因；无解释重复会被判定为模型响应非法。
- `model_decision` trace 新增 `reflect_constraints_acknowledged`，用于确认带 reflect feedback 的重规划已经通过硬约束校验。
- OpenAI compatible prompt 已改为中文硬约束说明，要求模型在重规划时明确回应反思证据并避免无解释重复失败工具序列。

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

- 模型决策 JSON 新增 `cross_round_plan`，用于记录跨轮安排和后续轮次意图；`planned_actions` 明确只描述本轮 `tool_calls` 实际会执行的动作。
- 下一轮 `runtime_feedback` 新增 `previous_cross_round_plan`，模型可以在重规划时看到上一轮给出的跨轮安排，而不再把跨轮意图混入 `planned_actions`。
- `model_decision` trace、plan state result、`finalize_summary` 和 `run_finished.stop_reason.details` 均会保留当前跨轮计划；报告的“模型返回摘要”也会展示 `cross_round_plan`。
- OpenAI compatible 请求新增结构化 `decision_schema`，明确 `tool_calls` 是唯一执行源、`planned_actions` 是本轮说明、`cross_round_plan` 是跨轮计划。
- 工具入参校验从“字段名/必填项”扩展到类型校验，覆盖 `string`、`integer`、`null`、`array` 以及数组元素类型；例如 `apply_patch.new_text = null` 会以 `ModelResponseError` / `model_error` 收口。
- `CoreToolRunner.apply_patch()` 增加防御式输入检查，即使绕过模型校验传入非法值，也会返回结构化 `invalid_tool_input`，不再抛出 `TypeError` traceback。
- 本轮不新增 `verify_rules`，不改变 `runtime.max_steps=2`，不做 `planned_actions` 与 `tool_calls` 的一致性硬诊断，继续交给 prompt 和模型自觉对齐。
