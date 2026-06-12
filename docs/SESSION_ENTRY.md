# Session Entry

## Purpose

This document is the lightweight entrypoint for a new AI session.

Do not start by loading every project document. Start here, then read only the minimum required files for the current phase.

## Current Default Workflow

1. Read:
   - `docs/CURRENT_STATUS.md`
   - `docs/PHASE_PROGRESS.md`
   - `docs/DEVELOPMENT_PLAYBOOK.md`
2. Inspect the repository structure.
3. Identify the current active phase.
4. Continue from the next unfinished implementation step.
5. Read other documents only if the current phase needs them.

## Current Phase

- `Phase 1: Scaffold and Control Plane`

## Do Next

Build the Python project scaffold and control-plane skeleton.

The immediate implementation target is:

- `pyproject.toml`
- `src/self_coding_agent/`
- `tests/`
- `configs/`
- `eval_tasks/`
- `runs/`

Then implement:

- base config models
- trace event models
- trace writer
- CLI entrypoint

## Read These First

Always read these first:

- `docs/CURRENT_STATUS.md`
- `docs/PHASE_PROGRESS.md`
- `docs/DEVELOPMENT_PLAYBOOK.md`

## Read These Only If Needed

Read these on demand:

- `docs/ARCHITECTURE.md`
  - when implementing package layout, module boundaries, trace, context, memory, or eval structure
- `docs/DECISIONS.md`
  - when a design choice seems unclear or you are tempted to reopen an old decision
- `docs/PRD.md`
  - when scope, task types, or MVP boundaries need clarification
- `docs/MONTH_PLAN.md`
  - when you need the month-level milestone framing

## Do Not Load By Default

Do not load all documents at the start of a session unless the user explicitly asks for a full documentation review.

## After Finishing Work

Update:

- `docs/CURRENT_STATUS.md`
- `docs/PHASE_PROGRESS.md`

If a key design decision changed, also update:

- `docs/DECISIONS.md`

If execution order changed, also update:

- `docs/DEVELOPMENT_PLAYBOOK.md`

## Session Resume Prompt

Use this prompt in a new session:

```text
Continue development of this project. Start by reading only docs/SESSION_ENTRY.md, docs/CURRENT_STATUS.md, docs/PHASE_PROGRESS.md, and docs/DEVELOPMENT_PLAYBOOK.md. Do not preload all project documents. Inspect the repository, identify the current phase, and continue from the next unfinished implementation step. Read ARCHITECTURE, DECISIONS, PRD, or MONTH_PLAN only if the current phase needs them. After finishing work, update CURRENT_STATUS and PHASE_PROGRESS.
```
