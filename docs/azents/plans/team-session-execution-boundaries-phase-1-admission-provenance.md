---
title: "Team Session execution boundaries phase 1: durable admission and sender provenance"
created: 2026-07-24
tags: [session, authorization, provenance, migration, api, frontend]
---

# Team Session execution boundaries phase 1: durable admission and sender provenance

## Phase Execution Plan

- Phase: `1 — Durable admission and sender provenance`
- Branch/base: `feature/team-session-admission-provenance` → `plan/userless-session-authorization`
- PR boundary: durable requester admission, idempotency, Human sender provenance, public projection, generated clients, and sender presentation
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Multi-phase plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)
- Inputs: approved snapshot and completed design/implementation-plan PR branches
- Deliverables:
  - Human message and TurnAction admission reauthorizes the requester inside one transaction before durable side effects.
  - Edit, command, failed-run retry, and stop operations reauthorize the current requester inside
    their mutation transaction; idempotent retries reveal accepted results only after
    reauthorization and before mutable idle-state checks.
  - `chat_write_requests` provides durable message and TurnAction idempotency, payload mismatch rejection, and stable post-promotion retry results.
  - New Human inputs retain `sender_user_id`; non-Human and historically unknown provenance remain null.
  - Promotion materializes Human attachments from their admission-time root Session claim without
    reauthorizing or otherwise using `sender_user_id`; post-admission membership loss does not revoke
    accepted attachment work.
  - A failed post-commit wake remains retryable: repeating an accepted request re-notifies pending
    work without recreating the InputBuffer or rebroadcasting its live event.
  - Sender provenance reaches InputBuffer, durable message/action payloads, forks, live/history projections, ActionExecution, and terminal action output.
  - Requester audit fields use explicit requester-oriented names for chat writes, pending commands, and stop metadata.
  - A generated Alembic revision and revision pointer carry the Phase 1 schema/data changes without applying a database upgrade.
  - Public OpenAPI and generated Python/TypeScript clients expose the Phase 1 projection contract.
  - azents-web displays a current Workspace profile only for an exact sender match and otherwise uses a bounded unavailable state without inference.
- Non-goals:
  - Phase 2 routing-only broker messages, canonical execution snapshots, and Worker/RunExecutor cutover.
  - Phase 3 removal of generic User fields from Engine, Toolkit, Memory, continuation, and subagent execution contracts.
  - Phase 4 general Session/Run resource authority and file/output ownership migration outside the
    accepted Human attachment promotion path required to keep Phase 1 sender provenance-only.
  - Phase 5 replay tooling, coordinated production cutover, or database upgrade execution.
  - Final E2E evidence, living spec promotion, implemented snapshot dates, or cleanup.
- Interfaces:
  - `sender_user_id` is immutable input provenance only and never grants execution, resource, credential, or personalization authority.
  - Human attachment promotion resolves only files already claimed at admission to the exact root
    Session and creates pending ModelFiles through an internal Agent/Session boundary; it does not
    repeat Workspace membership authorization or require a Human User.
  - `requester_user_id` is limited to public authorization, audit, command, and stop operations.
  - Public edit, command, failed-run retry, and stop services lock the target Session and reauthorize
    `requester_user_id` before returning an existing idempotency record or creating durable effects.
  - Historical sender provenance is nullable and must never be reconstructed from creator, owner, viewer, approver, uploader, or another fallback.
  - System-initiated operations do not manufacture requester or sender identity.
  - Generated clients come only from the repository OpenAPI/client generators.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema and durable repositories | Phase 1 implementation owner | `python/apps/azents/db-schemas/rdb/**`, `src/azents/rdb/models/{input_buffer,action_execution,agent_session,chat_write_request}.py`, `src/azents/repos/{input_buffer,action_execution,agent_session,chat_write_request}/**` | Approved data contract | Generated migration, revision pointer, renamed requester fields, sender persistence, repository coverage | Migration static inspection, focused Ruff/Pyright/pytest, repository tests |
| Transactional admission and idempotency | Phase 1 implementation owner | `src/azents/services/{agent_session_input,chat_write,input_buffer}.py`, `src/azents/api/public/chat/v1/**`, related tests | Schema and repository contracts | In-transaction requester reauthorization for messages, TurnActions, edit, command, failed-run retry, and stop; rollback safety; stable idempotent retry before mutable state checks; retry wake without duplicate live projection | Admission/idempotency API, service, repository, membership-revocation race, broker-failure retry, and stop-subtree tests |
| Accepted attachment promotion boundary | Phase 1 implementation owner | `src/azents/services/{exchange_file,model_file,input_buffer}.py`, `src/azents/engine/run/resolve.py`, related tests | Admission-time root Session claim and durable sender contract | Root-claim-authorized materialization and pending ModelFile creation with no sender/User authorization dependency | Membership-loss-after-admission, cross-root denial, exact Agent/Session, expiry/unavailable, retry, and cleanup-compensation tests |
| Sender propagation and system callers | Phase 1 implementation owner | `src/azents/engine/events/**`, `src/azents/services/{action_execution,agent_mailbox,chat/live_events}.py`, Worker/recovery/system-caller paths and tests | Durable sender contract | Live/history/fork/action propagation with null system provenance | Event, projection, Worker, recovery, mailbox, action, and system-caller tests |
| Public clients and sender presentation | Phase 1 implementation owner | public OpenAPI/generated clients, `typescript/apps/azents-web/src/features/chat/**`, locale messages, focused tests/stories | Public API projection | Generated client contract and exact-match/unavailable sender UI | OpenAPI/client generation, web test, format, lint, typecheck, build |

- Dependency order:
  1. Fix schema and repository contracts.
  2. Complete admission/idempotency against those contracts.
  3. Remove sender/User authorization from accepted attachment promotion.
  4. Propagate sender provenance through durable and runtime projections.
  5. Regenerate public clients and complete web projection.
  6. Run integrated Phase 1 verification.
- Integration order: schema/repositories → services/API → accepted attachment promotion → events/system callers → generated clients → web → integrated verification
- Agent continuity:
  - Keep the Phase 1 implementation owner for review findings that require workstream-level reimplementation.
  - The primary agent controls all role assignment, Phase progression, and workstream reassignment.
  - The independent review owner may continue in later phases only while remaining separate from implementation.
- Independent review:
  - Owner: a review subagent assigned by the primary agent after primary-agent verification; it must not have participated in implementation.
  - Scope: full Phase 1 diff against the plan branch, with priority on authorization, transaction rollback, idempotency races, null provenance, migration safety, generated-contract consistency, and UI non-inference.
  - Inputs: approved snapshot, multi-phase plan, this Phase plan, complete diff, project rules, and primary verification results.
  - Output: grounded Critical/Warning findings with exact paths and rationale, or an explicit no-findings result.
  - Finding handling: the primary agent applies accepted findings directly and asks the same reviewer to recheck them; only workstream-level reimplementation is delegated to the implementation owner.
- Final validation:
  - `git diff --check`
  - Focused Ruff and Pyright for all changed backend source/test paths.
  - Focused pytest covering API admission, repositories, idempotency, sender projection, system callers, Worker, recovery, and action execution.
  - Migration revision/head inspection and migration-focused tests without applying a database upgrade to a shared environment.
  - Repository OpenAPI dump plus generated Python and TypeScript public clients.
  - Sequential azents-web format, lint, typecheck, test, and build checks.
  - Documentation/frontmatter/index checks through pre-commit when committing the plan and Phase implementation.
- Scope-drift check:
  - Compare every changed path and behavior with this plan's deliverables and non-goals.
  - Move Phase 2+ runtime cutover, Userless Engine, resource authority, replay, E2E evidence, spec promotion, and cleanup work out of this branch.
  - Confirm sender remains provenance-only, accepted attachment promotion does not reauthorize a
    Human User, and no ambient execution User inference was introduced.
