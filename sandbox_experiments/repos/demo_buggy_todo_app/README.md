# demo_buggy_todo_app

这是一个用于真实 bug 修复实验的小型 Python TODO CLI。仓库里故意保留一个简单 bug：`list` 命令会把未完成任务显示成 `done`。

## 复现 bug

```powershell
python todo_app.py list
```

当前错误表现：`Write project notes` 会显示为 `[done]`。

期望表现：`done=false` 的任务应显示为 `[todo]`。

## 验证修复

```powershell
python todo_app.py list
```

输出应包含：

```text
1. [todo] Write project notes
```

并且不应包含：

```text
1. [done] Write project notes
```
