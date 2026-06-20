# Task Board CLI

This demo repository is intentionally a bit larger than the todo app demos.
It is used to test multi-file bug fixing in a small but realistic Python CLI.

## Commands

- `python task_board.py list`
- `python task_board.py list --owner alice`
- `python task_board.py list --status todo`
- `python task_board.py list --owner alice --status todo`
- `python task_board.py list --owner alice --status todo --include-archived`

## Expected behavior

- By default, archived tasks are excluded from `list`.
- `--include-archived` should include archived tasks in the result.
- When `--owner` and `--status` are both provided, the result should satisfy both filters.
- `status=todo` means `done=false`.
- `status=done` means `done=true`.
