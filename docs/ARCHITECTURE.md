# Self Coding Agent Architecture

## 1. Purpose

This document defines the technical architecture for the one-month MVP of the self-coding-agent project.

The target is not a general autonomous agent platform. The target is a local-repo coding agent harness that is structured enough to support:

- repeatable execution
- traceability
- evaluation
- strategy comparison
- future iteration on context, memory, and loop behavior

## 2. Architecture Principles

- Keep the first implementation small enough to finish in one month.
- Keep component boundaries explicit so strategy changes can be isolated.
- Prefer structured state and events over free-form logs.
- Treat trace, replay, and eval as first-class architecture concerns.
- Keep tool execution controlled, bounded, and auditable.
- Design for pluggability without overbuilding provider abstractions in week 1.

## 3. System View

```text
CLI
  -> Config Loader
  -> Orchestrator
    -> Agent Loop
      -> Context Builder
      -> Memory Manager
      -> Model Adapter
      -> Tool Registry
      -> Verifier
      -> Trace Writer
      -> Reporter

Eval Runner
  -> Task Spec Loader
  -> Orchestrator
  -> Metrics Aggregator
  -> Diagnostics Pass
  -> Batch Reporter
```

The core runtime path is:

1. Load task and strategy configuration.
2. Build initial runtime state.
3. Enter explicit loop states.
4. Build context for the current state.
5. Ask the model for the next structured decision.
6. Execute tool calls or apply transitions.
7. Update runtime memory and trace.
8. Verify when appropriate.
9. Finalize the run and emit reports.

## 4. Module Responsibilities

### 4.1 CLI

Responsibilities:

- Accept repo path, task input, config path, and budget overrides.
- Start a single run or a batch eval run.
- Select strategy profile.
- Select model provider.

Non-goals:

- Rich interactive UI.
- Multi-session state management.

### 4.2 Orchestrator

Responsibilities:

- Own the lifecycle of a run.
- Create the initial runtime state.
- Drive state transitions through the loop.
- Enforce budgets and stop conditions.
- Coordinate trace, reports, and memory persistence.

The orchestrator is the top-level application service. It should not contain provider-specific model logic or tool implementation details.

### 4.3 Agent Loop

Responsibilities:

- Define states.
- Define allowed transitions.
- Define when to call the model.
- Define when to run tools.
- Define when to verify and reflect.

The loop is a fixed baseline in MVP. It is intentionally not the first experimental variable.

### 4.4 Context Builder

Responsibilities:

- Assemble prompt input from task, repo, runtime, and memory layers.
- Apply recall, summarization, and trimming policy.
- Produce a context bundle and metadata about how that context was built.

### 4.5 Memory Manager

Responsibilities:

- Maintain runtime memory for the current run.
- Read and write long-term memory entries.
- Apply retrieval filtering rules.
- Record memory conflicts and usage metadata.

### 4.6 Model Adapter

Responsibilities:

- Convert harness-native requests into provider-native requests.
- Normalize provider responses into a common result shape.
- Expose capability metadata.

### 4.7 Tool Registry

Responsibilities:

- Register tool schemas and handlers.
- Validate tool arguments.
- Execute tools inside workspace constraints.
- Normalize tool results.

### 4.8 Verifier

Responsibilities:

- Run validation commands or checks.
- Normalize verification results.
- Signal pass, fail, or blocked outcomes.

### 4.9 Trace Writer

Responsibilities:

- Persist structured JSONL events.
- Assign event IDs and timestamps.
- Write artifact references for large outputs.

### 4.10 Reporter

Responsibilities:

- Generate single-run Markdown reports.
- Generate batch eval Markdown summaries.
- Present diagnostics, metrics, and strategy deltas.

## 5. Suggested Directory Layout

```text
self-coding-agent/
  pyproject.toml
  README.md
  configs/
    default.yaml
    strategies/
      baseline.yaml
  docs/
    PRD.md
    PRD.zh-CN.md
    ARCHITECTURE.md
    ARCHITECTURE.zh-CN.md
    MONTH_PLAN.md
    MONTH_PLAN.zh-CN.md
  src/
    self_coding_agent/
      cli/
        main.py
      core/
        loop.py
        state.py
        runtime.py
        stop.py
        orchestrator.py
      models/
        base.py
        openai_adapter.py
      tools/
        base.py
        registry.py
        filesystem.py
        command.py
        git.py
      context/
        builder.py
        recall.py
        compression.py
        layers.py
      memory/
        runtime_memory.py
        long_term_memory.py
        store.py
        retrieval.py
      trace/
        events.py
        writer.py
        replay.py
      eval/
        task_spec.py
        runner.py
        metrics.py
        diagnostics.py
      reports/
        markdown.py
      schemas/
        common.py
  eval_tasks/
  runs/
  tests/
```

## 6. Core Data Model

The MVP should use typed, structured models for all cross-module boundaries.

Suggested primary models:

### 6.1 RunConfig

```yaml
run_config:
  repo_path:
  model_provider:
  model_name:
  strategy_name:
  max_steps:
  max_tool_calls:
  verify_enabled:
  trace_enabled:
```

### 6.2 TaskSpec

```yaml
task_spec:
  id:
  task_type:
  instruction:
  success_criteria:
  constraints:
  prohibitions:
  validation:
  expected_touched_files:
  forbidden_touched_files:
  allowed_tools:
  tags:
```

### 6.3 RuntimeState

```yaml
runtime_state:
  run_id:
  task_id:
  current_state:
  step_count:
  tool_call_count:
  status:
  stop_reason:
  current_plan:
  candidate_files:
  active_files:
  modified_files:
  last_verify_result:
```

### 6.4 PlanStep

```yaml
plan_step:
  step_id:
  description:
  status: pending | in_progress | completed | dropped
  rationale:
```

### 6.5 ModelDecision

```yaml
model_decision:
  decision_type: tool_call | update_plan | verify | reflect | finalize
  reasoning_summary:
  tool_name:
  tool_args:
  plan_update:
  finalize_message:
```

### 6.6 ToolResult

```yaml
tool_result:
  tool_name:
  status: success | error | blocked
  output:
  error:
  metadata:
  duration_ms:
```

### 6.7 VerifyResult

```yaml
verify_result:
  status: passed | failed | blocked
  command:
  exit_code:
  stdout_summary:
  stderr_summary:
```

### 6.8 MemoryEntry

```yaml
memory_entry:
  memory_id:
  repo_id:
  memory_kind:
  content:
  file_paths:
  module_tags:
  task_type:
  source_run_id:
  verified:
  stability_level:
  confidence:
  conflict_count:
  status:
```

## 7. Agent Loop

### 7.1 States

- `ingest`: load task, repo, constraints, budgets, and strategy.
- `analyze`: understand the task and identify initial repo clues.
- `plan`: produce a staged execution plan before the first action.
- `act`: call tools or apply changes.
- `observe`: interpret tool results and update runtime memory.
- `reflect`: analyze low progress, verification failure, or conflicting evidence.
- `verify`: run validation checks.
- `finalize`: emit final status, reports, and eligible memory writes.

### 7.2 Transition Rules

```text
ingest -> analyze -> plan -> act -> observe

observe -> act
observe -> reflect
observe -> verify

verify -> finalize
verify -> reflect

reflect -> act
reflect -> plan
reflect -> finalize
```

### 7.3 Invariants

- The first `act` must be preceded by `plan`.
- `finalize` must not happen before at least one verification attempt unless the task type explicitly allows non-verification completion.
- `reflect` is not a mandatory step in every loop cycle.
- Every tool call increments `tool_call_count`.
- Every state transition must emit a trace event.

### 7.4 Reflect Triggers

- Verification failure.
- Consecutive tool results with no new information.
- Repeated identical tool-call patterns with no state change.
- Repeated reads or searches over the same files without new signal.
- Tool result conflicts with the active plan.
- Approaching step or tool-call budget.

### 7.5 No-Progress Rules

- Three consecutive steps without new candidate files, useful diff, or improved verification.
- Two consecutive code changes with no verification improvement.
- Repeated empty tool results without plan update.
- Repeated identical tool calls with identical outputs.

## 8. Context Architecture

### 8.1 Context Layers

- `task_context`
- `repo_context`
- `runtime_context`
- `memory_context`

### 8.2 Layer Semantics

`task_context`

- Objective.
- Success criteria.
- Constraints.
- Prohibitions.
- Budgets.
- Task type.

`repo_context`

- Repo map.
- Key modules.
- Build and test commands.
- Candidate files.
- Relevant code facts.

`runtime_context`

- Current plan.
- Recent tool calls.
- Key observations.
- Current diff summary.
- Tried paths.
- Active hypotheses.

`memory_context`

- Selected stable long-term memory entries.

### 8.3 Injection Policy

Raw injection:

- Task objective.
- Success criteria.
- Key constraints.
- Recent verification error.
- Active code snippets.
- Active test snippets.
- Patch-adjacent context.

Summary injection:

- Large files.
- Long command output.
- Historical attempts.
- Old verification results.
- Diff summary.

Index-only:

- Full repo file list.
- Full trace history.
- Large documents.
- Long-term memory corpus.
- Low-probability candidate files.

### 8.4 Context Build Output

The context builder should return:

- final messages
- source references
- truncation summary
- selected candidate files
- memory entries used

This is required for replay and diagnostics.

## 9. File-Level Recall

MVP uses file-level recall plus lightweight keyword and symbol search.

Recall flow:

1. Extract clues from task, errors, tests, recent results, and memory.
2. Map clues to candidate files.
3. Rank files by signal strength.
4. Read summaries or matched snippets for top candidates.
5. Inject only high-value snippets into context.

Signal tiers:

- Strong: stack traces, test output, explicit file names, function names, class names, test names.
- Medium: keyword matches, file names, directory names, repo summary hints.
- Weak: fuzzy keyword matches, broad module tags, memory hints.

The recall layer does not directly decide the final prompt contents. It only produces ranked candidates for context building.

## 10. Memory Architecture

### 10.1 Runtime Memory

Runtime memory is a per-run structured state store.

It should record:

- current plan
- read files
- modified files
- candidate files
- tried paths
- key tool results
- key errors
- verification status
- diff summary
- active hypotheses
- progress and no-progress signals

### 10.2 Long-Term Memory

Long-term memory is a cross-run structured store.

Store only:

- stable repo facts
- build and test commands
- key modules and entry points
- user preferences
- successful fix patterns
- task-type-specific repo experience

### 10.3 Write Rules

- Default write only after successful completion and verification pass.
- Store small, structured entries instead of long task stories.
- Increment conflict metadata when memory and live evidence disagree.

### 10.4 Retrieval Rules

MVP retrieval uses:

- repo filter
- task-type filter
- module-tag filter
- file-path filter
- keyword search

MVP does not use embedding retrieval.

### 10.5 Memory Pollution Readiness

MVP includes:

- `memory_pollution` diagnostic label
- `memory_conflict` evidence in trace or diagnostics
- schema support for confidence, conflict count, and status

MVP excludes dedicated memory-pollution strategy experiments.

## 11. Model Adapter

The model adapter normalizes provider-specific behavior.

Suggested interface shape:

```python
class BaseModelAdapter:
    def generate(self, request): ...
    def supports_native_tools(self) -> bool: ...
    def supports_structured_output(self) -> bool: ...
    def max_context_tokens(self) -> int: ...
```

The normalized response should include:

- assistant text
- structured decision
- tool call requests
- usage metadata
- raw provider metadata

The architecture should support both:

- native tool calling
- text action parsing

## 12. Tool Layer

### 12.1 Core Tools

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

### 12.2 Tool Contract

Every tool definition should include:

- name
- description
- argument schema
- execution handler
- permission constraints

Every tool result should include:

- `status`
- `output`
- `error`
- `metadata`
- `duration_ms`

Command tools should also include:

- `exit_code`
- `stdout`
- `stderr`
- `timed_out`

### 12.3 Safety Rules

- All file writes must remain in workspace scope.
- Dangerous command patterns must be blocked.
- Command execution must have timeout and working-directory control.
- Tool failures must be structured, not raised as silent exceptions.

## 13. Trace and Replay

### 13.1 Trace Format

Trace is JSONL, one event per line.

Core event types:

- `run_started`
- `state_entered`
- `context_built`
- `model_requested`
- `model_responded`
- `tool_called`
- `tool_completed`
- `memory_read`
- `memory_written`
- `patch_applied`
- `verify_completed`
- `reflect_completed`
- `state_transitioned`
- `run_finished`

### 13.2 Event Shape

```json
{
  "run_id": "run_001",
  "task_id": "bug_fix_001",
  "event_id": 1,
  "timestamp": "2026-06-11T00:00:00Z",
  "state": "act",
  "event_type": "tool_called",
  "payload": {}
}
```

### 13.3 Storage Policy

Trace should store:

- structured event metadata
- summaries for large payloads
- references to external artifacts when payloads are large

Large artifacts may include:

- long stdout or stderr
- full prompts
- full file snapshots
- long diff outputs

### 13.4 Replay Modes

MVP replay modes:

- trace replay: reconstruct the historical run timeline
- deterministic rerun: optional later enhancement for re-executing the same task with the same config

## 14. Eval Architecture

### 14.1 Task Spec

Eval task specs should be YAML or JSON.

Suggested fields:

- `id`
- `task_type`
- `repo`
- `instruction`
- `success_criteria`
- `allowed_tools`
- `budgets`
- `validation`
- `expected_touched_files`
- `forbidden_touched_files`
- `tags`

### 14.2 Metrics

Result metrics:

- success
- validation pass
- expected files touched
- unexpected changes

Process metrics:

- steps
- tool calls
- verify count
- reflect count
- duration

Diagnostic metrics:

- primary failure
- secondary failures
- evidence
- diagnosis source

### 14.3 Experiment Rules

- Define a baseline.
- Change one variable at a time.
- Keep task set, model, and budgets fixed for comparisons.
- Save a full config snapshot for every run.

## 15. Reports

MVP reports are Markdown.

Single-run report sections:

- summary
- final status and stop reason
- strategy and model
- changes
- timeline
- diagnostics
- verification
- memory read and write

Batch eval summary sections:

- task set
- strategy
- model
- success rate
- average process metrics
- success by task type
- failure profile
- delta against baseline

## 16. Persistence Layout

Suggested run output layout:

```text
runs/
  run_20260611_001/
    trace.jsonl
    report.md
    config_snapshot.yaml
    artifacts/
      verify_stdout.txt
      verify_stderr.txt
      prompt_003.txt
```

Suggested long-term memory layout:

```text
memory/
  long_term_memory.jsonl
```

The exact storage backend can remain simple in MVP. JSONL and local files are enough.

## 17. Evolution Path

### MVP

- fixed baseline loop
- file-level recall
- structured long-term memory without embeddings
- local CLI
- JSONL trace
- Markdown reporting
- batch eval

### Post-MVP

- richer model adapters
- embedding-based memory retrieval
- stronger diagnostics automation
- symbol-aware recall
- memory pollution strategy experiments
- remote execution isolation
- richer report UI

## 18. Architecture Risks

- Context builder can become the hidden complexity center if layer boundaries are not enforced.
- Tool contracts can drift if outputs are not normalized early.
- Trace volume can become noisy if event payload policy is not controlled.
- Memory can pollute future runs if write rules are relaxed too early.
- Eval can become untrustworthy if success criteria are not task-type-specific.

The MVP architecture is intentionally conservative to reduce these risks while preserving future extension points.
