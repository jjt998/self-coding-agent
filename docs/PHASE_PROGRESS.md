# Phase Progress

## Overview

- Last updated: 2026-06-11
- Current active phase: `Phase 1: Scaffold and Control Plane`

## Phase 1: Scaffold and Control Plane

- Status: `not_started`
- Goal: make the repository runnable and structurally stable.
- Completed:
  - Planning documents completed.
- Remaining:
  - Create Python project scaffold.
  - Add config models.
  - Add trace event model.
  - Add trace writer.
  - Add CLI skeleton.
- Acceptance:
  - A command can start a run and create a run directory with config snapshot and trace/report placeholders.
- Notes:
  - This is the next implementation target.

## Phase 2: Minimal Agent Loop

- Status: `not_started`
- Goal: run a task through the baseline state-machine loop.
- Completed:
  - Loop design has been specified in docs.
- Remaining:
  - Implement state enum.
  - Implement runtime state.
  - Implement stop reasons.
  - Implement loop orchestrator.
  - Implement initial transition flow.
- Acceptance:
  - A run can move through loop states and emit state transition events.
- Notes:
  - Depends on Phase 1 scaffold.

## Phase 3: Core Tools

- Status: `not_started`
- Goal: support core repo operations for local coding tasks.
- Completed:
  - Core tool list has been fixed.
- Remaining:
  - Implement `search_text`.
  - Implement `read_file`.
  - Implement `apply_patch`.
  - Implement `run_command`.
  - Implement `git_diff`.
  - Trace all tool interactions.
- Acceptance:
  - All five tools have structured input/output and can be used inside one run.
- Notes:
  - Depends on Phase 1 models and trace.

## Phase 4: Verification and Reports

- Status: `not_started`
- Goal: make success and failure auditable.
- Completed:
  - Verification requirements are defined in docs.
- Remaining:
  - Implement verification result schema.
  - Implement verify execution path.
  - Implement Markdown single-run report.
  - Implement structured stop reasons in reports.
- Acceptance:
  - A finished run produces a status, verification result, and readable report.
- Notes:
  - Verification rules should stay conservative.

## Phase 5: Context and Recall

- Status: `not_started`
- Goal: make model input controlled and inspectable.
- Completed:
  - Context-layer design is documented.
- Remaining:
  - Implement context models.
  - Implement file-level recall.
  - Implement raw/summary/index-only injection rules.
  - Implement trimming policy.
- Acceptance:
  - Context snapshots and file recall decisions are visible in trace.
- Notes:
  - First version should stay file-centric.

## Phase 6: Memory

- Status: `not_started`
- Goal: add reuse with basic pollution awareness.
- Completed:
  - Memory scope and retrieval baseline are defined.
- Remaining:
  - Implement runtime memory manager.
  - Implement long-term memory store.
  - Implement structured memory entries.
  - Implement tag/path/keyword retrieval.
  - Implement memory conflict evidence.
- Acceptance:
  - Successful verified runs can write memory and later runs can retrieve it.
- Notes:
  - No embedding retrieval in MVP.

## Phase 7: Eval

- Status: `not_started`
- Goal: support repeatable evaluation and comparison.
- Completed:
  - Eval structure and metrics have been defined.
- Remaining:
  - Implement task spec schema.
  - Implement eval runner.
  - Implement metrics collection.
  - Implement diagnostics pass.
  - Implement batch summary report.
- Acceptance:
  - A fixed task set can run in batch and emit aggregate metrics.
- Notes:
  - Result, process, and diagnostic metrics are all required.

## Phase 8: Strategy Comparison

- Status: `not_started`
- Goal: run meaningful strategy experiments.
- Completed:
  - First experiment directions are defined.
- Remaining:
  - Add strategy configs.
  - Add context strategy variants.
  - Add memory on/off switch.
  - Add reflect trigger variants.
  - Add comparison summary.
- Acceptance:
  - At least two strategies can be compared on the same task set with deltas.
- Notes:
  - First experiments should stay narrow and controlled.
