# 当前状态

## 最后更新时间

- 日期：2026-06-16

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
- 当前已补上 sandbox 清理/保留策略：支持 `always_keep`、`delete_on_success`、`always_delete` 三种模式，默认使用 `delete_on_success`。
- 当前默认行为已改为“验证通过就删除 sandbox，验证失败则保留 sandbox”，兼顾磁盘占用与失败复盘。
- 当前 `sandbox_cleanup_result` 已进入 trace，运行报告中也会明确展示 sandbox 的保留策略、清理结果和目录位置。
- 当前 `verify_commands` 已真正接入验证链路：有任务级验证命令时优先执行真实验证，没有时才回退到旧的 `agent_notes.md` 演示验证。
- 当前真实验证结果会记录 `verification_mode` 与逐条 `verify_command_results`，可以在 trace 中直接看到每条验证命令的返回码与输出。
- 当前已验证：`verify_commands` 会直接影响 sandbox 保留决策，默认策略下“验证成功删 sandbox，验证失败留 sandbox”已经生效。
- 当前任务级验证已补上第一版 `verify_rules`：除 `verify_commands` 外，任务现在还可声明结构化通过条件，用于检查命令输出、文件存在性、文件是否包含或不包含指定文本。
- 当前真实验证已从“只看 verify 命令退出码”升级到“命令执行结果 + 结构化规则联合判定”，失败时会直接落到 `verification_result.checks`，便于 eval 和 trace 解释具体未满足条件。
- 当前 `verify_rules` 第二批规则类型已补齐：除首批正向包含/存在检查外，现已支持命令输出“不包含”检查、文件“不存在”检查、文件最小/最大行数检查，能更自然表达“错误输出不应出现”“临时文件应被删除”“测试文件至少补到几行”等真实任务通过条件。
- 当前已补上强制真实模型决策层第一版：`src/model.py` 不再保留 `rule_based` adapter，配置层只支持 `openai_compatible` provider。
- 当前 OpenAI 兼容决策层会调用 `/chat/completions`，要求模型返回结构化 JSON：`summary`、`rationale`、`planned_actions`、`tool_calls`。
- 当前模型工具计划已做最小校验：只允许 `search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff`，且 `tool_input` 必须是对象。
- 当前 `plan` 阶段模型配置、请求或响应失败会写入 `model_decision_failed` trace，并以 `stop_reason.code = model_error` 结束 run，不再回退到本地规则决策。
- 当前所有 `configs/*.json` 已统一切到 `openai_compatible`，默认要求通过 `OPENAI_API_KEY` 提供密钥；无 API key 是预期的模型配置错误。
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
