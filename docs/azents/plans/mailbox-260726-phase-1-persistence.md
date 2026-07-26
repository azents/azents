---
title: "Unified Agent Input Mailbox Phase 1: Persistence Foundation"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, backend, database, migration, plan]
---

# Unified Agent Input Mailbox Phase 1: Persistence Foundation

## Phase Execution Plan

- Phase: `1 — Mailbox persistence foundation and internal data-shape cutover`
- Branch/base: `feature/mailbox-260726-persistence` → `feature/mailbox-260726-plan`
- PR boundary: Rename and evolve the current InputBuffer persistence into the canonical typed mailbox, migrate all existing rows, and move every internal producer and processor to the final mailbox data contract without changing scheduling or public wire behavior.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md), and [the multi-phase implementation plan](mailbox-260726-implementation-plan.md).
- Deliverables:
  - `mailbox_items` is the only unread AgentSession input table and preserves existing IDs, FIFO order, scheduling mode, and idempotency identity.
  - Internal ORM, enums, domain data, repositories, services, producer calls, preparation processors, replay helpers, action source identities, terminal delivery markers, and External Channel references use mailbox vocabulary without aliases.
  - Every current producer writes the final closed typed payload, and every current preparation processor reads that payload.
  - External Channel admission stores one complete ordered immutable context-plus-trigger snapshot; promotion no longer reconstructs Agent input from mutable source projections.
  - One generated Alembic revision upgrades every current mailbox kind, renames dependent schema objects, validates/backfills typed payloads, and aborts before destructive changes when any row is not convertible.
  - Existing public REST/OpenAPI field names remain temporarily serialized from mailbox-domain values so generated clients continue to compile until the coordinated Phase 4 public contract cutover.
- Non-goals:
  - Do not change which producers perform full Session wakeup or queue-only admission.
  - Do not implement live-owner-only activity, the Run-scoped observer, or `WaitToolkit`.
  - Do not make terminal finalization and parent delivery atomic; Phase 2 owns that transaction boundary.
  - Do not rename public REST paths, response fields, accepted type values, WebSocket actions, generated clients, or Web state.
  - Do not add compatibility storage, dual-read, dual-write, InputBuffer type aliases, or a parallel mailbox table.
  - Do not modify any executed migration revision.
- Interfaces:
  - ORM/table: `RDBMailboxItem` over `mailbox_items`.
  - Enums: mailbox item kind and scheduling mode replace `InputBufferKind` and `InputBufferSchedulingMode` internally while preserving stored semantic values unless the generated migration deliberately renames the PostgreSQL enum types.
  - Domain/service: mailbox item, admission/enqueue, preparation result, and passive mailbox service contracts replace all `InputBuffer*` contracts.
  - Payload: a closed discriminated union with final variants for user message, Goal continuation, Agent message, External Channel invocation, and Turn Action. Every envelope owns an ordered non-empty `items` collection with stable item keys.
  - Source identity: action execution and terminal delivery use mailbox item IDs under mailbox-named fields; External Channel invocation batches retain a nullable mailbox item FK with `SET NULL` deletion behavior.
  - Persistence boundary: enqueue, list/peek/claim, level check, prepare/handoff, and delete operations have no broker, Session-state, notification, or live-publication side effects.
  - Public compatibility boundary: API serializers may map new domain fields to existing InputBuffer JSON names only inside the public API layer until Phase 4; internal code must not import or expose compatibility aliases.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence and internal cutover | `/root/mailbox-implementer` | `python/apps/azents/db-schemas/rdb/**`; `python/apps/azents/src/azents/rdb/models/input_buffer.py` or its mailbox replacement; `core/enums.py`; `repos/input_buffer/**` or mailbox replacement; `services/input_buffer.py` or mailbox replacement; all backend callers under `services/agent_session_input.py`, `services/chat_write.py`, `services/chat/**`, `services/agent_mailbox.py`, `services/action_execution.py`, `services/external_channel/**`, `repos/action_execution/**`, `repos/session_execution/**`, `worker/session/**`, `worker/deps.py`, `engine/tools/subagent.py`; affected backend tests and migration fixtures | Approved snapshot and multi-phase plan | Generated schema migration, mailbox model/repository/service/payload contracts, all internal caller/processor cutover, External Channel immutable snapshot, tests | Focused migration/repository/service/producer/processor tests, full backend Ruff/format/Pyright/pytest, docs validation |
| Independent review | `/root/mailbox-reviewer` | Read-only review of the complete Phase 1 diff and test evidence | Implementation owner validation | Findings classified as Critical, Warning, Suggestion, or Consistency; recheck after fixes | Requirements/ADR/Design/phase-plan traceability, migration safety, no-alias scan, test evidence |

- Integration order:
  1. Inventory every remaining `InputBuffer`, table, enum, column, FK, index, constraint, repository, service, public serializer, and migration reference. Record intentional historical migration references separately from active runtime references.
  2. Define the final mailbox domain names and closed payload union, including stable item-key derivation and External Channel snapshot fields.
  3. Update ORM models and generate one new Alembic revision through the repository command; update `db-schemas/rdb/revision` from current head `cc31dfa97a1b`.
  4. Rename repository/service contracts and update every internal caller. Do not add aliases to keep stale imports compiling.
  5. Move every current producer to final typed payload construction while preserving its existing scheduling mode and post-commit wake behavior.
  6. Move every preparation processor and action handoff to typed payload consumption. External Channel promotion must use only the mailbox payload.
  7. Adapt the public API serialization layer to keep current wire names temporarily without leaking old vocabulary back into domain code.
  8. Complete migration preflight, typed backfill, dependent FK/index/constraint recreation, non-null enforcement, and destructive legacy-column removal in an order that keeps dependent rows valid.
  9. Add and run migration, payload, FIFO, idempotency, locking, stale-head, retry, promotion, External Channel mutation, action handoff, and public serialization regression tests.
  10. Run the implementation-owner validation suite, request review from `/root/mailbox-reviewer`, apply findings, rerun affected checks, and request reviewer recheck.
- Independent review: `/root/mailbox-reviewer` reviews the complete Phase 1 diff read-only. Critical criteria are data loss, invalid rollback/upgrade ordering, incomplete typed backfill, any runtime InputBuffer alias/dual-read/dual-write, producer or processor left on removed columns, External Channel promotion source reread, broken FK `SET NULL`, changed FIFO/idempotency/locking semantics, public wire drift before Phase 4, or an edited historical migration. Warnings include incomplete vocabulary cleanup, insufficient malformed-row coverage, non-exhaustive payload matching, missing generated revision head update, or missing regression coverage. The implementation owner applies findings and requests recheck before root verification.
- Final validation:

  ```bash
  cd python/apps/azents
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright .
  uv run pytest -q \
    src/azents/repos/input_buffer \
    src/azents/services/input_buffer_test.py \
    src/azents/services/chat/input_buffer_test.py \
    src/azents/services/chat/live_events_test.py \
    src/azents/services/agent_mailbox_test.py
  uv run pytest -vv

  cd ../../..
  python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
  ```

  The implementation owner may correct exact targeted test paths after repository inspection, but must record the replacement in this plan before treating the command as skipped or satisfied. Run migration upgrade tests against a pre-feature fixture containing all five kinds, a valid pending External Channel batch, and an invalid/unresolvable pending row.
- Scope-drift check: Compare `git diff --stat` and `git diff <base>...HEAD` with the deliverables and non-goals above. Reject runtime activity, Wait Toolkit, terminal transaction, public API rename, generated client, Web, spec-promotion, and unrelated refactor changes from this branch. Scan active source for stale `InputBuffer` runtime vocabulary; allow only intentional public serialization compatibility until Phase 4 and historical executed migration references. Confirm the diff contains exactly one new migration revision and the updated revision-head file.

## Migration Contract

The generated revision must use current head `cc31dfa97a1b` and preserve these active dependencies:

| Current dependency | Required final state |
| --- | --- |
| `input_buffers` table and FIFO indexes | `mailbox_items` with preserved primary keys and Session FIFO ordering |
| `external_channel_invocation_batches.input_buffer_id` FK | mailbox-named nullable FK with `ON DELETE SET NULL` |
| `action_executions.input_buffer_id` unique/index source identity | mailbox-named non-FK source identity with equivalent uniqueness and lookup behavior |
| `agent_runs.parent_result_input_buffer_id` delivery marker | mailbox-named nullable source identity preserving existing values |
| `input_buffer_kind` and scheduling PostgreSQL enums | deliberately retained or renamed by generated operations while preserving all current values |
| generic content/metadata/action/attachment/FilePart columns | fully backfilled typed payload, then removed only after validation |

The migration sequence must:

1. rename the table and active dependent columns/schema objects while preserving IDs;
2. add the typed payload in a transitional nullable state;
3. validate and materialize one final payload for every existing row;
4. construct complete External Channel message snapshots from intact admitted batch records;
5. fail before non-null enforcement or legacy-column removal when any row is malformed or unresolvable;
6. recreate dependent constraints and indexes with mailbox names and equivalent semantics;
7. make the payload non-null; and
8. remove superseded generic columns only after all conversion checks pass.

## Typed Payload Contract

Every envelope contains a discriminated payload and a non-empty ordered presentation-item list. Item keys are assigned at admission and survive pending projection, durable event creation, and action handoff correlation.

Minimum variant responsibilities:

- User message: safe content, attachments/FileParts, sender provenance, requested inference intent, and stable presentation item key.
- Goal continuation: continuation content, Goal identity/provenance required by current processing, requested inference intent, and stable item key.
- Agent message: source SessionAgent identity, task/result semantics, safe content, terminal metadata when present, and stable item key.
- External Channel invocation: complete ordered context-plus-trigger `ExternalChannelMessagePayload` snapshots, including provider/resource/message/revision/sender/body/attachment/reference/lifecycle/timestamp/URL/truncation/correction fields required by current event construction.
- Turn Action: typed Goal, Skill, or operation action plus user-authored presentation data, attachments/FileParts, requested inference intent, and stable item key.

Consumers use exhaustive matching. Unknown variants or invalid payloads fail visibly and leave the mailbox row unread.

## Test Matrix

| Area | Required evidence |
| --- | --- |
| Upgrade | One pre-feature row per current kind upgrades with identical ID, Session order, scheduling mode, and idempotency identity. |
| Invalid upgrade | Malformed typed source data or missing External Channel batch projection aborts before destructive changes. |
| FK/source identity | External batch nullable `SET NULL`, action execution source lookup, and Agent Run parent-result marker survive upgrade. |
| FIFO and locking | Head selection, row locking, changed-head restart, and concurrent enqueue behavior remain equivalent. |
| Idempotency | Producer retry returns the existing mailbox item and does not duplicate payload items. |
| Retry safety | Failed promotion or action handoff leaves the mailbox item available. |
| External Channel | Admission captures complete ordered snapshot; source mutation/removal after admission does not change promotion output. |
| Action handoff | Operation action execution creation and mailbox deletion remain atomic. |
| Public compatibility | Existing Phase 1 REST/OpenAPI fields and route behavior serialize from mailbox-domain values without internal aliases. |
| Vocabulary | Active runtime source contains mailbox terminology; old names remain only in executed migrations, historical docs, and temporary public serialization keys explicitly allowed by this plan. |
