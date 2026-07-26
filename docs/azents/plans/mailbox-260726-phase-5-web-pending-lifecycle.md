---
title: "Unified Agent Input Mailbox Phase 5: Web Pending Lifecycle"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, web, chat, lifecycle, plan]
---

# Mailbox Phase 5: Web Pending Lifecycle

## Phase Execution Plan

- Phase: `5 — Web pending lifecycle`
- Branch/base: `feature/mailbox-260726-web-lifecycle` → `feature/mailbox-260726-pending-api`
- PR boundary: Replace the Phase 4 local pending-input adapter with native typed mailbox envelope/item state and source-specific pending timeline presentation. Preserve the fixed server contract, public clients, and current chat resync/authorization behavior.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md), the [multi-phase implementation plan](mailbox-260726-implementation-plan.md), and completed [Phase 4 execution plan](mailbox-260726-phase-4-pending-projection-api.md).
- Deliverables:
  - Native ordered pending mailbox envelope/item state keyed by `(mailbox_item_id, item_key)`.
  - REST baseline and `mailbox_item_upserted`/`mailbox_item_removed` reducers that are idempotent under duplicate or reordered observations.
  - Source-specific pending presentation for user messages, Agent messages, Goal continuations, External Channel items, and Turn Actions with shared pending emphasis.
  - Correlation-based suppression so durable history and active or durable ActionExecution ownership win over stale pending state.
  - Existing delete mutation, resync, latest-following, detached-history, authorization, and subagent read-only behavior preserved.
  - Deterministic reducer/selector and presentation coverage, plus documented
    refresh/reconnect, compound External Channel, and action-handoff fixture
    prerequisites for the later integrated Validation phase.
- Non-goals:
  - No API, OpenAPI, generated client, mailbox schema/payload, producer scheduling, runtime wait, terminal-finalization, or server publication-order changes.
  - No public or local fallback to the removed Event-shaped pending API or `PendingInputBuffer` adapter.
  - No new user mutation authority, provider/source-record lookup, raw External Channel payload exposure, or visual redesign outside pending mailbox lifecycle.
- Interfaces:
  - Native pending identity is `mailbox_item_id:item_key`; envelope order follows mailbox FIFO/creation order and item order follows the server envelope order.
  - A REST live snapshot is authoritative for pending envelopes only when the existing resync epoch and observation-generation gate accepts it.
  - `mailbox_item_upserted` replaces one envelope idempotently; `mailbox_item_removed` removes only that envelope; durable/action correlation removes or suppresses only matching item keys.
  - Common pending emphasis is opacity `0.6`; a pending deletion in flight is opacity `0.45`. Server `pending` and client optimistic `sending` remain distinct states.
  - Pending renderers consume only the safe typed presentation union. They never rebuild inputs from raw metadata or producer-owned records.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Native pending state, reducers, renderer integration, tests, and E2E fixture support | `/root/mailbox-implementer` | `typescript/apps/azents-web/src/features/chat/{containers,useChatWebSocket.ts,types.ts,components,story-fixtures.ts,**/*test*.*,**/*.stories.tsx}`; necessary `testenv/azents/e2e/**` fixture/test paths; Phase 5 plan | Phase 4 typed API/client contract | Native typed state, renderer selection, correlation/reconciliation, tests and fixture prerequisites | TypeScript format/lint/typecheck/build, deterministic reducer/story tests, targeted E2E/testenv checks |
| Independent review | `/root/mailbox-reviewer` | Read-only Phase 5 diff and evidence | Implementer validation | Grounded findings and recheck verdict | Native identity, source mapping, opacity, resync/detached behavior, action/durable precedence, mutation constraints, Phase 5 scope |

- Integration order:
  1. Introduce native typed pending state and pure selectors/reducer helpers. Define one common correlation extractor for durable history payloads and action-execution source mailbox IDs.
  2. Replace the Phase 4 envelope-flattening adapter in REST baseline and mailbox WebSocket handling. Preserve the existing health-check, epoch, generation, and buffered-replay flow.
  3. Apply durable-history and ActionExecution correlation suppression before source rendering, including duplicate and reordered observations.
  4. Replace generic pending-buffer timeline rendering with source-specific pending renderer selection inside the existing latest-following live tail. Use the existing source visual families and shared pending frame; do not flatten to generic bubbles.
  5. Preserve detached-history behavior: mailbox/live actions do not mutate detached visible state, while durable history alone marks newer availability.
  6. Preserve delete permissions and rollback/resync behavior; visibility never grants mutation authority.
  7. Add deterministic reducer/selector, renderer, story, and E2E fixture evidence. Compare the final diff against non-goals before review.
- Independent review: `/root/mailbox-reviewer` verifies native state replaces the adapter, all five source renderers use safe typed inputs, stable correlation/deduplication, durable/action precedence, REST/WS resync, detached mode, pending emphasis, delete/read-only behavior, and no server/API/client drift.
- Final validation:
  - TypeScript format, lint, typecheck, and build for the full workspace.
  - Deterministic native-state reducer/selector and renderer tests for every mailbox kind, compound External Channel ordering, duplicate/reordered WebSocket frames, stale REST baseline rejection, durable-first promotion, action handoff, detached history, and delete rollback.
  - Record the deterministic testenv/E2E fixture prerequisites for the later
    Validation phase; that phase executes refresh/reconnect, pending promotion,
    compound External Channel, and Turn Action handoff coverage without live
    provider credentials.
  - Relevant backend contract tests unchanged or rerun as integration evidence, docs index check, `git diff --check`, and reviewer `CLEAN`.
- Scope-drift check: permit only native Web pending lifecycle, corresponding tests/fixtures, and this plan. Move server/API/client changes, persistence, runtime behavior, general chat redesign, spec promotion, and unrelated E2E work to their designated phases.

## Native State and Correlation

The native state stores envelopes in server FIFO order and items in each envelope's server order. It must retain envelope metadata and typed item presentation without converting an item into a legacy `ChatEventResponse` or `PendingInputBuffer`.

A durable event correlation extractor reads the mailbox envelope ID and item key stored by Phase 1 promotion. An ActionExecution correlation extractor reads `source_mailbox_item_id`; current operation action envelopes contain one item, so action ownership suppresses that envelope's pending item before or when its removal frame arrives. A durable action result remains authoritative over any delayed live action or pending frame.

Duplicate upserts replace the same envelope without reordering unrelated envelopes. Removal is idempotent. A delayed upsert must not resurrect an item already suppressed by matching durable history or ActionExecution ownership. A fresh accepted REST baseline replaces pending state atomically, then buffered valid WebSocket observations replay using the same rules.

## Pending Presentation

All pending items are rendered only in `LATEST_FOLLOWING`, after live ActionExecution content and before the composer, matching the current live-tail placement.

- **User message:** reuse the user-message visual family within the common pending frame.
- **Agent message:** reuse the collapsed, source-labeled internal Agent-message family; never render it as a human user bubble.
- **Goal continuation:** reuse the continuation/control presentation.
- **External Channel item:** render from the safe pending presentation union with a pending-specific adapter/defaults where the durable renderer expects unavailable provider metadata. Do not query source records or expose new data.
- **Turn Action:** reuse action/control visual treatment while pending; active ActionExecution takes precedence after handoff.

The common pending frame applies opacity `0.6`; deletion in progress uses `0.45`. The frame does not change semantic layout, source label, metadata safety, or available mutation controls. Optimistic client submission remains distinct from durable server-pending mailbox state.

## Resync, Detached History, and Mutation

The existing subscription-health barrier, buffered WebSocket replay, request epoch, and live-observation generation rules remain authoritative. Typed pending state participates in the same accepted-baseline replacement and replay flow.

In `DETACHED_HISTORY_BROWSING`, mailbox and other live actions are ignored for the detached visible timeline. Durable history append may mark `hasNewer`, but pending state is not rendered or advanced until a latest baseline is restored.

The mailbox delete operation keeps existing session authorization, mutable-kind limits, subagent read-only restrictions, failure rollback, and resync behavior. A pending item being visible does not imply it is deletable.

## Verification Matrix

| Scenario | Required evidence |
| --- | --- |
| All five mailbox kinds | Native state and source-specific pending renderer use only typed safe presentation and shared pending emphasis. |
| Compound External Channel envelope | Envelope FIFO and item order remain contiguous; each `(mailbox_item_id,item_key)` is stable across baseline and WebSocket replay. |
| Duplicate/reordered observations | Upsert/removal/durable/action reducers are idempotent and never resurrect suppressed pending items. |
| Message promotion | Durable history wins before pending removal; delayed removal is harmless. |
| Operation handoff | Active ActionExecution wins before pending removal; durable result later wins over delayed live state. |
| Refresh/reconnect | Accepted REST baseline plus buffered replay converges after missed mailbox WebSocket actions. |
| Detached history | Live mailbox state remains hidden/unchanged; only durable history sets newer availability. |
| Delete mutation | Allowed deletion dims only the matching pending item; failure restores/resyncs without affecting unrelated items. |
| Authorization | Subagent read-only and existing session access controls remain unchanged. |

## Risks and prerequisites

- Existing External Channel durable renderer expects metadata not present in the safe pending union. The pending-specific adapter must use safe defaults/omission, not source lookups or server contract expansion.
- Current Web coverage is story-oriented; Phase 5 must add deterministic reducer/selector test coverage before E2E validation.
- The later Validation phase must execute deterministic provider-independent
  External Channel snapshots and operation action handoff; live provider
  credentials are not required.
