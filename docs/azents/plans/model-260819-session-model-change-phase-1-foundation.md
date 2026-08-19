---
title: "Session Model Change Phase 1 Foundation Plan"
created: 2026-08-19
tags: [model, session, migration, api, openapi]
---

# Session Model Change Phase 1 Foundation Plan

## Phase Execution Plan

- Phase: `1 — Applied profile foundation`
- Branch/base: `feature/model-260819-1-session-profile-foundation` → `origin/main`
- PR boundary: durable applied/prepared Session state split, forward migration,
  idempotent model-profile API, public projection changes, OpenAPI and generated
  public clients
- Inputs: confirmed [`model-260819/REQ`](../requirements/model-260819-session-model-change.md),
  accepted [`model-260819/ADR`](../adr/model-260819-session-model-change.md), approved
  [`model-260819/DESIGN`](../design/model-260819-session-model-change.md) revision 2,
  current migration head `c05f9971773f`, current Conversation and Agent Specs
- Deliverables: separate nullable applied intent and retained prepared snapshot in the
  domain/repository/schema; generated migration and tests; minimal no-side-effect
  model-profile PUT with replay-before-validation semantics; existing Session response
  fields sourced from applied intent; regenerated public clients
- Non-goals: admission-time application for message/edit/TurnAction; mailbox promotion
  removal; fresh-boundary worker changes; Composer wiring; E2E and Living Spec
  promotion; live cutover or deployment
- Interfaces: nullable applied-profile domain type; repository read/replace methods;
  retained prepared `SessionInferenceState`; model-profile request/response DTOs;
  `ChatWriteRequestType.MODEL_PROFILE`; applied-profile projection available to later
  explicit-write responses
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M10`
- Authority references: `model-260819/REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-9`;
  `model-260819/ADR-D1`, `ADR-D2`, `ADR-D3`; current Conversation and Agent Specs
- Design delta: `None`
- Removal obligations: combined public/prepared Session inference authority; missing
  transcript-free mutation; any proposed AgentRun inference snapshot; physical model
  fields in public model-profile contracts
- Absence verification: repository divergence tests; API/generated schemas contain
  only label and effort; source/schema search shows no AgentRun inference columns; API
  side-effect tests show no mailbox/event/Run/wake/provider/WS activity

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Domain and ORM split | `/root/model-260819-foundation-owner` | `python/apps/azents/src/azents/core/inference_profile.py`, `rdb/models/agent_session.py`, `repos/agent_session/**`, focused tests | approved M1/M2 | explicit applied-intent type/fields and independent prepared-state round trip | inference-profile, ORM, repository tests; Ruff/type checks |
| Forward migration | `/root/model-260819-foundation-owner` | `python/apps/azents/db-schemas/rdb/**`, `python/apps/azents/migration_tests/**` | stable ORM fields | Alembic revision after `c05f9971773f`, enum/columns/constraints/backfill, revision marker | migration-focused tests, single-head and upgrade suite |
| Model-profile service and idempotency | `/root/model-260819-foundation-owner` | `rdb/models/chat_write_request.py`, `repos/chat_write_request/**`, `services/chat_write.py` or focused service, tests | applied repository interface | replay-before-validation full replacement with active root authorization and no execution side effects | repository/service idempotency, conflict, authorization and no-side-effect tests |
| Public API and projection | `/root/model-260819-foundation-owner` | `api/public/chat/v1/{data.py,__init__.py,*test.py}`, service wiring | domain/service outputs | minimal PUT request/response and Session response fields sourced from applied intent | API/data-contract tests and OpenAPI diff |
| Generated public clients | `/root` | `python/apps/azents/specs/public/openapi.json`, `python/libs/azents-public-client/**`, `typescript/packages/azents-public-client/**` | stable public API | regenerated Python and TypeScript clients | generation commands, package/type checks, generated diff inspection |
| Independent review | `/root/model-260819-implementation-reviewer` | read-only full Phase 1 plan and diff | stable Phase 1 diff | authority/security/migration/idempotency/removal report | explicit approve or blocking findings |

- Integration order: domain types and ORM → generated Alembic revision and repository
  round trip → idempotency type/service → public DTO/route/projection → OpenAPI dump and
  generated clients → focused/full Phase 1 validation → independent review → fixes and
  revalidation → commit and PR
- Independent review: `/root/model-260819-implementation-reviewer` reviews M1/M2/M3/M10,
  prepared/applied divergence, migration and rollback safety, canonical lock order,
  replay-before-validation, root/User/subagent authorization, no side effects, public
  physical-data absence, and no unauthorized compatibility or AgentRun authority
- Final validation: from `python/apps/azents`, focused pytest for inference profile,
  AgentSession repository, chat-write service/API/data contracts and migration tests,
  then Ruff format/check and `ty`; dump public OpenAPI; regenerate Python client from
  `python/libs/azents-public-client` and TypeScript client from `typescript`; run
  affected generated-client/type checks; run documentation snapshot validation
- Scope-drift check: every Phase 1 change maps to M1/M2/M3/M10; Phase 2 admission and
  worker semantics, Phase 3 frontend behavior, and Phase 4 E2E/Specs remain absent;
  no physical client input, fallback, WebSocket frame, wake, queued switch, Agent
  fanout, Redis authority, or mixed-version compatibility path is added
- Context checkpoint: Phase 1 completes when applied and prepared states can diverge,
  legacy data migrates safely, the model-profile endpoint and generated contracts are
  stable, focused checks/review pass, and PR 1 is open. Remaining scope is admission
  and worker semantics, frontend integration/removal, deterministic E2E, Living Specs,
  implementation dates, and plan cleanup.
