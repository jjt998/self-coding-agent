# Decisions

## Purpose

This document records key project decisions that have already been made for the MVP.

Future implementation sessions should treat these as settled unless implementation reality forces a change.

## D-001: Build A Research-Oriented Harness First

Decision:

- Prioritize a research-oriented coding agent harness over a polished end-user product.

Reason:

- The project goal is to study loop, context, memory, tool use, trace, replay, and eval.
- A usable agent matters, but comparability and iteration matter more in the first month.

Impact:

- Infrastructure quality takes priority over raw task success rate.

## D-002: Local Repository CLI First

Decision:

- Support local repository CLI workflows first.

Reason:

- It keeps the scope controlled.
- It is enough to study the harness.
- It avoids early complexity from remote sandboxes, IDE integrations, or browsers.

Impact:

- MVP excludes cloud execution, browser automation, and IDE plugin workflows.

## D-003: Use An Explicit State-Machine Loop

Decision:

- Use an explicit state-machine loop with:
  - `ingest`
  - `analyze`
  - `plan`
  - `act`
  - `observe`
  - `reflect`
  - `verify`
  - `finalize`

Reason:

- It is easier to trace, replay, constrain, and compare than a fully free-form loop.
- It makes evaluation and diagnostics clearer.

Impact:

- The loop itself is initially treated as a stable baseline, not the first major experimental variable.

## D-004: Reflect Is Conditional

Decision:

- `reflect` is not executed on every step.
- It is triggered by low progress, verification failure, conflicting evidence, or budget pressure.

Reason:

- Per-step reflection is expensive and often low-value.
- Conditional reflection better matches the project goal of studying useful control points.

Impact:

- Reflection becomes an explicit experimental lever later.

## D-005: Require Verification Before Finalize

Decision:

- `finalize` requires at least one verification attempt.

Reason:

- Model self-judgment is not enough for reliable success claims.
- Verification is needed for fair evaluation and trustworthy reporting.

Impact:

- Success is a system judgment, not just a model claim.

## D-006: Start With File-Level Recall

Decision:

- Use file-level recall plus lightweight keyword and symbol-oriented search.

Reason:

- It is simpler, fast to implement, and good enough for the MVP.
- A heavy AST/LSP-based symbol graph would consume too much schedule and distract from harness work.

Impact:

- Context quality is improved through controlled recall, not through a full code intelligence platform.

## D-007: Use Four Context Layers

Decision:

- Separate context into:
  - `task_context`
  - `repo_context`
  - `runtime_context`
  - `memory_context`

Reason:

- These layers have different lifecycles and different experimental roles.
- Mixing them makes diagnosis and replacement harder.

Impact:

- Context building is treated as a first-class system module.

## D-008: Use Structured Long-Term Memory Without Embeddings In MVP

Decision:

- Long-term memory uses structured entries, tag filtering, path filtering, task-type filtering, and keyword search.
- Do not use vector retrieval or embeddings in the MVP.

Reason:

- First-month memory volume will be small.
- Structured retrieval is easier to debug and compare.
- Embedding retrieval adds complexity before it is justified.

Impact:

- Memory architecture should leave room for a future retrieval backend, but not depend on one now.

## D-009: Write Long-Term Memory Conservatively

Decision:

- Write long-term memory only after task success and verification pass.

Reason:

- Wrong memory is more harmful than missing memory.
- Early memory systems are especially vulnerable to contamination.

Impact:

- Runtime memory can be broad.
- Long-term memory must be conservative.

## D-010: Detect Memory Pollution, But Do Not Make It A Core MVP Experiment

Decision:

- Include `memory_pollution` diagnosis and `memory_conflict` evidence.
- Do not run dedicated memory-pollution experiments in the MVP.

Reason:

- Pollution awareness is important.
- A full experiment track would require more memory volume and more task history than the MVP will have.

Impact:

- The schema must support future anti-pollution strategies.
- The first version only needs observability and basic safeguards.

## D-011: Eval Starts Early

Decision:

- Eval is part of the first implementation stage.

Reason:

- The project is about iteration and comparison.
- Without early eval, later improvements will be hard to attribute.

Impact:

- Even weak early agent runs should emit metrics and reports.

## D-012: Focus On Four Task Types

Decision:

- Support:
  - `code_understanding`
  - `bug_fix`
  - `test_generation`
  - `refactor`

Reason:

- These task types cover the main learning targets while keeping the task set manageable.

Impact:

- Eval and diagnostics should keep task-type distinctions explicit.

## D-013: First-Core Experiments

Decision:

- First strategy comparisons should focus on:
  - context strategy
  - memory on/off
  - reflect trigger strategy

Reason:

- These are the strongest fit for the stated research goal.

Impact:

- The initial code architecture must expose these as configurable strategies.
