# Self Coding Agent PRD

## 1. Project Goal

Build a local-repo coding agent harness for research and learning. The system should be usable, but its primary goal is to compare and iterate on agent loop, context management, memory, tool use, and eval strategies.

The one-month MVP should prove that the harness can run local coding tasks, record structured traces, evaluate outcomes, and compare strategy variants.

## 2. Product Positioning

This project is a research-oriented harness, not a polished IDE product.

It should answer questions such as:

- Which context strategy reduces context misses?
- Does structured memory reduce repeated exploration?
- Does conditional reflection reduce repeated no-progress loops?
- Which failures come from context, tools, loop design, verification, or memory?

## 3. In Scope

- Local repository CLI.
- Single-agent execution loop.
- Pluggable model adapter interface.
- Core tools for local code work.
- Explicit state-machine loop.
- File-level context recall.
- Runtime memory.
- Structured long-term memory.
- JSONL trace.
- Trace replay.
- Markdown run reports.
- Batch eval runner.
- Strategy comparison reports.

## 4. Out of Scope for MVP

- Web UI.
- IDE plugin.
- Multi-agent collaboration.
- Browser automation.
- Remote sandbox or cloud runner.
- GitHub PR automation.
- Heavy AST/LSP symbol graph.
- Vector database or embedding memory.
- Large public benchmark reproduction.
- Complex permission system.
- Dedicated memory pollution A/B experiments.

## 5. Target Task Types

The MVP should support four task categories:

- `code_understanding`: locate and explain relevant code.
- `bug_fix`: fix a small, localized bug.
- `test_generation`: add or improve focused tests.
- `refactor`: perform a local behavior-preserving refactor.

## 6. Core User Flows

### 6.1 Single Task Run

Input:

- Repo path.
- Task instruction.
- Model config.
- Strategy config.
- Budgets.

Output:

- Final status.
- Modified files, if any.
- Verification result.
- JSONL trace.
- Markdown run report.

### 6.2 Batch Eval Run

Input:

- Eval task set.
- Model config.
- Strategy config.
- Fixed budgets.

Output:

- Per-task run reports.
- Aggregate eval summary.
- Result, process, and diagnostic metrics.
- Strategy comparison report.

## 7. Agent Loop Requirements

The first MVP loop is a fixed baseline:

- `ingest`
- `analyze`
- `plan`
- `act`
- `observe`
- `reflect`
- `verify`
- `finalize`

`fail` is not a state. Failures are represented by structured status and stop reason.

Rules:

- The first `act` must be preceded by `plan`.
- During execution, `act <-> observe` may repeat without re-planning.
- `reflect` is conditionally triggered by verification failure, repeated low-value attempts, conflicting results, or budget pressure.
- `finalize` requires at least one verification attempt.
- Verification failure enters `reflect` before further action or termination.

## 8. Context Requirements

The context system has four layers:

- `task_context`: objective, success criteria, task type, constraints, prohibitions, and budgets.
- `repo_context`: repo map, relevant files, key modules, build/test commands, and task-specific code facts.
- `runtime_context`: current plan, recent tool calls, key observations, diff summary, failed paths, active hypotheses.
- `memory_context`: selected stable cross-run knowledge.

Context injection policy:

- Preserve precise high-value content as raw text.
- Summarize large or historical content.
- Keep large low-probability content as an index or reference.
- Prefer key information over merely recent information.

## 9. Memory Requirements

### 9.1 Runtime Memory

Runtime memory serves one run and records:

- Current state.
- Current plan.
- Read files.
- Modified files.
- Candidate files.
- Tried paths.
- Key tool results.
- Key errors.
- Verify status.
- Diff summary.
- Active hypotheses.
- Progress and no-progress signals.

Runtime memory is broader than the model context. Only selected slices enter the prompt.

### 9.2 Long-Term Memory

Long-term memory serves cross-run reuse.

It should store stable, low-noise, high-value information:

- Repo facts.
- Build and test commands.
- Key modules and entry points.
- User preferences.
- Successful repair patterns.
- Task-type-specific repo experience.

Default write rule:

- Write long-term memory only after task success and verification pass.

Default retrieval:

- Structured filtering by repo, task type, tags, paths, and keywords.
- No vector database or embedding retrieval in MVP.

### 9.3 Memory Pollution Scope

MVP includes basic pollution awareness:

- Diagnostic label: `memory_pollution`.
- Runtime evidence: `memory_conflict`.
- Schema fields for confidence, conflict count, and memory status.

MVP excludes dedicated memory pollution experiments.

## 10. Tool Requirements

MVP core tools:

- `search_text`
- `read_file`
- `apply_patch`
- `run_command`
- `git_diff`

Tool requirements:

- Structured input.
- Structured output.
- Status, error, duration, and metadata recorded.
- Workspace path restrictions.
- Command timeout.
- Dangerous command blocking.
- Trace every tool call.

## 11. Eval Requirements

Eval must start in week 1.

Metrics are grouped into:

- `result_metrics`: success, validation pass, expected files touched, unexpected changes.
- `process_metrics`: steps, tool calls, verify count, reflect count, duration.
- `diagnostic_metrics`: failure type and evidence.

MVP task set size:

- 12 to 20 tasks.
- 3 to 5 tasks per target task type.

## 12. Diagnostic Labels

MVP diagnostic labels:

- `context_miss`
- `context_noise`
- `wrong_plan`
- `wrong_tool_choice`
- `tool_failure`
- `edit_failure`
- `verification_gap`
- `repeated_no_progress`
- `budget_exhausted`
- `memory_pollution`

Each diagnosis should include evidence and a source:

- `rule`
- `llm_judge`
- `human`

## 13. Stop Reasons

MVP stop reasons:

- `success`
- `step_budget_exceeded`
- `tool_budget_exceeded`
- `repeated_no_progress`
- `verification_failed`
- `unsafe_action_blocked`
- `environment_blocked`
- `need_human_input`

## 14. MVP Success Criteria

After one month, the project should be able to:

- Run a local repo task from CLI.
- Plan, act, observe, reflect, verify, and finalize.
- Modify files through controlled tools.
- Produce JSONL trace.
- Produce Markdown run report.
- Run a fixed eval task set.
- Compare at least two strategies.
- Output failure type distribution.
- Produce at least one interpretable result about context, memory, or reflect strategy.
