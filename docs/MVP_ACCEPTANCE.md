# MVP 验收

本文档固定第一版 MVP 的验收命令、预期产物、当前边界和下一阶段 backlog。

## 1. 验收环境

统一使用当前虚拟环境：

```powershell
D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe
```

真实模型运行需要复制 `.env.example` 为 `.env`，并在 `.env` 中填写：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek API key
```

自动化回归测试使用 fake model 环境，不访问外网。

## 2. 全量测试验收

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m pytest -q
```

验收标准：

- 命令返回码为 `0`。
- 全量测试全部通过。
- 不产生需要提交的 `__pycache__` 文件。

## 3. Sample Eval Smoke

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --repo-root . `
  --output-root runs `
  --config-name default
```

验收标准：

- 生成 `runs\eval-sample_batch\summary.json`。
- 生成 `runs\eval-sample_batch\summary.md`。
- `summary.json` 包含 `failure_taxonomy_counts`、`failure_taxonomy_tag_counts`、`reflect_trigger_reason_counts`。
- 每个 task 都有独立 run 目录，并包含 `trace.jsonl`、`report.md`、`config_snapshot.json`。

## 4. Sample Comparison Smoke

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file eval_tasks\sample_batch.json `
  --compare-strategies default,verify_failure_only_reflect `
  --repo-root . `
  --output-root runs
```

验收标准：

- 生成 `runs\comparison-sample_batch\summary.json`。
- 生成 `runs\comparison-sample_batch\summary.md`。
- `summary.json` 包含 `deltas` 和 `task_deltas`。
- delta 中包含 `failure_taxonomy_counts_delta`、`failure_taxonomy_tag_counts_delta`、`verification_failure_counts_delta`、`reflect_trigger_reason_counts_delta`。

## 5. MVP 当前边界

- 只支持 `openai_compatible` 模型 provider。
- 不支持 `rule_based`。
- 无 API key 会失败为 `model_error`。
- CLI 单次运行暂不支持直接传入 `verify_commands` / `verify_rules`。
- 默认 `runtime.max_steps = 2`。
- verify 阶段只消费已配置的 `verify_commands` / `verify_rules`。
- 回归测试不依赖真实 API。

## 6. 下一阶段 Backlog

- 评估是否开放 `runtime.max_steps > 2`，并补预算控制和防重复策略。
- 根据真实任务继续扩展更少量、更必要的 `verify_rules`。
- 增强模型重规划质量评估，而不是只校验是否响应 reflect feedback。
- 增加更真实的 eval task，覆盖小型 bug fix、重构和测试补全任务。
- 梳理长期 memory 的真实收益评估任务。
