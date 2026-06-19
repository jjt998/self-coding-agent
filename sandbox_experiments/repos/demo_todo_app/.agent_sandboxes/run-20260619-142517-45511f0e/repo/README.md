# demo_todo_app

这是一个用于真实任务实验的小型 Python TODO CLI。它故意保持简单，方便 agent 在真实文件上执行读取、修改、运行命令和生成 diff。

## 当前命令

列出任务：

```powershell
python todo_app.py list
```

新增任务：

```powershell
python todo_app.py add "Write changelog" --description "Summarize release notes"
```

## 实验目标示例

可以要求 agent 增加 `search <keyword>` 子命令，并用下面命令验证：

```powershell
python todo_app.py search docs
```

预期实现后会输出包含 `docs` 关键字的任务，例如 `Write project notes`。
