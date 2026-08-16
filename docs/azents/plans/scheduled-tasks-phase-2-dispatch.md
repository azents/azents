---
title: "Scheduled Tasks Phase 2 Dispatch and Start Admission Plan"
created: 2026-08-16
tags: [scheduled-task, scheduler, mailbox, agent-run, toolkit-state, concurrency]
---

# Phase Execution Plan

- Phase: `2/8 — Dispatch and start admission`
- Branch/base: `feature/scheduled-tasks-2-dispatch` →
  `feature/scheduled-tasks-1-foundation`
- PR boundary: Make Session-only Scheduled Task occurrences durably due, admitted
  through FIFO Mailbox, and bound to AgentRuns at the exact start boundary without
  exposing Agent management tools or terminal execution.
- Inputs: Phase 1 Task schema/repository, nullable AgentRun cycle field, complete
  closed trigger/continuation/result protocol readers, confirmed
  `scheduled-260816/REQ`, accepted `scheduled-260816/ADR-D1` through `ADR-D4`, and
  approved `scheduled-260816/DESIGN` revision `3`.
- Deliverables: Canonical schedule parsing and cursor calculation; shared Task
  create/list/edit/delete service; bounded due dispatcher and Scheduler
  registration; due leases, coalescing, active/pending fences, immutable admitted
  cycle snapshots, idempotent trigger Mailbox insertion, post-commit wake; trigger
  and continuation admission into cycle-bound AgentRuns; exact pre-start deletion
  suppression and post-start independence; focused deterministic concurrency and
  recovery tests.
- Non-goals: ScheduledToolkit management or terminal tools, managed Skill VFS
  activation, idle-continuation production, compaction enrichment, provider
  presentation or effects, Session/Binding lifecycle participants, Public API,
  generated Scheduled Task clients, Web management UI, testenv/E2E journeys,
  Living Spec promotion, or `implemented` dates.
- Interfaces: `scheduled_tasks` remains the only Task/cursor/lease/fence authority;
  admitted and started cycles use schema-version-1 Toolkit State under namespace
  `scheduled` and state name `cycle:{cycle_id}`; one trigger Mailbox item uses the
  existing safe typed payload and `wake_session`; the trigger processor changes
  `admitted` to `started` in the same transaction that creates and binds the
  AgentRun; continuation admission requires existing `started` cycle state and does
  not require a surviving Task row; wake happens only after the canonical
  admission transaction commits.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M13`
- Authority references: `scheduled-260816/REQ-1`, `REQ-4`, `REQ-5`, `REQ-6`,
  `REQ-13`, `REQ-14`; `scheduled-260816/ADR-D1`, D2, D3, D4; approved Design
  revision `3`.
- Design delta: `None`
- Removal obligations: Replace historical Session-per-occurrence execution with
  the selected existing Session, FIFO Mailbox, AgentRun, and cycle Toolkit State.
  Do not restore historical owner-user/status/provider-coordinate behavior, use
  `scheduled_task_states` for product Tasks, add Redis correctness authority,
  introduce a second scheduler, or add compatibility routes/tools.
- Absence verification: Stable Session IDs in admission tests; static imports prove
  product code does not use `scheduled_task_states`; registry contains one bounded
  user-Task dispatcher; repository/schema searches find no historical status,
  retry-history, provider-coordinate, or Session-creation path.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared plan and composition | `/root` | this phase plan; `scheduler/{registry.py,registry_test.py,user_scheduled_task_dispatch.py}`; exact `repos/mailbox/{__init__.py,repository_test.py}` lock surface; shared composition-only edits | both implementation workstreams | registered bounded dispatcher, explicit Scheduler-side DI/clock, exact Scheduled CRUD Mailbox lock, and conflict-free composition | mailbox and registry tests, import smoke, diff/scope audit |
| Task service and Scheduler dispatcher | `/root/scheduled-data-scheduler-scout` | `repos/scheduled_task/**`; new `services/scheduled_task/**`; focused Task/Scheduler tests excluding shared registry files | Phase 1 Task row; cycle repository and typed Mailbox contracts | validation, cursor, CRUD, leases, coalescing, admitted snapshot handoff, idempotent trigger, wake outcome | focused pytest including PostgreSQL locks/races, Ruff, formatter, ty |
| Cycle state and worker admission | `/root/scheduled-toolkit-runtime-scout` | new `repos/scheduled_task_cycle/**`; `repos/agent_execution/**`; `services/mailbox.py` and focused tests; `worker/session/lifecycle.py`, `worker/run/executor.py`, and focused tests | Phase 1 closed payloads and AgentRun field | schema-versioned cycle state, trigger start transaction, continuation binding, stale-trigger consumption, immutable Run binding | focused repository/Mailbox/worker pytest, Ruff, formatter, ty |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 2 diff | stable integrated diff and focused evidence | authority, race, privacy, recovery, removal, and scope-drift verdict | written blocker/no-blocker report with exact evidence |

- Integration order: Fix cycle-state repository contract → implement schedule and
  Task service → implement leases/coalescing and dispatcher handoff → implement
  trigger/continuation worker admission → register the dispatcher and compose
  dependencies → run cross-boundary deletion/wake/recovery tests → scope and
  absence audit → independent review → corrections → final validation.
- Independent review: `/root/scheduled-stack-reviewer` reviews read-only against
  confirmed Requirements, accepted ADR-D1 through D4, approved Design
  M1/M2/M3/M4/M13, current Specs, this plan, Phase 1 contracts, focused evidence,
  and the stable diff. Review priority is atomicity, lock ordering, duplicate
  admission, lost wake recovery, pre/post-start deletion behavior, sanitized
  model-visible content, immutable AgentRun binding, and later-phase scope.
- Final validation: Focused schedule/Task/dispatcher/cycle/Mailbox/AgentRun/worker
  tests; PostgreSQL lease and race tests; Scheduler registry tests; `uv run ruff
  check .`; `uv run ruff format --check .`; `uv run ty check
  --error-on-warning`; full `uv run pytest`; canonical OpenAPI stability; docs
  validation; `git diff --check`.
- Scope-drift check: Confirm complete M1–M4/M13 coverage and no missing trigger or
  continuation reader. Confirm the diff adds no Agent-facing tool, terminal result
  execution, Skill activation, compaction hook, provider effect, lifecycle
  participant, API route, generated Scheduled Task client, Web management feature,
  compatibility path, duplicate scheduler, or second persistent Session.
- Context checkpoint: Phase starts from Phase 1 tip `2ef56c01e`, whose backend full
  suite, migration checks, Python quality checks, generated public contract
  compatibility, Web tests/typecheck/build, and independent review passed. The
  untracked Scheduled Skill VFS remains preserved for Phase 3. Phase 3 may begin
  only after this PR is open and receives the stable Task service, dispatcher
  outcome, cycle repository, and AgentRun admission interfaces.
