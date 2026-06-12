---
name: requirements-to-delivery-planning
description: Use when starting a new product or engineering project and you need to turn a long requirements discussion into a staged execution package. This skill guides Codex to drive structured requirement discovery, freeze key decisions, and produce only the minimum document set needed for iterative development, session recovery, and phased implementation.
---

# Requirements To Delivery Planning

Use this skill when a user is still shaping a new project and wants to move from discussion into an implementation-ready document set.

This skill is for planning and execution preparation, not for immediate deep implementation.

## Goals

Produce a compact package that lets future sessions continue work without replaying the full discussion.

The package should make these questions easy to answer:

- What is the project trying to achieve?
- What is in scope for the first version?
- What technical decisions are already fixed?
- What is the next concrete implementation step?
- How should a new session resume without loading everything?

## Workflow

### 1. Drive requirements discussion

Push until these are explicit:

- product goal
- target user or usage mode
- first-version scope
- non-goals
- core technical focus areas
- success criteria
- schedule or phase expectation

When the user understands unevenly, teach through targeted questions instead of dumping a complete plan.

### 2. Freeze non-negotiable MVP decisions

Before producing documents, pin the decisions that should not be reopened casually.

Typical decisions:

- execution shape or architecture baseline
- scope boundaries
- evaluation philosophy
- safety or reliability constraints
- what is deliberately deferred

### 3. Produce the minimum useful document set

Always start with:

- `PRD`
- `ARCHITECTURE`
- `MONTH_PLAN` or equivalent phase plan
- `DEVELOPMENT_PLAYBOOK`

Then add project-control docs:

- `DECISIONS`
- `CURRENT_STATUS`
- `PHASE_PROGRESS`
- `SESSION_ENTRY`

Read [references/document-set.md](references/document-set.md) when deciding what each file should contain.

Do not create extra explanatory documents unless the user explicitly asks for them or the project genuinely needs them.

### 4. Keep loading light for future sessions

Do not recommend that future sessions load every document.

Default resume path:

- `SESSION_ENTRY`
- `CURRENT_STATUS`
- `PHASE_PROGRESS`
- `DEVELOPMENT_PLAYBOOK`

Load other docs only when the current phase requires them.

### 5. Convert planning into execution

Once the minimum document set exists, stop expanding documentation.

Shift to the next unfinished implementation phase and update:

- `CURRENT_STATUS`
- `PHASE_PROGRESS`

after each meaningful step.

## Output Rules

- Prefer a small, high-signal document set over a broad documentation tree.
- Separate stable decisions from current progress.
- Keep session-resume instructions explicit.
- Write documents so a new AI session can continue without re-running the whole conversation.
- If the project is bilingual, generate paired language versions only for the documents that will be actively used.

## Default Document Order

When creating documents from scratch, use this order:

1. `PRD`
2. `ARCHITECTURE`
3. `MONTH_PLAN`
4. `DEVELOPMENT_PLAYBOOK`
5. `DECISIONS`
6. `CURRENT_STATUS`
7. `PHASE_PROGRESS`
8. `SESSION_ENTRY`

## Anti-Patterns

Avoid these:

- starting implementation before scope and control surfaces are fixed
- producing a large documentation tree before phase 1 work exists
- telling future sessions to read every document
- mixing settled decisions with active progress notes
- keeping next-step guidance only in chat history

## Resume Prompt Pattern

When the user asks for a reusable continuation prompt, generate a short prompt that:

- points to `SESSION_ENTRY`
- points to current status and phase progress
- tells the new session not to preload all documents
- tells the new session to continue from the next unfinished phase

## When To Stop Using This Skill

Once the execution package exists and implementation has started, stop using this skill as the primary mode.

At that point, the project should proceed through normal implementation guided by:

- `SESSION_ENTRY`
- `CURRENT_STATUS`
- `PHASE_PROGRESS`
