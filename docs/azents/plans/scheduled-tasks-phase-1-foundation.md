---
title: "Scheduled Tasks Phase 1 Domain Foundation Plan"
created: 2026-08-16
tags: [scheduled-task, database, migration, mailbox, events, engine]
---

# Phase Execution Plan

- Phase: `1/8 — Domain foundation`
- Branch/base: `feature/scheduled-tasks-1-foundation` →
  `feature/scheduled-tasks-0-docs`
- PR boundary: Add the additive Scheduled Task schema, persistence contracts,
  AgentRun binding field, and complete closed-protocol readers without emitting
  Scheduled work.
- Inputs: Confirmed `scheduled-260816/REQ`, accepted `scheduled-260816/ADR-D1`
  through `ADR-D7`, approved `scheduled-260816/DESIGN` revision `2`, current Periodic
  Execution, Conversation, Toolkit, Agent Execution, External Channel, and E2E Living
  Specs.
- Deliverables: One generated linear migration; new Task model/repository data
  contracts; nullable AgentRun cycle binding; typed trigger, continuation, and result
  payload readers; complete Event/Mailbox validation, lowering, filtering,
  history/live/public projections; focused migration and protocol tests.
- Non-goals: Scheduler dispatch, Task service mutations, Agent tools, cycle admission,
  ScheduledToolkit, Skill VFS activation, idle continuation production, terminal tool
  execution, provider effects, lifecycle cleanup, Public API, generated clients, Web
  UI, testenv/E2E journeys, Living Spec promotion, or `implemented` dates.
- Interfaces: New `scheduled_tasks` table and PostgreSQL schedule enum exactly match
  M1; `agent_runs.scheduled_task_cycle_id` is nullable and has no Task foreign key;
  Mailbox/Event kinds are `scheduled_task_trigger`,
  `scheduled_task_continuation`, and `scheduled_task_result`; typed payloads are
  accepted by every reader and lowerer but no producer creates them; public result
  projection exposes no Task/cycle/lease/provider identity; existing
  `scheduled_task_states` semantics do not change.
- Approved Design mechanisms: `M1`, `M3`, `M4`, `M13`, `M14`
- Authority references: `scheduled-260816/REQ-1`, `REQ-4`, `REQ-6`, `REQ-8`,
  `REQ-13`, `REQ-14`; `scheduled-260816/ADR-D1`, D2, D3, D4, D5; approved Design
  revision `2`.
- Design delta: `None`
- Removal obligations: Do not restore the historical owner-user/status/provider-
  coordinate Task schema; do not reuse `scheduled_task_states`; do not add historical
  tool/API aliases, compatibility readers, Session-per-occurrence execution, provider
  replay state, or a second scheduler.
- Absence verification: Migration and model assertions reject old columns; static
  source/import searches prove product repositories do not import
  `scheduled_task_state`; route/tool searches find no legacy aliases; generated schema
  contains no delivery ledger, retry history, tombstone, status, or provider
  coordinate fields.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved artifacts and shared integration | `/root` | `docs/azents/{requirements,adr,design,plans}/scheduled-*`, shared enum/composition files, migration generation and revision marker | approved revision 2 | tracked authority and plans, generated migration, conflict-free shared contracts | snapshot validator, docs frontmatter/index hook, migration-head check, diff check |
| Task persistence contracts | `/root/scheduled-data-scheduler-scout` | new `rdb/models/scheduled_task.py`, new `repos/scheduled_task/**`, focused model/repository tests | shared schedule enum and migration contract | Task ORM/data/repository foundation without runtime producers | targeted pytest, Ruff, formatter, ty |
| AgentRun and closed protocol readers | `/root/scheduled-toolkit-runtime-scout` | AgentRun model/repository data, Mailbox payload union, Event payload registry, lowerers, filters, history/live/public projections and focused tests | shared enum names and public payload contract | nullable cycle binding and exhaustive trigger/continuation/result readers | targeted pytest, exhaustive typecheck, Ruff, formatter |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 1 diff | stable implementation and focused evidence | authority/migration/protocol/removal/scope report | written findings with exact evidence |

- Integration order: Shared enum and schema contract → generated Alembic revision →
  Task ORM/data/repository → AgentRun field plumbing → typed Mailbox/Event payloads →
  all validators/lowerers/filters/history/live/public projections → focused tests →
  absence searches → independent review → required corrections → final validation.
- Independent review: `/root/scheduled-stack-reviewer` reviews read-only against the
  confirmed Requirements, accepted ADR, approved Design M1/M3/M4/M13/M14, current
  Specs, this plan, migration lineage, removal obligations, and the stable diff. It
  reports only authority, security/data-loss, migration, exhaustive-protocol,
  removal, lifecycle-precondition, and scope-drift findings.
- Final validation: Generated migration and revision checks; pytest-alembic and
  focused model/repository/Mailbox/Event/lowerer/projection tests; affected Python
  Ruff check and format check; Azents `ty --error-on-warning`; docs snapshot and
  frontmatter validation; Skill validator; legacy/duplicate-authority searches; and
  `git diff --check`.
- Scope-drift check: Confirm complete reader coverage for M13 and exact M1/M3/M4/M14
  schema contracts. Confirm the phase emits no Scheduled work, exposes no management
  surface, changes no `scheduled_task_states` semantics, introduces no provider
  effect or lifecycle behavior, and adds no compatibility path or second authority.
- Context checkpoint: Phase starts from `origin/main` commit `da30e50f7` with the
  approved Requirements/ADR/Design and managed Skill package untracked but externally
  backed up. Readiness review found no material decision or Design delta. Phase 2
  begins only after this PR is open and records the final schema, repository, AgentRun,
  and closed-protocol interfaces.
