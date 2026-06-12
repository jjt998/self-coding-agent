# One-Month Plan

## Week 1: Single Task Loop

Goal: run one local task end to end and leave a structured trace.

Deliverables:

- CLI skeleton.
- Agent state enum and state-machine loop.
- Model adapter base interface.
- Initial model provider implementation or stub.
- Tool registry.
- Core tools:
  - `search_text`
  - `read_file`
  - `apply_patch`
  - `run_command`
  - `git_diff`
- Runtime memory.
- JSONL trace writer.
- Minimal Markdown run report.

Acceptance:

- A simple code understanding or bug fix task can run through `ingest -> analyze -> plan -> act -> observe -> verify -> finalize`.
- Tool calls and state transitions are recorded in trace.
- A run report is generated.

## Week 2: Context and Memory

Goal: make model input controlled and memory-aware.

Deliverables:

- `task_context`, `repo_context`, `runtime_context`, and `memory_context`.
- File-level recall.
- Raw, summary, and index-only context policies.
- Context budget and trimming rules.
- Structured long-term memory store.
- Memory read/write events in trace.
- Conditional reflect triggers.
- Memory conflict evidence recording.

Acceptance:

- Different context strategies can be configured.
- Successful verified runs can write long-term memory.
- Later runs can retrieve relevant memory.
- Reflect triggers on verification failure or repeated low progress.

## Week 3: Eval Loop

Goal: move from single runs to repeatable evaluation.

Deliverables:

- Eval task spec schema.
- Eval runner.
- Result metrics.
- Process metrics.
- Diagnostic labels.
- Rule-based diagnostic pass.
- Batch Markdown eval summary.
- Initial task set with 12 to 20 tasks.

Acceptance:

- One command can run a fixed eval task set.
- Summary includes success rate, average steps, average tool calls, reflect count, verify count, and failure profile.
- Failed tasks include primary failure, secondary failures, and evidence.

## Week 4: Strategy Comparison

Goal: prove that the harness supports meaningful iteration.

Deliverables:

- Baseline strategy config.
- Context strategy comparison:
  - `naive_recent_context`
  - `file_recall_context`
  - `file_recall_plus_summary`
- Memory comparison:
  - `memory_off`
  - `structured_memory_on`
- Reflect comparison:
  - `verify_failure_only_reflect`
  - `low_progress_plus_verify_reflect`
- Strategy comparison report.
- Representative trace analysis.
- README and design documentation cleanup.

Acceptance:

- At least two strategies can be compared on the same task set.
- Reports show result, cost, and failure-profile deltas.
- The project can answer at least three research questions:
  - Does file-level recall reduce `context_miss`?
  - Does structured memory reduce repeated exploration?
  - Does conditional reflect reduce `repeated_no_progress`?

## MVP Completion Criteria

The one-month MVP is complete when:

- Local CLI can start a task.
- The agent can plan, use tools, modify files, verify, and finalize.
- Every run emits JSONL trace.
- Every run emits a Markdown report.
- A fixed eval set can run in batch.
- Strategy comparison works.
- Failures are categorized with evidence.
- Memory pollution is detectable through diagnostic tags and conflict evidence.

## Deferred Work

- Web UI.
- IDE integration.
- Multi-agent execution.
- Remote sandbox.
- Full symbol graph.
- Embedding memory.
- Dedicated memory pollution experiments.
- Large benchmark integration.
