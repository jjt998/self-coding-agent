# 目录结构说明

这份文档解释 `self-coding-agent` 的目录安排。整体原则是：按 harness 的工程边界拆模块，而不是按零散功能堆文件。这样后续研究 `loop`、`context`、`memory`、`tool use`、`eval` 时，每一层都能独立替换、观察和评测。

## 推荐目录结构

```text
self-coding-agent/
  pyproject.toml
  README.md
  configs/
  docs/
  src/
     cli/
     core/
     models/
     tools/
     context/
     memory/
     trace/
     eval/
     reports/
  eval_tasks/
  runs/
  tests/
```

## 根目录

### `pyproject.toml`

Python 项目配置文件。

后续用于配置：

- 项目包信息。
- 运行依赖。
- 开发依赖。
- 测试配置。
- 格式化和 lint 配置。
- CLI 入口。

### `README.md`

项目入口说明文档。

它面向使用者，应该说明：

- 项目是什么。
- 如何安装。
- 如何运行单个任务。
- 如何运行 eval。
- 如何查看 trace 和 report。

### `docs/`

设计文档目录。

这里存放“为什么这么设计”，不是运行时依赖。当前已有：

- `PRD.md`
- `PRD.zh-CN.md`
- `ARCHITECTURE.md`
- `ARCHITECTURE.zh-CN.md`
- `MONTH_PLAN.md`
- `MONTH_PLAN.zh-CN.md`
- `DIRECTORY_GUIDE.zh-CN.md`

### `configs/`

运行配置和策略配置目录。

示例：

```text
configs/
  default.yaml
  strategies/
    baseline.yaml
    memory_off.yaml
    file_recall_plus_summary.yaml
```

它的价值是让策略实验通过配置切换，而不是通过改代码完成。

例如：

- 切换 context 策略。
- 切换 memory 开关。
- 切换 reflect 触发规则。
- 调整 step/tool budget。
- 指定模型 provider。

## `src/`

这是主包目录，项目核心代码都放在这里。

### `cli/`

命令行入口层。

职责：

- 解析用户命令。
- 加载配置。
- 接收 repo、task、model、strategy、budget 等参数。
- 调用 orchestrator 或 eval runner。

示例命令形态：

```bash
self-agent run --repo . --task "fix login bug"
self-agent eval --task-set eval_tasks/basic
```

`cli/` 不应该承载复杂 agent 逻辑。它只负责把命令行参数转换为系统调用。

### `core/`

核心控制层。

这里放 agent loop、状态机、运行时对象和停止条件。它是 harness 的中枢。

典型文件：

- `loop.py`：状态机主循环。
- `state.py`：`ingest`、`analyze`、`plan`、`act`、`observe`、`reflect`、`verify`、`finalize` 状态定义。
- `runtime.py`：单次 run 的运行时状态。
- `stop.py`：预算、无进展、stop reason 判断。

核心职责：

- 控制状态流转。
- 维护 run 生命周期。
- 调用 context、memory、tools、model、trace 等模块。
- 判断是否继续、反思、验证或结束。

### `models/`

模型适配层。

职责是屏蔽不同模型 provider 的 API 差异，让上层 agent loop 不直接依赖某个厂商接口。

典型文件：

- `base.py`：统一模型接口。
- `openai_adapter.py`：OpenAI 模型适配。

未来可扩展：

- `anthropic_adapter.py`
- `local_adapter.py`

这一层应该抽象的不只是 API 形状，还包括能力差异：

- 是否支持原生 tool calling。
- 是否支持 structured output。
- 最大上下文长度。
- usage/cost 元数据。
- provider-specific 错误处理。

### `tools/`

工具层。

这里放 agent 可以调用的本地工具。

MVP 核心工具：

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

典型文件：

- `registry.py`：工具注册表。
- `filesystem.py`：文件读取、路径限制等。
- `command.py`：命令执行、超时、白名单、危险命令阻断。
- `git.py`：`git_diff` 等 git 相关能力。

工具层要求：

- 结构化输入。
- 结构化输出。
- 记录 status、error、duration、metadata。
- 工具调用必须进入 trace。

### `context/`

上下文构建层。

职责是决定模型下一步能看到什么。

典型文件：

- `builder.py`：组装 `task_context`、`repo_context`、`runtime_context`、`memory_context`。
- `recall.py`：文件级召回。
- `compression.py`：摘要、裁剪、长内容压缩。

核心设计：

- 高精度信息原文注入。
- 大块信息摘要注入。
- 大量低概率信息只做索引或引用。
- 上下文裁剪按信息价值，而不是只按时间。

这是项目的研究重点之一。

### `memory/`

记忆系统。

分为运行时记忆和长期记忆。

典型文件：

- `runtime_memory.py`：单次 run 内的结构化状态和经验。
- `long_term_memory.py`：跨 run 的稳定知识。
- `store.py`：JSON 或 SQLite 存储实现。

运行时记忆记录：

- 当前计划。
- 已读文件。
- 已修改文件。
- 候选文件。
- 已尝试路径。
- 关键工具结果。
- 关键错误。
- verify 状态。
- 当前 diff。
- 活跃假设。
- progress/no-progress 信号。

长期记忆记录：

- repo 稳定事实。
- 构建和测试命令。
- 关键模块和入口点。
- 用户偏好。
- 成功修复模式。
- 特定任务类型在当前 repo 上的经验。

第一版不做 embedding。长期记忆使用结构化字段、标签筛选和关键词搜索。

### `trace/`

结构化运行记录层。

职责是把每一步 agent 行为写成 JSONL event。

典型文件：

- `events.py`：事件 schema。
- `writer.py`：JSONL 写入器。
- `replay.py`：trace replay。

核心事件：

- `run_started`
- `state_entered`
- `context_built`
- `model_requested`
- `model_responded`
- `tool_called`
- `tool_completed`
- `memory_read`
- `memory_written`
- `verify_completed`
- `reflect_completed`
- `state_transitioned`
- `run_finished`

这一层是 eval、debug 和 replay 的基础。

### `eval/`

评测层。

职责是批量运行任务、计算指标、输出诊断。

典型文件：

- `task_spec.py`：eval task schema。
- `runner.py`：批量任务运行器。
- `metrics.py`：result/process metrics。
- `diagnostics.py`：`context_miss`、`wrong_tool_choice`、`repeated_no_progress` 等诊断标签。

它回答的问题是：

- 策略是否真的变好。
- 成本是否上升。
- 失败类型是否变化。
- 哪一层最需要优化。

### `reports/`

报告生成层。

职责是把 trace 和 eval 结果转成人可读 Markdown。

典型文件：

- `markdown.py`：单次 run report 和批量 eval summary。

它不负责执行任务，只负责展示结果。

## `eval_tasks/`

固定评测任务目录。

示例：

```text
eval_tasks/
  basic/
    bug_fix_001.yaml
    code_understanding_001.yaml
    test_generation_001.yaml
```

这些任务组成项目的小型 benchmark。策略对比时必须固定 task set，才能公平比较。

每个任务应该包含：

- `id`
- `task_type`
- `repo`
- `instruction`
- `success_criteria`
- `allowed_tools`
- `budgets`
- `validation`
- `expected_touched_files`
- `forbidden_touched_files`
- `tags`

## `runs/`

运行产物目录。

示例：

```text
runs/
  run_20260611_001/
    trace.jsonl
    report.md
    artifacts/
    final_diff.patch
```

这里存放：

- trace。
- report。
- diff。
- 工具输出 artifact。
- eval summary。

`runs/` 可以被清理，不应该存放手写源代码。

## `tests/`

项目自身测试目录。

这里测试的是 harness 本身，不是 agent 要修改的目标仓库。

测试对象包括：

- 状态机跳转。
- stop reason 判断。
- 工具安全限制。
- context builder。
- memory store。
- trace writer。
- eval metrics。
- diagnostics。

## 模块职责总结

- `core/` 管控制流。
- `models/` 管模型差异。
- `tools/` 管 agent 能做什么。
- `context/` 管模型能看到什么。
- `memory/` 管信息如何留下来。
- `trace/` 管过程如何记录。
- `eval/` 管结果如何比较。
- `reports/` 管人如何阅读结果。
- `configs/` 管策略如何切换。
- `eval_tasks/` 管固定任务集。
- `runs/` 管运行产物。

这个拆法的主要好处是：后续想研究某一层时，可以尽量只替换那一层。例如研究 memory 是否有效时，主要切换 `memory/` 和 `configs/`，不需要改动 `core/` 的状态机。
