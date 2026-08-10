---
title: "Batched External Channel Ingress Phase 2 Mailbox Plan"
created: 2026-08-10
tags: [mailbox, external-channel, migration, engine]
---

# Phase Execution Plan

- Phase: `2/4 — Canonical mailbox and prompt-role contract`
- Branch/base: `feature/channel-batched-ingress-2-mailbox` →
  `feature/channel-batched-ingress-1-runtime`
- PR boundary: Introduce stable mailbox group/sequence ordering, replace the batched
  External Channel mailbox envelope with one provider message per row, migrate the
  complete persisted/runtime presentation contract to `prompt_role`, and transform
  existing pending mailbox and durable Event data transactionally.
- Inputs: Phase 1 commit `b5df6e43d`; confirmed `channel-260810/REQ`; accepted
  `channel-260810/ADR-D1` and `channel-260810/ADR-D2`; approved
  `channel-260810/DESIGN` revision `1`; current Conversation, External Channel, Provider
  Ingress, and Delivery Living Specs as the pre-change behavior baseline.
- Deliverables: Explicit mailbox `order_group` and `order_sequence` schema and FIFO
  repository ordering; a closed single-message External Channel mailbox payload and
  one-row promotion path; canonical `prompt_role = context | invocation` across
  mailbox, Event, engine rendering/lowering, chat presentation, API schemas, generated
  clients, fixtures, and tests; one generated forward migration that backfills FIFO
  fields, splits pending legacy envelopes in place, rewrites durable JSON, renames the
  persisted mailbox kind, and validates legacy-contract absence.
- Non-goals: Durable External Channel ingress Session/item tables, DB-only callback
  admission, first-one/later-ten drain behavior, provider-policy exact/history changes,
  active-trigger correlation, cursor finalization, retry-tail behavior, batch-level wake
  activation, recovery scans, queue diagnostics, testenv ingress inspection, product
  E2E journeys, Living Spec promotion, or temporary-plan cleanup.
- Interfaces: Every mailbox row has non-null stable `order_group` and
  `order_sequence`; FIFO selection and locking order by group, sequence, then ID;
  ordinary enqueue assigns its own row ID as group and sequence zero; one synchronous
  External Channel admission may enqueue several single-message rows in provider order
  while retaining one invocation-level idempotency boundary and current wake behavior;
  the External Channel mailbox kind and payload describe exactly one
  `ExternalChannelMessagePayload`; persisted and public message contracts expose only
  `prompt_role` with closed values `context` and `invocation`; prompt text uses
  `Prompt role:`; no compatibility reader or alias accepts the legacy contract after
  migration.
- Approved Design mechanisms: `M7`, `M10`
- Authority references: `channel-260810/REQ-4`, `channel-260810/REQ-5`,
  `channel-260810/DESIGN` sections Independent Mailbox Rows, Stable FIFO Ordering,
  Prompt Role and Presentation Contract, Database Migration, and Removal and
  Replacement; `ingress-260801/ADR-D1` for existing mailbox wake recovery authority.
- Design delta: `None`
- Removal obligations: Multi-message
  `ExternalChannelInvocationMailboxPayload`; persisted/runtime mailbox kind whose name
  describes an invocation batch; `authorization`, `context_only`,
  `authorized_invocation`, and human-readable `Authorization:` throughout affected
  source, generated contracts, fixtures, tests, pending mailbox JSON, and durable Event
  JSON.
- Absence verification: Static searches exclude the removed payload type, kind, field,
  enum values, and prompt label from affected source/generated/fixture trees; migration
  integration assertions prove no pending legacy External Channel envelope and no old
  key/value remains in transformed mailbox/Event rows; payload and repository tests
  prove one provider message per row and group/sequence/ID FIFO ordering.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Mailbox schema and repository ordering | `/root` | `python/apps/azents/src/azents/rdb/models/mailbox_item.py`, `python/apps/azents/src/azents/repos/mailbox/**`, mailbox services and focused tests | approved `M7` FIFO contract | non-null group/sequence fields, ordinary enqueue defaults, deterministic reads and locks | model/repository/service pytest, Ruff, ty |
| Single-message External Channel admission and promotion | `/root` | `python/apps/azents/src/azents/services/external_channel/**`, `azents/services/mailbox.py`, `azents/worker/session/**`, related core payloads and tests | mailbox ordering interface | one row per canonical provider message, one-row promotion, preserved synchronous ingress and wake recovery | payload, ingestion-store, promotion, pending/live/history tests |
| Prompt-role runtime and presentation contract | `/root` | `python/apps/azents/src/azents/core/**`, `azents/engine/**`, `azents/services/chat/**`, `azents/services/session_title.py`, public API models/routes and focused tests | single-message payload | closed `prompt_role` enum/field, rendering/lowering/accounting/title semantics, public projections | engine, projection, title, API-schema tests and static absence checks |
| Forward data migration | `/root` | `python/apps/azents/db-schemas/rdb/migrations/versions/**`, `python/apps/azents/db-schemas/rdb/revision`, migration tests | final schema and canonical payload definitions | generated linear transactional revision, FIFO backfill, pending row split, Event/mailbox JSON rewrite, kind rename, fail-closed validation | revision-chain and PostgreSQL migration integration tests |
| Generated contracts and fixtures | `/root` | `python/apps/azents/specs/**`, `python/libs/azents-public-client/**`, `typescript/packages/azents-public-client/**`, affected application/testenv fixtures and tests | public canonical schemas | regenerated Python/TypeScript contract artifacts with only canonical names | OpenAPI generation checks, generated diff checks, focused TypeScript validation as affected |
| Independent review | `/root/channel-ingress-reviewer` | read-only phase diff | stable implementation and focused evidence | authority, migration data-preservation, interface, generated-contract, and scope report | written review findings |

- Integration order: Record current contract inventory → add mailbox schema/repository
  ordering → replace the External Channel payload/kind and promotion path → propagate
  `prompt_role` through runtime and presentation → generate and implement the forward
  migration → regenerate public contracts → update fixtures/tests → run focused
  validation → independent review → corrections → final validation.
- Independent review: `/root/channel-ingress-reviewer` reviews read-only against the
  confirmed Requirements, accepted ADRs, approved Design revision `1` mechanisms `M7`
  and `M10`, current Specs, this plan, and the stable diff. It reports only material
  authority/scope drift, migration data loss or ordering failures, persistence/runtime
  contract mismatch, generated-contract omissions, and security or correctness
  findings.
- Final validation: Affected Python Ruff and formatter checks; Azents
  `uv run ty check --error-on-warning`; focused mailbox, External Channel ingestion,
  promotion, engine rendering/lowering, chat projection, title, API, and migration
  pytest modules; OpenAPI dump/client regeneration checks; affected TypeScript format,
  lint, typecheck, and build checks when generated or application TypeScript changes;
  docs snapshot validation; static legacy-name and batch-payload absence searches;
  `git diff --check`.
- Scope-drift check: Confirm all Phase 2 mailbox/FIFO and canonical prompt-role behavior
  required by `M7`/`M10` is present and the forward migration preserves historical Event
  content and pending mailbox input. Confirm the diff adds no ingress queue/drain state,
  callback behavior, provider-policy/correlation mechanism, retry lifecycle, cursor CAS,
  new wake mode, compatibility reader, new backend mode, Living Spec promotion, or
  Phase 3/4 diagnostics and E2E surface.
- Context checkpoint: Phase starts from Phase 1 commit `b5df6e43d` and PR `#1233` with
  stable Job Runtime/AppContext/Scheduler interfaces. Completion must leave current
  synchronous ingress functional through the final one-message mailbox contract,
  record focused validation and independent review evidence, and open a stacked `[2/4]`
  PR targeting `feature/channel-batched-ingress-1-runtime`. Phase 3 begins only after
  that PR exists.
