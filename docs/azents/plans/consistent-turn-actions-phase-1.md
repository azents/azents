---
title: "Consistent TurnAction Capabilities Phase 1"
created: 2026-08-23
tags: [agent, chat, backend, implementation]
---

## Phase Execution Plan

- Phase: `1 - closed TurnAction capability integration`
- Branch/base: `feature/turn-action-capability-1393` → `main`
- PR boundary: Centralize TurnAction policy, catalog, preparation, and Worker
  operation dispatch without changing public or durable contracts.
- Inputs: Confirmed `action-260823/REQ`, accepted `action-260823/ADR`, approved
  `action-260823/DESIGN` revision 1, and current conversation, toolkit,
  workspace, execution-loop, and run-resume Specs.
- Deliverables: One explicit closed capability registry, dynamic composer
  definitions, Goal/Skill semantic preparation, Worker operation executor
  registry, exhaustive tests, synchronized Specs, and validated contract parity.
- Non-goals: Third-party action plugins, new action discriminators, public schema
  changes, database migration, Skill storage changes, mailbox ordering changes,
  operation retry changes, or compatibility aliases.
- Interfaces: Typed action payloads remain ingress authority; public action
  responses and errors retain their current shape; mailbox and operation
  lifecycle ownership remains at the existing orchestration boundaries.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`
- Authority references: `action-260823/REQ-1..6`,
  `action-260823/ADR-D1..D5`, current conversation/toolkit/workspace domain
  Specs, current agent-execution-loop and run-resume flow Specs, and Python
  dependency-injection/exhaustive-union conventions.
- Design delta: `None`
- Removal obligations: All five entries in the
  `action-260823/DESIGN` Removal and Replacement table.
- Absence verification: Source search for route-owned Goal/Skill catalog
  construction, action-specific REST admission matches, Mailbox-owned Goal/Skill
  stores and preparation, RunExecutor operation action imports/matches, plus
  OpenAPI and migration diff inspection.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Capability contract and composition | primary agent | `engine/events/action_messages.py`, `engine/tools/deps.py`, `services/turn_action.py`, dependency providers | approved snapshot | closed policy/catalog/preparation registry | focused registry tests, Ruff, ty |
| API catalog and admission | primary agent | `api/public/chat/v1/__init__.py`, focused chat API tests | capability contract | generic catalog mapping and policy-driven admission | focused chat API pytest, OpenAPI diff |
| Mailbox preparation | primary agent | `services/mailbox.py`, focused mailbox and constructor fixtures | capability contract | domain-owned Goal/Skill preparation with unchanged durable outcomes | focused mailbox pytest, Ruff, ty |
| Worker operation execution | primary agent | `worker/run/turn_action_executor.py`, `worker/run/executor.py`, Worker DI, focused executor tests | capability contract and mailbox handoff | registry-owned typed operation dispatch with existing fencing/cancellation | focused executor pytest, Ruff, ty |
| Specs and final evidence | primary agent | affected `docs/azents/spec/**`, validation records in PR | stable integrated diff | current behavior documentation and complete validation evidence | `/spec-review`, docs validation, CI |

- Integration order: Capability contract → Mailbox preparation → API catalog and
  admission → Worker execution → focused tests → Specs → final validation.
- Independent review: `/root/reviewer-turn-action-1393` using the
  `/code-review` workflow on the stable final diff for Requirements/Design
  coverage, closed registration completeness, public/event compatibility,
  cancellation/recovery behavior, security/data-loss risk, and stale duplicated
  authorities.
- Final validation: `uv run ruff format .`; `uv run ruff check .`;
  `uv run ty check --error-on-warning`; focused registry/mailbox/chat/executor
  pytest; applicable full backend pytest; documentation validation; OpenAPI and
  migration absence inspection; required CI and E2E jobs.
- Scope-drift check: all M1-M6 mechanisms and every removal obligation are
  covered; no action type, schema, persistence, fallback, retry, plugin, or new
  source-of-truth behavior is added.
- Context checkpoint: Requirements/ADR/Design revision 1 are implemented; the
  closed registry, API, Mailbox, and Worker integration are complete; six Living
  Specs are synchronized; Ruff, ty, focused tests, full backend tests, OpenAPI
  parity, migration absence, and independent review passed; commit, PR, and CI
  remain; no known blocker.
