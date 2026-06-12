# Document Set Reference

Use this file only when deciding which documents to create and what belongs in each one.

## Core Documents

### `PRD`

Purpose:

- Define the product goal, scope, non-goals, target task types, and success criteria.

### `ARCHITECTURE`

Purpose:

- Define system structure, major modules, interfaces, and baseline technical choices.

### `MONTH_PLAN`

Purpose:

- Break the first delivery window into week-by-week or phase-by-phase milestones.

### `DEVELOPMENT_PLAYBOOK`

Purpose:

- Define implementation order, phase breakdown, completion definitions, and resume rules.

## Control Documents

### `DECISIONS`

Purpose:

- Record key MVP decisions and why they were made.

Use when:

- the project has multiple design branches that should not be reopened repeatedly

### `CURRENT_STATUS`

Purpose:

- Record the current active phase, immediate next step, and current blockers.

Use when:

- future sessions need a fast snapshot

### `PHASE_PROGRESS`

Purpose:

- Track each phase as `not_started`, `in_progress`, `completed`, or `blocked`.

Use when:

- the project will span multiple sessions

### `SESSION_ENTRY`

Purpose:

- Tell a new session what to read first and what not to preload.

Use when:

- the document set has grown enough that full loading would waste context

## Recommended Creation Threshold

Create only what the project needs:

- very small exploratory projects may stop at `PRD + PLAYBOOK`
- multi-session implementation projects should add the full control document set
- bilingual duplicates are justified only when they materially help the human operator
