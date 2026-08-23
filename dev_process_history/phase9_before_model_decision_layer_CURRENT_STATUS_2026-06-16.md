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
- 本轮分项回归已通过：`tests/test_verify.py`、`tests/test_eval.py`、`tests/test_cli.py`、`tests/test_loop.py` 均通过；全量 `python -m pytest -q` 在 Windows `.pytest_tmp` 清理阶段仍偶发文件锁报错，这属于测试环境清理噪声，不是当前功能回归。

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
- 真实任务 task schema 已补上第一版最小字段，`verify_commands` 也已接入执行，但还缺“通过条件”的更细粒度结构化解释与 richer verification schema。
- 真实任务 task schema 已补上 `verify_rules` 第二版，但当前仍缺更高层的结构化断言，例如面向 JSON / diff / 多文件聚合结果的验证语义。
- 任务级隔离/重置能力已补上第一版：当前固定采用“每题绑定一个独立 sandbox 目录”的方案，并补上了基础清理/保留策略；后续可继续补配额控制与更精细的保留规则。
- 缺少真实模型驱动的决策层：当前策略对比主要比较 context / memory / reflect 外壳，还没有接入真正的任务级模型决策与工具选择回路。

## 下一步明确动作

- 接入真实模型/策略决策层，让当前 harness 先具备真实任务级决策入口。
- 在不破坏现有 trace / summary / comparison 结构的前提下，把 `loop` 从 stub 链路逐步替换成真实任务求解链路。
- 继续扩展任务级 `verify_rules`，优先补 JSON / diff / 多文件聚合类验证语义，把“通过条件更可解释的结构化验证”做成更完整 schema。
- 在 sandbox 中补任务级准备步骤之后的真实执行/失败收口，让 setup 失败、verify 失败都能沉淀为结构化 stop reason，并进一步稳定 failure taxonomy。

## 当前阻塞

- 暂无外部阻塞。
- 当前主要约束是继续保持 MVP 节奏，优先补齐“真实任务可运行、可验证、可复现”的最小闭环，再继续扩展更复杂的策略和指标。

## 新会话恢复指引

1. 阅读 `docs/SESSION_ENTRY.md`
2. 阅读 `docs/CURRENT_STATUS.md`
3. 阅读 `docs/PHASE_PROGRESS.md`
4. 优先查看 `src/loop.py`、`src/tools.py`、`src/verify.py`、`src/runner.py`
5. 再查看 `src/eval_runner.py`、`src/experiment_runner.py`、`eval_tasks/sample_batch.json`
6. 从“结构化任务级 verify 增强 + 真实模型/策略决策层 + stub loop 替换”继续推进
