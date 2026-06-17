# sandbox_experiments

这个目录用于放真实任务实验资源，避免实验任务、临时目标仓库和运行输出污染正式的 `eval_tasks/`、`runs/`、`tests/`。

## 目录结构

- `tasks/`：实验用 eval task JSON。
- `repos/demo_todo_app/`：可被 agent 修改的 demo 项目仓库。
- `runs/`：实验运行输出，默认不纳入 git。
- `notes/`：实验记录。

## Demo 项目

`repos/demo_todo_app/` 是一个小型 Python TODO CLI。当前内置 `list` 和 `add` 子命令，实验任务会要求 agent 增加真实可验证的功能，例如 `search` 子命令。

`repos/demo_buggy_todo_app/` 是一个用于 bug 修复实验的 TODO CLI。它故意把 `list` 命令里的任务完成状态显示反了，适合用来跑一次最小真实 bugfix。

轻量检查命令：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' sandbox_experiments\repos\demo_todo_app\todo_app.py list
```

## 运行实验 eval

真实模型运行需要先在项目根目录复制 `.env.example` 为 `.env`，并填写 API key：

```powershell
Copy-Item .env.example .env
```

`.env` 中至少需要：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek API key
```

如需确保走真实模型，不要在 `.env` 或系统环境变量中设置 `SELF_CODING_AGENT_FAKE_MODEL_RESPONSE`。

推荐把 `--repo-root` 指向 demo 项目，把输出写到本目录的 `runs/`：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_todo_app_batch.json `
  --repo-root sandbox_experiments\repos\demo_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default
```

运行简单 bug 修复实验：

```powershell
& 'D:\jt\ANACONDA\envs_dirs\learn-claude-code\python.exe' -m cli `
  --eval-task-file sandbox_experiments\tasks\demo_bugfix_todo_app_batch.json `
  --repo-root sandbox_experiments\repos\demo_buggy_todo_app `
  --output-root sandbox_experiments\runs `
  --config-name default
```

## 注意事项

- `runs/` 默认忽略，不提交实验输出。
- `repos/tmp_*/` 默认忽略，可用于临时复制或破坏性试验。
- `repos/demo_todo_app/` 会作为可复用 demo fixture 保留在主仓库中。
- CLI 单次运行暂不支持直接传 `verify_commands` / `verify_rules`；需要显式验证时请使用 eval task JSON。
