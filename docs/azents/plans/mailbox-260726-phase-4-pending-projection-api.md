---
title: "Unified Agent Input Mailbox Phase 4: Pending Projection API and Clients"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, api, websocket, openapi, client, plan]
---

# Mailbox Phase 4: Pending Projection API and Clients

## Phase Execution Plan

- Phase: `4 — Pending projection API and generated clients`
- Branch/base: `feature/mailbox-260726-pending-api` → `feature/mailbox-260726-runtime-wait`
- PR boundary: Replace the legacy Event-shaped pending-input public contract with a server-owned, typed pending mailbox projection for REST live state, write snapshots, WebSocket actions, OpenAPI, and generated public clients. Correct server-side action-handoff publication ordering. Do not implement Web state or rendering.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md), the [multi-phase implementation plan](mailbox-260726-implementation-plan.md), and completed [Phase 1](mailbox-260726-phase-1-persistence.md), [Phase 2](mailbox-260726-phase-2-terminal-delivery.md), and [Phase 3](mailbox-260726-phase-3-runtime-activity-wait.md) execution plans.
- Deliverables:
  - A closed server-owned pending mailbox envelope/item projection for all current mailbox kinds, including admitted External Channel invocation items.
  - REST `/live` and write snapshots with `mailbox_items` pending envelopes instead of `input_buffers` or `input_buffer_events`.
  - Dedicated `mailbox_item_upserted` and `mailbox_item_removed` WebSocket actions; pending mailbox items do not use `live_event_upserted` or `live_event_removed`.
  - A mailbox-named pending-item delete route and action-execution source correlation without legacy public aliases.
  - Action-handoff publication ordering in which active `ActionExecution` is published before its pending mailbox projection is removed.
  - Regenerated public OpenAPI, Python client, and TypeScript client artifacts.
- Non-goals:
  - No mailbox schema or payload changes, producer scheduling changes, runtime wait changes, terminal-finalization changes, Web reducer/state/rendering changes, or compatibility aliases.
  - No raw mailbox persistence payload, provider diagnostics, credentials, or raw External Channel envelope exposure.
- Interfaces:
  - `PendingMailboxEnvelope`: `mailbox_item_id`, `session_id`, mailbox kind, scheduling mode, `created_at`, and ordered pending items.
  - `PendingMailboxItem`: deterministic `id` derived from `(mailbox_item_id, item_key)`, `mailbox_item_id`, stable `item_key`, semantic kind, `state = "pending"`, `created_at`, and a closed source-specific safe presentation union.
  - REST and write snapshots expose `mailbox_items: list[PendingMailboxEnvelope]`; no `input_buffers` or `input_buffer_events` aliases remain.
  - WebSocket upsert action carries one typed envelope; removal carries `session_id` and `mailbox_item_id` only.
  - Action-execution public correlation uses `source_mailbox_item_id`; no public `input_buffer_id` remains.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Typed pending projection, REST/WS contract, action ordering, OpenAPI/client generation, and tests | `/root/mailbox-implementer` | `python/apps/azents/src/azents/{api/public/chat/v1,services/chat,transport,worker/events,worker/live,worker/run}/**`; `python/apps/azents/specs/public/openapi.json`; `python/libs/azents-public-client/**`; `typescript/packages/azents-public-client/**`; Phase 4 plan | Phase 1 mailbox payloads, Phase 3 runtime branch | Typed projections, no-alias public cutover, dedicated actions, correct action handoff order, regenerated clients | Backend/API/transport tests; OpenAPI dump; Python/TypeScript client generation and checks; full relevant quality suite |
| Independent review | `/root/mailbox-reviewer` | Read-only Phase 4 diff and evidence | Implementer validation | Grounded findings and recheck verdict | Projection privacy, no aliases, correlation, action ordering, resync, authorization, generated artifacts, Phase 5 exclusion |

- Integration order:
  1. Define typed service and public projection models from the existing typed mailbox payloads. Every projection must be built from durable mailbox rows; it may not re-read External Channel source records or expose raw persistence JSON.
  2. Replace legacy REST live/write fields and delete-route vocabulary. Preserve existing active-session, workspace membership, and subagent mutation checks.
  3. Add dedicated mailbox WebSocket serializers and publish one envelope only after a newly admitted mailbox item commits. Do not rebroadcast idempotent existing admission.
  4. Split post-commit promotion/handoff publication so message promotion publishes durable history before mailbox removal, while operation Turn Action handoff publishes active `ActionExecution` before mailbox removal.
  5. Remove all public legacy names and generic live-event use for pending mailbox items. Regenerate OpenAPI and both public clients from the schema; never hand-edit generated output.
  6. Compare the final diff against this phase's non-goals before independent review.
- Independent review: `/root/mailbox-reviewer` verifies all-kind projections, no-alias public cutover, stable envelope/item correlation, committed-publish ordering, idempotent retry behavior, action-handoff ordering, authorization/privacy, REST resync, generated artifacts, and the exclusion of Phase 5 rendering.
- Final validation:
  - Focused mailbox projection, chat API, transport, publisher/projector, executor/action-handoff, authorization, and resync tests.
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`.
  - `cd python/libs/azents-public-client && make generate`.
  - `cd typescript && pnpm run generate --filter=@azents/public-client`.
  - Relevant Python and TypeScript format, lint, typecheck/build, generated-artifact determinism, full backend pytest, docs index check, `git diff --check`, and reviewer `CLEAN`.
- Scope-drift check: permit only typed pending projection/public contract/client-generation/action-ordering code and tests. Move Web reducer/rendering, mailbox persistence, producer scheduling, and spec promotion work to their designated later phases.

## Projection Contract

### Durable source and stable identity

`MailboxItem` remains private storage. The service reads its typed immutable envelope payload and projects each embedded `MailboxPresentationItem` without querying producer-owned pending stores. The public envelope ID is the mailbox item ID. An embedded item's public ID is the deterministic concatenation of the envelope ID and item key; it remains stable across REST resync and WebSocket delivery.

The public presentation union is closed and source-specific. It must include safe user-message, Agent-message, Goal-continuation, External-Channel-invocation, and Turn-Action presentations. It must exclude source-domain routing state, authorization data, raw provider envelopes, credentials, and internal diagnostics.

### REST and write responses

Replace `LiveEventListResponse.input_buffers` and `ChatWriteSnapshotResponse.input_buffer_events` with `mailbox_items`. Replace accepted/input identifiers and action-execution references that use `input_buffer` vocabulary. Rename the pending-item delete route to `/chat/v1/sessions/{session_id}/mailbox-items/{mailbox_item_id}`. Remove old routes, field names, models, and aliases in the same cutover.

A REST live or write snapshot reconstructs pending envelopes from PostgreSQL. A mailbox projection remains pending only while its row remains unread. The consumer-facing server contract preserves source-specific ordering and correlation; Phase 5 selects client rendering and applies visual pending emphasis.

### WebSocket publication and ordering

Publish `mailbox_item_upserted` after a new admission commits, with the complete typed envelope. Publish `mailbox_item_removed` only after the durable promotion or action ownership handoff commits. A best-effort publication failure never rolls back durable admission; REST resync reconstructs the pending state.

For message-like promotion, publish every durable `history_event_appended` before `mailbox_item_removed`. For operation Turn Action handoff, publish `action_execution_updated` before `mailbox_item_removed`. Do not use generic live-event actions for either pending mailbox upsert or removal.

### Authorization, resync, and idempotency

Reuse current REST active-session/workspace authorization and WebSocket ticket/session authorization. Preserve subagent read-only mutation restrictions. The server must project the same durable pending state after refresh or reconnect. On server transition and later Phase 5 client reconciliation, durable history or active `ActionExecution` wins over a stale pending projection with the same `(mailbox_item_id, item_key)` correlation.

A successful idempotent retry that returns an existing mailbox item does not publish another upsert. A newly created mailbox item may publish exactly one best-effort upsert after commit.

## Verification Matrix

| Scenario | Required evidence |
| --- | --- |
| Each mailbox kind | REST live and write snapshot contain one typed pending envelope/item with stable correlation and safe presentation. |
| External Channel invocation | REST and WebSocket expose admitted context-plus-trigger items without reading source projections or exposing raw provider data. |
| New admission | One committed typed `mailbox_item_upserted`; idempotent existing retry has no duplicate upsert. |
| Message promotion | Durable history action(s) publish before `mailbox_item_removed`; resync has no pending duplicate. |
| Operation action handoff | `action_execution_updated` publishes before `mailbox_item_removed`; source correlation remains stable. |
| Pending deletion | Mailbox-named delete route retains authorization/read-only behavior and publishes typed removal after commit. |
| Access denial | REST, WebSocket, and mutation authorization behavior remains unchanged; no pending payload leaks. |
| Generated API | OpenAPI and regenerated Python/TypeScript clients expose only mailbox terminology and deterministic output. |

## Risks and prerequisites

- The generated TypeScript public client output is ignored; generation and consuming-package type checks are still required evidence.
- Existing living specs describe `input_buffers`; update them only in the later spec-promotion phase after implementation validation.
- The Phase 4 API contract intentionally precedes Phase 5 UI adoption. Backend/API tests must therefore prove contract and ordering independently of Web rendering.
