# 使用手册

本文档固定第一版 MVP 的最小使用路径：配置模型、编写 eval task、查看 report、运行 eval、运行 comparison。

## 1. 配置模型

配置文件位于 `configs/`。当前只支持 OpenAI 兼容模型接口：

```json
{
  "model": {
    "provider": "openai_compatible",
    "name": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_seconds": 30
  }
}
```

真实运行前复制 `.env.example` 为 `.env`，并在 `.env` 中填写 API key：

```powershell
Copy-Item .env.example .env
```

`.env` 示例：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek API key
```

程序启动时会自动加载 `.env`；系统环境变量优先于 `.env`。缺少 API key 会按预期停止为 `model_error`。测试环境使用 `SELF_CODING_AGENT_FAKE_MODEL_RESPONSE` 注入假模型响应，不访问外网。

## 2. 运行单次任务

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --task "整理项目并生成说明" `
  --repo-root . `
  --output-root runs `
  --config-name default
```

单次运行会生成：

- `trace.jsonl`
- `report.md`
- `config_snapshot.json`

## 3. 编写 eval task

eval task 使用 JSON。需要成功判定的任务必须显式配置 `verify_commands` 或 `verify_rules`。

```json
{
  "tasks": [
    {
      "name": "demo_task",
      "task": "完成一个可验证的小任务",
      "task_type": "general",
      "verify_commands": [["python", "-c", "print('ok')"]],
      "verify_rules": [
        {
          "type": "command_stdout_contains",
          "command_index": 1,
          "contains": "ok"
        }
      ],
      "expectation": {
        "passed": true,
        "outcome": "passed_cleanly"
      }
    }
  ]
}
```

未配置 `verify_commands` 且未配置 `verify_rules` 时，验证会失败为 `missing_task_verification`。

## 4. 查看 report

`report.md` 是面向人的单次运行报告。重点查看：

- `运行摘要`：总步数、最大轮数、实际轮数、reflect 次数、stop reason。
- `失败诊断`：setup、model、verify、max steps 等失败摘要。
- `Token 消耗`：单任务模型请求数、缺失 usage 请求数、`prompt_tokens`、`completion_tokens`、`total_tokens`。
- `进展观察`：是否观察到文件变更、变更文件数、失败工具数。
- `反思反馈`：最近一次 reflect trigger、失败检查、建议关注点。
- `模型返回摘要`：最近一次模型显式返回的 summary、rationale、loop_end、planned_actions、donelist 和 tool_calls；其中 `donelist` 现在表示累计已完成事项。
- `验证结果`：每条验证检查是否通过。

`trace.jsonl` 是结构化事件流，适合脚本分析和定位细节。排查模型为什么只读文件、不修改文件或没有响应 reflect feedback 时，优先查看：

- `model_raw_response`：模型显式返回的原始 `choices[0].message.content`。
- `model_decision`：解析后的结构化决策，包括 `rationale`、`loop_end`、`planned_actions`、`donelist` 和 `tool_calls`。
- `run_finished`：单任务最终聚合字段，包括 stop reason 和任务级 `token_usage`。

字段定位说明：
- `tool_calls` 是唯一会被 `act` 阶段实际执行的工具调用。
- `planned_actions` 只描述本轮 `tool_calls` 实际会做的事情，不作为跨轮任务队列。
- `donelist` 记录到当前轮为止已经完成的事项；下一轮模型会通过 `runtime_feedback.previous_donelist` 看到上一轮累计 done list。
- `loop_end` 只有在确认后续不再需要任何读取、修改、命令检查、diff 检查或补充验证时才应为 `true`；只要还打算继续做事，就必须保持 `false`。当 `loop_end=true` 时，`tool_calls` 也必须为空。
- `tool_input` 会按 `tool_schema` 校验字段名和类型，类型不匹配会以 `model_error` 收口，不会继续进入工具层 traceback。

这里记录的是模型显式返回内容，不包含 provider 隐藏推理链，也不会记录 API key 或请求头。
token 指标只统计 provider 返回的模型 usage，不统计工具调用或命令开销；若某轮缺少 `usage`，当前会保留真实值并把整次任务标记为 token usage 不完整，不做本地估算。

## 4.1 读取源码时的工具分工

- `read_file`：通用入口。小文件返回全文；大文件返回 `content_mode="structure_summary"`。
- `read_file_structure_summary`：显式只读结构摘要。适合先看 `.py` 文件里的 `class` / `def` 起始行号，或先看 Markdown / 文本文件的标题分节。
- `read_file_range`：在已经拿到行号后，再按闭区间精读关键区域。

当前运行时还会把已读文件缓存进 `runtime_feedback.previous_reflect.file_context_cache`。需要注意：

- `cache_status = fresh`：这份读取结果仍可直接参考。
- `cache_status = stale`：这个文件在编辑后已整文件失效，旧片段只表示“以前读过”，不能继续当成当前可信源码。
- 如果只想在 stale 后重新定位结构，优先再调用一次 `read_file_structure_summary`；确定位置后再用 `read_file_range`。

## 5. 运行 eval batch

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --repo-root . `
  --output-root runs `
  --config-name default
```

eval 产物包含：

- `summary.json`
- `summary.md`
- 每个 task 的独立 run 目录

`summary.json` 中重点字段包括 `outcome_counts`、`failure_taxonomy_counts`、`failure_taxonomy_tag_counts`、`verification_failure_counts`、`reflect_trigger_reason_counts`，以及 `average_total_tokens`、`total_tokens`、`token_usage_complete_count`、`token_usage_incomplete_count`。

## 6. 运行 comparison

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --compare-strategies default,verify_failure_only_reflect `
  --repo-root . `
  --output-root runs
```

comparison 产物包含：

- `summary.json`
- `summary.md`
- 每个策略各自的 eval summary

重点查看 delta：

- `failure_taxonomy_counts_delta`
- `failure_taxonomy_tag_counts_delta`
- `verification_failure_counts_delta`
- `reflect_trigger_reason_counts_delta`
- `average_total_tokens_delta`
- `total_tokens_delta`
- `task_deltas`

## 7. 当前仓库任务与启动命令

当前仓库里已有两类可直接运行的任务文件：

- `eval_tasks/`：内置评测任务集，适合做常规 eval 和 strategy comparison。
- `sandbox_experiments/tasks/`：面向 demo 仓库的任务批次，适合单独压测某一类 bugfix / refactor / feature 任务。

终端说明：

- 如果你当前在 `PowerShell` 里运行，请使用下面的 `powershell` 代码块；PowerShell 的续行符是反引号 `` ` ``，不是 `^`。
- 如果你当前在 `cmd.exe` 里运行，请使用下面的 `cmd` 代码块；`cmd.exe` 的续行符才是 `^`。
- 如果不想区分终端，最稳妥的方式是直接改用单行命令运行。

统一运行模板如下：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file <任务文件路径> `
  --repo-root <对应的 demo 仓库路径> `
  --output-root sandbox_experiments\runs `
  --config-name default
```

对应的 `cmd.exe` 版本如下：

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file <任务文件路径> ^
  --repo-root <对应的 demo 仓库路径> ^
  --output-root sandbox_experiments\runs ^
  --config-name default
```

如果要对同一批任务做策略对比，可在上面命令后追加：

```powershell
  --compare-strategies default,memory_off
```

对应的 `cmd.exe` 追加写法如下：

```cmd
  --compare-strategies default,memory_off
```

当前任务清单与可直接复制的命令如下。

说明：`sandbox_experiments/tasks/` 下的任务文件需要搭配各自的 demo 仓库运行，不能统一写成 `--repo-root .`。

内置评测集：

- `eval_tasks/sample_batch.json`
  混合任务集，包含 `general`、`bug_fix`、`code_understanding`、`test_generation`、`refactor` 五类任务，共 5 题。

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --repo-root . `
  --output-root sandbox_experiments\runs `
  --config-name default
```

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file eval_tasks\sample_batch.json ^
  --repo-root . ^
  --output-root sandbox_experiments\runs ^
  --config-name default
```

Bug Fix 任务：

- `sandbox_experiments/tasks/demo_bugfix_task_board_batch.json`
  Task Board 基础 bugfix 题，1 题。
- `sandbox_experiments/tasks/demo_bugfix_task_board_dual_fix_batch.json`
  Task Board 双问题修复题，1 题。
- `sandbox_experiments/tasks/demo_bugfix_task_board_false_lead_batch.json`
  Task Board 带误导线索的 bugfix 题，1 题。
- `sandbox_experiments/tasks/demo_bugfix_task_board_similar_function_batch.json`
  Task Board 相似函数干扰 bugfix 题，1 题。
- `sandbox_experiments/tasks/demo_bugfix_todo_app_batch.json`
  Todo App bugfix 题，1 题。

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_task_board `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_dual_fix_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_dual_fix `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_false_lead_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_false_lead `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_similar_function_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_similar_function `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_todo_app_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default
```

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_batch.json ^
  --repo-root sandbox_experiments\repos\demo_buggy_task_board ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_dual_fix_batch.json ^
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_dual_fix ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_false_lead_batch.json ^
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_false_lead ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_similar_function_batch.json ^
  --repo-root sandbox_experiments\repos\demo_buggy_task_board_similar_function ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_todo_app_batch.json ^
  --repo-root sandbox_experiments\repos\demo_buggy_todo_app ^
  --output-root sandbox_experiments\runs ^
  --config-name default
```

Refactor 任务：

- `sandbox_experiments/tasks/demo_refactor_task_board_export_batch.json`
  Task Board 共享筛选和排序流水线抽取题，1 题。
- `sandbox_experiments/tasks/demo_refactor_task_board_filters_batch.json`
  Task Board 过滤标记 helper 抽取题，1 题。
- `sandbox_experiments/tasks/demo_refactor_task_board_service_pipeline_batch.json`
  Task Board service 输出构造抽取题，1 题。
- `sandbox_experiments/tasks/demo_refactor_task_board_views_batch.json`
  Task Board 视图准备逻辑抽取题，1 题。
- `sandbox_experiments/tasks/demo_refactor_todo_app_helpers_batch.json`
  Todo App helper 抽取题，1 题。

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_export_batch.json `
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_export `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_filters_batch.json `
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_filters `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_service_pipeline_batch.json `
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_service_pipeline `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_views_batch.json `
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_views `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_refactor_todo_app_helpers_batch.json `
  --repo-root sandbox_experiments\repos\demo_refactor_todo_app_helpers `
  --output-root sandbox_experiments\runs `
  --config-name default
```

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_export_batch.json ^
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_export ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_filters_batch.json ^
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_filters ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_service_pipeline_batch.json ^
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_service_pipeline ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_refactor_task_board_views_batch.json ^
  --repo-root sandbox_experiments\repos\demo_refactor_task_board_views ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_refactor_todo_app_helpers_batch.json ^
  --repo-root sandbox_experiments\repos\demo_refactor_todo_app_helpers ^
  --output-root sandbox_experiments\runs ^
  --config-name default
```

Feature 任务：

- `sandbox_experiments/tasks/demo_todo_app_batch.json`
  Todo App 新增搜索命令题，1 题。
- `sandbox_experiments/tasks/demo_todo_app_complete_task_batch.json`
  Todo App 新增完成任务命令题，1 题。

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_batch.json `
  --repo-root sandbox_experiments\repos\demo_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default

& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_complete_task_batch.json `
  --repo-root sandbox_experiments\repos\demo_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default
```

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_batch.json ^
  --repo-root sandbox_experiments\repos\demo_todo_app ^
  --output-root sandbox_experiments\runs ^
  --config-name default

D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_complete_task_batch.json ^
  --repo-root sandbox_experiments\repos\demo_todo_app ^
  --output-root sandbox_experiments\runs ^
  --config-name default
```

若要单独跑某个任务批次的策略对比，推荐直接在对应命令上追加 `--compare-strategies`。例如：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_batch.json `
  --compare-strategies default,memory_off,verify_failure_only_reflect `
  --repo-root sandbox_experiments\repos\demo_buggy_task_board `
  --output-root sandbox_experiments\runs
```

```cmd
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe -m cli ^
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_task_board_batch.json ^
  --compare-strategies default,memory_off,verify_failure_only_reflect ^
  --repo-root sandbox_experiments\repos\demo_buggy_task_board ^
  --output-root sandbox_experiments\runs
```

## 8. 当前限制

- 不支持 `rule_based` provider。
- CLI 单次运行暂不支持直接传入 `verify_commands` / `verify_rules`。
- 默认 `runtime.max_steps = 2`，暂不开放更高预算。
- `runtime.max_steps` 只由 harness 内部使用；模型请求不会看到当前轮数、剩余轮数或最大轮数。
- 第二轮及后续模型只通过 `runtime_feedback.previous_reflect` 接收上一轮事实压缩，并通过 `previous_donelist` 接收上一轮累计 done list。
- 读取缓存治理当前只做第一版“文件级全失效”：文件一旦被编辑，旧读取缓存整文件失效，不做行号偏移修补。
- 回归测试不依赖真实外网模型，使用 fake model 环境。

# 2026-06-22 使用补充

- 单次 run 现在会额外生成 `live_trace_view.html`、`live_trace_snapshot.json` 和 `live_trace_snapshot.js`。
- `live_trace_view.html` 面向过程观察：右侧看 Harness 发给模型的完整输入，左侧看解析后的 `model_decision`。
- `trace_view.html` 继续保留为原始事件调试视图；需要逐条排查时仍优先看它和 `trace.jsonl`。
- `trace.jsonl` 现已新增 `model_request_prepared`，用于记录每轮真实 `request_payload`。
