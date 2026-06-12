# Development Playbook

## 1. Purpose

This document is the execution guide for building the first MVP of the self-coding-agent project.

It is designed to support:

- Iterative development.
- Session recovery after context compression.
- Handoff to a new AI session.
- Clear implementation order.
- Stable evaluation of progress.

If a future session needs to resume work, this file should be treated as the primary execution reference, together with:

- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/MONTH_PLAN.md`

## 2. Project Intent

The project is not a one-off coding agent demo.

The project is a research-oriented local coding agent harness whose core value is:

- comparability,
- observability,
- replayability,
- diagnosability,
- strategy iteration.

The first MVP should prioritize harness quality over raw bug-fixing strength.

## 3. Non-Negotiable MVP Decisions

These decisions are already made and should not be re-opened during early implementation unless a strong reason appears.

### 3.1 Loop Baseline

Use an explicit state-machine loop:

- `ingest`
- `analyze`
- `plan`
- `act`
- `observe`
- `reflect`
- `verify`
- `finalize`

Rules:

- The first `act` must come after `plan`.
- `reflect` is conditional, not per-step.
- `verify` is required before `finalize`.
- Failures are represented by structured status and stop reason, not a dedicated `fail` state.

### 3.2 Context Baseline

Use four context layers:

- `task_context`
- `repo_context`
- `runtime_context`
- `memory_context`

Use file-level recall first. Do not build a heavy symbol system in MVP.

### 3.3 Memory Baseline

Use:

- runtime memory
- structured long-term memory

Do not use vector memory or embedding retrieval in MVP.

Write long-term memory only after success plus verification pass.

### 3.4 Eval Baseline

Eval starts in the first implementation stage.

Target task types:

- `code_understanding`
- `bug_fix`
- `test_generation`
- `refactor`

### 3.5 Memory Pollution Scope

MVP must include:

- `memory_pollution` diagnosis label
- `memory_conflict` evidence recording
- schema fields that allow future anti-pollution strategies

MVP does not include a dedicated memory-pollution experiment track.

## 4. Execution Order

Do not implement in feature popularity order. Implement in control-surface order.

Recommended order:

1. Project scaffold.
2. Runtime models and config models.
3. Trace writer and run directory structure.
4. CLI entrypoint.
5. Tool registry and five core tools.
6. Baseline state-machine loop.
7. Verification flow.
8. Context builder and file recall.
9. Runtime memory.
10. Long-term memory store and retrieval.
11. Eval task schema and batch runner.
12. Markdown reports.
13. Strategy toggles and comparison runs.

## 5. Phase Breakdown

### Phase 1: Scaffold and Control Plane

Goal:

- Make the repository runnable and structurally stable.

Deliver:

- `pyproject.toml`
- package layout under `src/self_coding_agent/`
- `tests/`
- `configs/`
- `eval_tasks/`
- `runs/`
- base settings model
- trace event model
- trace writer
- CLI skeleton

Definition of done:

- A command can start a run and emit a run directory with config snapshot and empty trace/report stubs.

### Phase 2: Minimal Agent Loop

Goal:

- Run a task through the fixed state-machine skeleton.

Deliver:

- state enum
- runtime state object
- stop reason model
- loop orchestrator
- no-progress tracking
- reflect trigger placeholders

Definition of done:

- A single run can move through the loop and produce state transition events even if model behavior is still stubbed.

### Phase 3: Core Tools

Goal:

- Support the minimum repo operations required for coding tasks.

Deliver:

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

Definition of done:

- Every tool has structured input and output and is recorded in trace.

### Phase 4: Verification and Reports

Goal:

- Make success and failure auditable.

Deliver:

- verification result schema
- verify execution
- Markdown single-run report
- structured stop reasons

Definition of done:

- A run can end with a report showing status, tools used, and verification result.

### Phase 5: Context and Recall

Goal:

- Make agent input controlled rather than ad hoc.

Deliver:

- task/repo/runtime/memory context models
- file-level recall
- raw/summary/index-only selection logic
- context trimming policy

Definition of done:

- Context snapshots are visible in trace, and candidate file recall is inspectable.

### Phase 6: Memory

Goal:

- Add reuse without overcomplicating retrieval.

Deliver:

- runtime memory manager
- long-term memory store
- structured memory entries
- filtering by tags, task type, file path, keywords
- conflict evidence tracking

Definition of done:

- Successful verified runs can write memory entries, and later runs can retrieve them.

### Phase 7: Eval

Goal:

- Compare runs instead of inspecting isolated behavior.

Deliver:

- task spec schema
- eval runner
- result metrics
- process metrics
- diagnostic labels
- batch summary report

Definition of done:

- A fixed task set can run in batch and produce summary metrics.

### Phase 8: Strategy Comparison

Goal:

- Use the harness for actual experimentation.

Deliver:

- baseline strategy config
- context strategy variants
- memory on/off switch
- reflect trigger variants
- comparison summary

Definition of done:

- At least two strategies can be compared on the same task set with recorded deltas.

## 6. Engineering Rules During Implementation

### 6.1 Prefer Stable Models

Use structured Python models for:

- config
- runtime state
- trace events
- tool outputs
- eval specs
- reports where practical

### 6.2 Keep Interfaces Small

Do not over-abstract early.

Interfaces that must exist early:

- model adapter base
- tool registry base
- trace writer
- memory manager interface
- context builder interface

### 6.3 Avoid Premature Intelligence

Do not spend early time on:

- advanced prompt tuning
- heavy planning frameworks
- embedding retrieval
- rich UI
- autonomous multi-agent execution

### 6.4 Every Important Action Must Leave Evidence

At minimum, trace must record:

- config snapshot
- state transitions
- context build result
- model request/response summary
- tool calls/results
- reflect result
- verify result
- stop reason

## 7. Suggested Repository Milestones

### Milestone A

Repo can run:

- `python -m self_coding_agent.cli ...`

and creates:

- run directory
- config snapshot
- JSONL trace
- Markdown report

### Milestone B

Repo can perform:

- search
- file read
- patch
- command execution
- diff collection

inside one controlled run.

### Milestone C

Repo can execute:

- one simple `code_understanding` task
- one simple `bug_fix` task

with trace and report.

### Milestone D

Repo can batch-run a small eval set and report:

- success rate
- average steps
- average tool calls
- failure distribution

## 8. First Experiments To Run

After MVP infrastructure exists, compare:

### Experiment 1

`naive_recent_context` vs `file_recall_context`

Question:

- Does file recall reduce `context_miss`?

### Experiment 2

`memory_off` vs `structured_memory_on`

Question:

- Does memory reduce repeated exploration?

### Experiment 3

`verify_failure_only_reflect` vs `low_progress_plus_verify_reflect`

Question:

- Does conditional reflect reduce repeated no-progress loops?

## 9. What A New Session Should Do First

If a new AI session resumes this project, it should:

1. Read:
   - `docs/DEVELOPMENT_PLAYBOOK.md`
   - `docs/PRD.md`
   - `docs/ARCHITECTURE.md`
   - `docs/MONTH_PLAN.md`
2. Inspect current repository structure.
3. Identify the latest completed phase from this playbook.
4. Continue from the next unfinished phase.
5. Avoid reopening settled design decisions unless blocked by implementation reality.

## 10. Handoff Prompt For A New Session

Use the following prompt to resume in a new session:

```text
Read docs/DEVELOPMENT_PLAYBOOK.md first, then docs/PRD.md, docs/ARCHITECTURE.md, and docs/MONTH_PLAN.md. Treat those files as the current source of truth. Inspect the repository, identify the latest completed phase from the playbook, and continue implementation from the next unfinished phase without re-opening already-settled MVP decisions unless implementation reality forces a change. Preserve the project as a research-oriented coding agent harness focused on loop, context, memory, tool use, trace, replay, and eval.
```

## 11. Current Recommended Next Step

The next implementation step after this document is:

- scaffold the Python project
- add package layout
- add config models
- add trace event models and writer
- add CLI entrypoint

Do not jump ahead to advanced agent logic before that control plane exists.
