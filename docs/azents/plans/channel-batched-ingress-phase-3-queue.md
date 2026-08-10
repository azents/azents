---
title: "Batched External Channel Ingress Phase 3 Queue Plan"
created: 2026-08-10
tags: [external-channel, ingress, queue, cursor, recovery]
---

# Phase Execution Plan

- Phase: `3/4 — Durable conversation ingress batching`
- Branch/base: `feature/channel-batched-ingress-3-queue` →
  `feature/channel-batched-ingress-2-mailbox`
- PR boundary: Replace synchronous normal-message provider history, mailbox admission,
  and per-trigger wake work with content-free durable Session-bound callback admission,
  bounded queue draining, provider resolution, atomic cursor/mailbox finalization,
  retry-tail lifecycle, and producer recovery.
- Inputs: Phase 1 common Job Runtime and AppContext lifecycle; Phase 2 canonical
  single-message mailbox rows, stable FIFO group/sequence ordering, and closed
  `prompt_role = context | invocation` contract; confirmed `channel-260810/REQ`;
  accepted `channel-260810/ADR-D1` and `channel-260810/ADR-D2`; approved
  `channel-260810/DESIGN` revision `1`; current External Channel Provider Ingress,
  Lifecycle, Delivery, Conversation, and mailbox behavior as the pre-change baseline.
- Deliverables: Active ingress-session and content-free ingress-item persistence;
  idempotent DB-only callback admission; one-item first claims and due backlog claims of
  at most ten; Session drain leases and reclaim; typed Slack/Discord exact/history
  policies; same-batch tentative cursor evaluation and final locked CAS; active-trigger
  invocation correlation; atomic successful mailbox subset, cursor, retry-tail, queue,
  drain-state, and Session-runnable transitions; one routing-only wake after each
  non-empty committed batch; bounded retry/failure deletion with sanitized logs; and
  API/Gateway producer recovery scans independent of Redis correctness.
- Non-goals: Active-queue operator CLI/API, metrics dashboards, testenv ingress
  inspection/release endpoints, provider-fake barriers, product E2E journeys, live
  provider verification, Living Spec promotion, implemented snapshot markers, plan
  cleanup, Temporal execution, generic durable job/outbox records, durable wake rows,
  completed ingress outcomes, compatibility readers, or new Deployments.
- Interfaces: Callback admission persists no message body, callback payload,
  credentials, signatures, tokens, private URLs, provider history, terminal reason, or
  completed tombstone. One active drain row owns immutable Session identity and a
  conditional lease. Ingress items retain immutable admission identity and mutable
  monotonic queue order; retries preserve item identity and original age while moving to
  the tail. Provider content remains task-local until one final transaction validates
  ownership and cursor snapshots, creates deterministic single-message mailbox rows,
  advances only successful cursors, applies retry/deletion transitions, and marks the
  Session runnable. Existing pending-mailbox state remains wake-recovery authority.
- Approved Design mechanisms: `M1`, `M4`, `M5`, `M6`, `M8`, `M11`
- Authority references: `channel-260810/REQ-1` through `REQ-8` as traced by approved
  Design sections Ingress Persistence, Callback Admission, Session Drain and Batch
  Formation, Provider Resolution and Cursor Semantics, Atomic Mailbox Admission and
  Wake, Retry/Bounded Failure/Recovery, and Security and Permission Boundaries;
  `channel-260810/ADR-D1`; Phase 2 `M7`/`M10` mailbox interfaces; and
  `ingress-260801/ADR-D1` for existing mailbox wake recovery authority.
- Design delta: `None`
- Removal obligations: Normal conversation provider history and mailbox work inside
  Slack/Discord callback deadlines; callback failure poisoning later delivered Discord
  message admission; normal-message Redis conversation-lock correctness dependency;
  immediate per-trigger mailbox wake; and any retained completed ingress outcome or
  tombstone.
- Absence verification: Callback tests prove acknowledgement after DB insertion and
  before provider exact/history calls; static call-path checks find no normal callback
  invocation of provider history or canonical mailbox admission; Redis-unavailable
  repository/service tests preserve queue correctness; wake tests assert one attempt per
  non-empty processing batch; schema/repository searches find active states only and no
  completed outcome authority.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Durable ingress schema and repository | `/root` | `python/apps/azents/src/azents/rdb/models/**`, `azents/repos/external_channel/**`, `db-schemas/rdb/**` | final Phase 2 revision and mailbox schema | active drain/item models, constraints, idempotent admission, ordered claim/reclaim/tail/finalization primitives, forward migration | repository/model pytest, PostgreSQL migration integration, Ruff, ty |
| DB-only callback admission and Runtime submission | `/root` | `azents/services/external_channel/transport_ingestion.py`, `ingestion.py`, `mailbox_ingestion_store.py`, Slack/Discord callback adapters and focused tests | repository admission and Job Runtime request contract | immutable Session-bound trigger commit, immediate acknowledgement, best-effort active-drain-lifecycle execution-key submission, independent callback attempts | admission/callback barrier tests, lifecycle recreation and coalescing tests |
| Provider policy and prepared outcomes | `/root` | `azents/services/external_channel/{slack_*,discord_*,ingestion_history.py}` plus new ingress policy modules/tests | typed content-free locator | exact/history policy registry, safe retry classification, task-memory canonical projections, admitted-trigger correlation inputs | provider policy exact/history, identity, rate-limit, attachment, and safe-error tests |
| Session drain, cursor CAS, and atomic mailbox finalization | `/root` | new External Channel drain/finalization services, mailbox ingestion integration, conversation-position repository methods and tests | claims, policies, Phase 2 mailbox contract | first-one/later-ten loop, tentative cursor map, deterministic locks, bounded coordination retry, atomic successful subset, group/sequence ordering, one post-commit wake | batch/cursor/correlation/rollback/wake integration tests |
| Retry, bounded failure, and recovery | `/root` | ingress repository/service recovery modules, `app.py`, gateway runtime/CLI lifecycle and tests | active queue and Job Runtime | five-attempt/five-minute budget, bounded delays and Retry-After, queue-tail movement, sanitized failure log, expired/unowned Session scans in API/Gateway producers | retry age/attempt/tail tests, recovery/resubmission tests, Redis-independent tests, log redaction assertions |
| Independent review | `/root/channel-ingress-reviewer` | read-only phase plan and complete diff | stable implementation and focused evidence | authority, transaction/data-loss, retry, security/redaction, lifecycle, removal, and scope report | written PASS or concrete material findings |

- Integration order: Add tracked plan and current-flow inventory → install active
  ingress schema/repository and migration → register the Session drain Job Runtime
  handler → split callback admission before provider I/O → adapt typed provider policies
  to claimed items → implement sequential preparation and final cursor/mailbox
  transaction → add retry-tail, bounded failure, post-commit wake, and producer recovery
  → remove synchronous normal-message paths → run focused validation and absence checks
  → independent review → corrections and final phase validation.
- Independent review: `/root/channel-ingress-reviewer` reviews read-only against the
  confirmed Requirements, accepted ADRs, approved Design revision `1` mechanisms `M1`,
  `M4`, `M5`, `M6`, `M8`, and `M11`, current Specs, Phase 1/2 interfaces, this plan, and
  the stable diff. It reports only material authority/scope drift, callback security or
  permission changes, persisted-content leakage, queue/cursor/mailbox data loss,
  transaction or lease races, retry/recovery correctness failures, unsafe logs, removal
  omissions, compatibility fallbacks, and unauthorized durable authority.
- Final validation: Affected Python Ruff and formatter checks; Azents
  `uv run ty check --error-on-warning`; focused repository, callback admission, Runtime
  submission, provider policy, drain/claim, cursor/correlation, mailbox finalization,
  retry/failure, wake, recovery, and migration pytest modules; full Azents Python suite
  on the stable diff; migration revision/head validation; generated contract checks only
  if public schemas change; static content-free/legacy synchronous-path/completed-state
  absence searches; Redis-independent focused tests; log-redaction assertions; docs
  hooks during commit; and `git diff --check`.
- Scope-drift check: Confirm every Phase 3 behavior required by `M1`, `M4`, `M5`, `M6`,
  `M8`, and `M11` is present and consumes the final `M7`/`M10` interfaces without
  changing them. Confirm no operator/testenv/E2E/Spec promotion from Phase 4, provider
  policy product change, setup/interactive rerouting, raw callback persistence,
  generic durable job/outbox, durable wake state, completed outcome, Temporal path,
  per-handler backend selection, new Deployment, Redis authority, or compatibility
  reader is added.
- Context checkpoint: Phase starts from normalized Phase 2 commit `1c05cab17` after PR
  `#1233` was squash-merged and PR `#1234` was retargeted to `main`. Phase 2 remains
  current synchronous behavior with final canonical mailbox/prompt-role contracts.
  Completion leaves normal Session-bound Slack/Discord messages durably admitted and
  drained through PostgreSQL plus the Local Job Runtime, with deterministic lower-level
  evidence and independent review. Phase 4 begins only after the `[3/4]` PR is open.
- Completion checkpoint (2026-08-10): Implemented the assigned mechanisms with
  `Design delta: None`; content-free and Phase 4 absence searches are clean; Alembic
  revision/head is `b53dacd10814`; Ruff format/check and ty pass; the External Channel
  service/repository regression set passes 578 tests, migration coverage passes 13
  tests, and the complete Azents Python suite passes 4,068 tests;
  `/root/channel-ingress-reviewer` returned PASS after the connection-before-drain
  lock-order correction and the active-drain-lifecycle execution-key race correction.
