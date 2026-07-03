# Team Knowledge Base CLI

This demo repository is a small Python CLI for browsing team knowledge base articles.
It is intentionally incomplete so feature tasks can exercise multi-file changes.

## Current Commands

- `python team_kb.py list`
- `python team_kb.py list --owner alice`
- `python team_kb.py list --status published`
- `python team_kb.py show 1`

## Data

Articles live in `data/articles.json`.
Each article has an `id`, `title`, `owner`, `status`, `tags`, `summary`, and `body`.
