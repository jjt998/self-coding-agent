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
- `进展观察`：是否观察到文件变更、变更文件数、失败工具数。
- `反思反馈`：最近一次 reflect trigger、失败检查、建议关注点。
- `模型返回摘要`：最近一次模型显式返回的 summary、rationale、planned_actions 和 tool_calls。
- `验证结果`：每条验证检查是否通过。

`trace.jsonl` 是结构化事件流，适合脚本分析和定位细节。排查模型为什么只读文件、不修改文件或没有响应 reflect feedback 时，优先查看：

- `model_raw_response`：模型显式返回的原始 `choices[0].message.content`。
- `model_decision`：解析后的结构化决策，包括 `rationale`、`planned_actions` 和 `tool_calls`。

这里记录的是模型显式返回内容，不包含 provider 隐藏推理链，也不会记录 API key 或请求头。

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

`summary.json` 中重点字段包括 `outcome_counts`、`failure_taxonomy_counts`、`failure_taxonomy_tag_counts`、`verification_failure_counts`、`reflect_trigger_reason_counts`。

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
- `task_deltas`

## 7. 当前限制

- 不支持 `rule_based` provider。
- CLI 单次运行暂不支持直接传入 `verify_commands` / `verify_rules`。
- 默认 `runtime.max_steps = 2`，暂不开放更高预算。
- 回归测试不依赖真实外网模型，使用 fake model 环境。
