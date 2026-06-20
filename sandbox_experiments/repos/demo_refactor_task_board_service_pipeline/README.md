# Task Board CLI

This demo repository is intentionally a bit larger than the todo app demos.
It is used to test multi-file bug fixing in a small but realistic Python CLI.

## Commands

- `python task_board.py list`
- `python task_board.py list --owner alice`
- `python task_board.py list --status todo`
- `python task_board.py list --owner alice --status todo`
- `python task_board.py list --owner alice --status todo --include-archived`
- `python task_board.py export --owner alice --status todo`
- `python task_board.py owners --owner alice --status todo`
- `python task_board.py priorities --owner alice --status todo --include-archived`
