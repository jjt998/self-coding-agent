# self-coding-agent

`self-coding-agent` 是一个用于学习和研究 coding agent harness 的本地实验项目。它的重点不是做一个完整 IDE Agent，而是把“模型决策、工具执行、观察、验证、反思、评测、策略对比”这些环节拆成可追踪、可复现、可实验的最小闭环。

当前项目处于 `Phase 9：真实任务最小闭环`。核心目标是逐步把早期 stub loop 替换成可用于真实代码任务的最小求解链路。

## 当前能力

- 单次任务运行：生成 `trace.jsonl`、`report.md`、`config_snapshot.json` 等运行产物。
- OpenAI 兼容模型决策层：配置只支持 `openai_compatible`，默认使用 DeepSeek 的 OpenAI-compatible endpoint 和 `DEEPSEEK_API_KEY`。
- 最小多轮 loop：默认 `runtime.max_steps = 2`，流程为 `ingest -> analyze -> (plan -> act -> observe -> verify/reflect)* -> finalize`。
- 核心工具：`search_text`、`read_file`、`apply_patch`、`run_command`、`git_diff`。
- 真实进展观察：基于 `apply_patch` 成功和 `git_diff` 变更判断是否有进展。
- 任务级验证：支持 `verify_commands` 和结构化 `verify_rules`；未配置任务级验证时会以 `missing_task_verification` 失败，不再回退到演示型检查。
- 结构化失败收口：支持 `setup_failed`、`verification_failed`、`model_error`、`max_steps_reached` 等 stop reason，并提供稳定 failure taxonomy。
- Reflect feedback 重规划约束：下一轮模型计划必须回应上一轮失败证据，不能无解释重复失败工具序列。
- 真实 loop 内核扫尾：当前代码不再保留 Phase 3 固定工具序列辅助函数，测试样例默认产物改为 `run_evidence.md`。
- 模型返回日志：每次 plan 会在 `trace.jsonl` 写入 `model_raw_response`，记录模型显式返回的 JSON content，便于排查工具计划和 rationale。
- eval batch：批量运行任务并生成聚合 `summary.json` / `summary.md`。
- strategy comparison：对同一批任务执行多套配置并输出 delta。
- experiment suite：把多组 comparison 固化成实验清单。

## 运行环境

要求 Python `>=3.11`。本项目无运行时第三方依赖；测试使用 `pytest`。

本仓库当前约定测试使用虚拟环境：

```powershell
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe
```

如需真实模型调用，复制 `.env.example` 为 `.env`，并在 `.env` 中填写 API key：

```powershell
Copy-Item .env.example .env
```

`.env` 示例：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek API key
```

程序启动时会自动加载项目根目录 `.env`；如果同名变量已经存在于系统环境变量中，则优先使用系统环境变量。无 API key 时，真实运行会按预期失败为 `model_error`。测试中通过 fake model 环境避免访问外网。

## 快速开始

最小使用路径建议按这个顺序走：配置模型 -> 单次 run -> 编写 eval task -> 查看 report -> 运行 eval -> 运行 comparison -> 排障。完整手册见 `docs/USAGE_GUIDE.md`，MVP 验收命令见 `docs/MVP_ACCEPTANCE.md`。

安装为本地可编辑包：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m pip install -e .
```

运行单次任务：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --task "整理项目并生成说明" `
  --repo-root . `
  --output-root runs `
  --config-name default
```

运行 eval batch：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --repo-root . `
  --output-root runs `
  --config-name default
```

运行策略对比：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --compare-strategies default,memory_off,verify_failure_only_reflect `
  --repo-root . `
  --output-root runs
```

运行实验套件：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --experiment-suite-file experiment_suites\first_batch.json `
  --repo-root . `
  --output-root runs
```

## 配置

配置文件位于 `configs/`。默认配置示例：

```json
{
  "model": {
    "provider": "openai_compatible",
    "name": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_seconds": 30
  },
  "runtime": {
    "max_steps": 2,
    "trace_level": "standard"
  },
  "context": {
    "strategy": "file_recall_context"
  },
  "reflect": {
    "strategy": "low_progress_plus_verify_reflect"
  },
  "memory": {
    "enabled": true
  }
}
```

现有策略配置包括：

- `default`
- `memory_off`
- `naive_recent_context`
- `verify_failure_only_reflect`
- `high_weak_conflict_penalty`
- `short_memory_summary`

## 模型配置与排障

- `api_key_env` 默认是 `DEEPSEEK_API_KEY`；程序会从 `.env` 或系统环境变量读取该变量，缺少时会失败为 `model_error`，错误 details 会显示变量名但不会记录密钥值。
- `base_url` 必须以 `http://` 或 `https://` 开头，默认是 `https://api.deepseek.com`。
- `timeout_seconds` 默认是 `30`；网络超时、DNS 错误、HTTP 非 2xx 都会在 trace/report 中显示安全摘要。
- 常见 `model_error` 类型包括 `ModelConfigError`、`ModelRequestError`、`ModelResponseError`。
- 测试环境可使用 `SELF_CODING_AGENT_FAKE_MODEL_RESPONSE` 注入假响应，仍需设置测试用 API key 环境变量。
- 排查模型为什么只读文件、不修改文件或没有响应 reflect feedback 时，优先查看 `trace.jsonl` 中的 `model_raw_response` 和 `model_decision`。前者是模型显式返回的原始 JSON content，后者是解析后的结构化决策。
- 更完整的模型配置、eval task、report 和 comparison 使用说明见 `docs/USAGE_GUIDE.md`。

## eval task schema

eval task 文件使用 JSON：

```json
{
  "tasks": [
    {
      "name": "demo_task",
      "task": "完成一个可验证的小任务",
      "task_type": "general",
      "workspace_mode": "per_task_sandbox",
      "sandbox_retention": "delete_on_success",
      "setup_commands": [["python", "-V"]],
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

默认 eval 使用 `per_task_sandbox`，避免污染源仓库。sandbox 保留策略支持：

- `delete_on_success`
- `keep_on_success`
- `always_keep`
- `always_delete`

## verify_rules

当前已支持的结构化验证规则包括：

- 命令输出：`command_stdout_contains`、`command_stdout_not_contains`、`command_stderr_contains`、`command_stderr_not_contains`
- 命令返回码：`command_returncode`
- 文件存在性：`file_exists`、`file_not_exists`
- 文件文本：`file_contains`、`file_not_contains`
- 文件行数：`file_line_count_at_least`、`file_line_count_at_most`
- JSON 文件值：`json_file_value_equals`
- JSON 结构：`json_path_exists`、`json_array_length_equals`、`json_array_length_at_least`、`json_array_length_at_most`、`json_object_key_exists`
- diff：`diff_changed_file_count_at_least`、`diff_changed_file_count_at_most`、`diff_contains_file`
- diff 文本：`diff_contains_text`、`diff_not_contains_text`
- 命令输出 regex：`command_stdout_matches_regex`、`command_stderr_matches_regex`
- 多文件聚合：`files_matching_count_at_least`、`files_matching_count_at_most`

说明：

- `json_file_value_equals` 的 `json_path` 使用简单点号路径，例如 `a.b.0.name`。
- JSON 结构规则复用同一套简单点号路径，不支持完整 JSONPath。
- diff 规则只消费当前 run 已有的 `git_diff` 工具结果，不会在 verify 阶段隐式重新生成 diff。
- diff 文本规则匹配 `git_diff.tool_output.diffs[].diff` 中已有的统一 diff 文本。
- regex 规则使用 Python 标准库 `re.search` 默认行为，不额外支持 flags。
- 多文件聚合只统计 repo root 内可按 UTF-8 读取的文本文件。

## 运行产物

每次 run 会生成一个独立目录，主要包含：

- `config_snapshot.json`：运行设置和配置快照。
- `trace.jsonl`：结构化事件流，包括状态迁移、模型原始返回、模型决策、工具调用、验证结果、stop reason。
- `report.md`：面向人阅读的运行报告。

eval 和 comparison 会额外生成：

- `summary.json`
- `summary.md`
- strategy comparison delta
- task-level delta
- failure taxonomy 聚合
- failure taxonomy tags 聚合

当前稳定 taxonomy 口径包括：

- `setup:command_returncode`
- `model:<error_type>`
- `verification:verify_command_returncode`
- `verification:verify_rule:<check>`
- `verification:missing_task_verification`
- `runtime:max_steps_reached`

## 测试

MVP 冻结验收命令见 `docs/MVP_ACCEPTANCE.md`。

运行核心回归：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m pytest -q
```

按模块运行：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m pytest tests\test_loop.py tests\test_cli.py -q
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m pytest tests\test_eval.py tests\test_verify.py tests\test_model.py -q
```

## 当前限制

- loop 已拆分为独立状态处理方法，并已清理旧 Phase 3 固定工具序列语义；后续仍需继续增强真实任务求解策略。
- reflect feedback 已作为下一轮 plan 的硬约束；后续仍可继续增强反思策略质量。
- 默认最大求解轮数仍固定为 `2`，暂不开放更高预算。
- CLI 暂不支持单次运行直接传入 `verify_commands` / `verify_rules`，该能力目前只在 eval task schema 中使用。

## 开发入口

继续开发时优先阅读：

- `docs/SESSION_ENTRY.md`
- `docs/CURRENT_STATUS.md`
- `docs/PHASE_PROGRESS.md`
- `docs/DEVELOPMENT_PLAYBOOK.md`

按项目流程，更新当前状态文档前需要先把旧版本归档到 `dev_process_history/`。
