---
title: "Batched External Channel Ingress Implementation Plan"
created: 2026-08-10
tags: [external-channel, runtime, mailbox, migration, testenv]
---

# Batched External Channel Ingress Implementation Plan

- Requirements: [`channel-260810/REQ`](../requirements/channel-260810-batched-conversation-ingress.md)
- Decisions: [`channel-260810/ADR`](../adr/channel-260810-batched-conversation-ingress.md)
- Approved Design: [`channel-260810/DESIGN`](../design/channel-260810-batched-conversation-ingress.md)
- Approved Design revision: `1`
- Approved mechanism IDs: `M1` through `M12`
- Design delta: `None`
- Implementation owner: Primary agent (`/root`)
- Independent reviewer: `channel-ingress-reviewer` (`/root/channel-ingress-reviewer`)

## Delivery Shape

The feature ships as four stacked PRs. Each PR remains reviewable and passes its focused
checks before the next branch is created. All four PRs are created before stack-wide CI
monitoring begins.

| Phase | Branch | Base | PR title | Approved mechanisms | Primary boundary |
| --- | --- | --- | --- | --- | --- |
| 1 | `feature/channel-batched-ingress-1-runtime` | `origin/main` | `Batched channel ingress [1/4]: Add the common job runtime` | `M2`, `M3`, `M9` | AppContext-owned Local Job Runtime, global backend selection, Scheduler integration, shared devserver lifecycle |
| 2 | `feature/channel-batched-ingress-2-mailbox` | Phase 1 | `Batched channel ingress [2/4]: Migrate external channel mailbox messages` | `M7`, `M10` | single-message mailbox payloads, stable FIFO ordering, prompt-role migration, generated contracts |
| 3 | `feature/channel-batched-ingress-3-queue` | Phase 2 | `Batched channel ingress [3/4]: Add durable conversation ingress batching` | `M1`, `M4`, `M5`, `M6`, `M8`, `M11` | durable callback admission, Session queue/drain, provider policies, cursor CAS, retries, wake/recovery |
| 4 | `feature/channel-batched-ingress-4-validation` | Phase 3 | `Batched channel ingress [4/4]: Validate and document batched ingress` | `M12` plus full `M1`–`M12` validation | diagnostics, testenv/E2E, rollout verification, Living Spec promotion, snapshot implementation dates, plan cleanup |

## Fixed Interfaces and Integration Boundaries

- PostgreSQL domain tables remain the only durable ingress correctness authority.
- The Job Runtime owns bounded local execution only; it owns no durable generic queue,
  retry schedule, attempt history, or cross-process dispatch.
- One configured backend applies to every registered handler. `local` is implemented;
  `temporal` is reserved and fails startup until a later approved snapshot implements it.
- Job handlers receive typed JSON-safe requests, stable execution keys, absolute
  deadlines, and task-local DI containers rooted in the process AppContext.
- Scheduler requests serialize only task key, claim timestamp, lease owner, and manual
  trigger state. The Runtime handler reconstructs `TaskContext` with its task-local
  container; a `di.Container` never enters the request payload.
- Scheduler execution keys identify one database claim rather than one task definition,
  so a later lease-reclaimed attempt cannot coalesce with an earlier claim.
- Registered handlers must propagate `asyncio.CancelledError`. Local cancellation grace
  remains below Scheduler's existing 30-second lease margin, and focused tests prove a
  cooperative timed-out handler settles before its claim can expire.
- External Channel callback admission commits a content-free Session-bound trigger
  before provider exact/history I/O and treats the admitted target Session as immutable.
- Mailbox admission stores one provider message per row and orders by stable group,
  sequence, then row ID.
- Provider content exists only in task memory until cursor CAS, mailbox admission, queue
  transitions, and Session runnable state commit atomically.
- Existing pending mailbox state remains wake-recovery authority; no durable wake table
  is added.
- Persisted payload migration has no compatibility reader and does not support mixed
  old/new application versions.

## Phase Dependencies and Context Checkpoints

### Phase 1 — Runtime substrate

Inputs: approved Design revision 1 and the current Scheduler/AppContext lifecycle.

Outputs:

- common handler registry, request/handle/outcome contracts, and bounded Local backend;
- AppContext pre-close callbacks and Runtime singleton ownership;
- global backend configuration and startup rejection for unavailable Temporal;
- Scheduler delegation through a JSON-safe per-claim request while retaining existing
  DB state;
- one AppContext/DI base per co-located non-reload devserver process, with externally
  owned FastAPI lifespans that never close the root context; and
- unit, lifecycle, Scheduler, config, and Helm render evidence.

Checkpoint to Phase 2: stable Runtime interfaces, unchanged Scheduler persistence
semantics, and no ingress or mailbox behavior change.

### Phase 2 — Canonical mailbox contract

Inputs: Phase 1 runtime/config surfaces.

Outputs:

- mailbox order-group/order-sequence schema and repository ordering;
- single-message External Channel mailbox payload and one-row promotion;
- `prompt_role = context | invocation` throughout mailbox, Event, engine, chat,
  projections, OpenAPI, generated clients, fixtures, and tests;
- generated forward Alembic migration that rewrites durable Event/mailbox JSON, splits
  pending legacy envelopes in place, and removes the old kind/field/value contract; and
- absence checks for batch payloads and legacy prompt-role names.

Checkpoint to Phase 3: current synchronous ingress still works, but it creates
independent mailbox rows through the final canonical payload contract.

### Phase 3 — Durable ingress and batching

Inputs: Phase 1 Runtime and Phase 2 canonical mailbox contract.

Outputs:

- active Session drain and ingress item persistence, repositories, diagnostics fields,
  and generated migration additions;
- DB-only callback admission after existing authentication/access/Binding/Session
  filtering;
- first-one/later-ten queue claims, Session lease reclaim, retry-tail ordering, and
  bounded failure deletion/logging;
- typed Slack/Discord exact/history policies and admitted-trigger prompt-role
  correlation;
- sequential tentative cursor evaluation, final deterministic lock/CAS, atomic mailbox
  successful-subset commit, and one post-commit wake;
- producer recovery scans and Redis-independent correctness; and
- removal of synchronous normal-message provider history and immediate per-trigger
  wake paths.

Checkpoint to Phase 4: full product behavior implemented with deterministic lower-level
coverage and no unauthorized durable authority.

### Phase 4 — Validation, Specs, and cleanup

Inputs: stable Phase 3 diff and fresh deterministic test prerequisites.

Outputs:

- active-queue operator diagnostics, metrics, and testenv inspection/release APIs;
- Slack/Discord exact/history barriers, ordered callback fixtures, Retry-After sequences,
  and sanitized evidence;
- deterministic E2E coverage for callback acknowledgement, batching, out-of-order
  cursor semantics, mailbox cardinality, mixed outcomes, retry tail, wake failure,
  restart recovery, and migration;
- full authority/removal/absence validation;
- Living Spec promotion and matching Requirements/Design `implemented` date after all
  required validation succeeds; and
- deletion of this plan and every tracked phase plan after spec promotion.

Checkpoint: every stacked PR exists, the complete stack CI passes, and no PR is merged
without separate requester approval.

## Workstream Ownership

| Workstream | Owner | Primary paths | Interfaces produced/consumed |
| --- | --- | --- | --- |
| Common Job Runtime and AppContext | `/root` | `python/apps/azents/src/azents/job_runtime/**`, `azents/utils/appctx.py`, `azents/app.py`, CLI entrypoints | Runtime request/handle/outcome, registry, shutdown lifecycle |
| Scheduler and global configuration | `/root` | `azents/scheduler/**`, `azents/core/config.py`, `infra/charts/azents/**`, ArgoCD packaging as applicable | registered Scheduler handler adapter, backend selector |
| Mailbox and prompt role | `/root` | mailbox model/repository/service, engine events/rendering, chat projections, OpenAPI and generated clients | single-message payload, FIFO group/sequence, `prompt_role` |
| Persistence and ingress services | `/root` | External Channel RDB models/repos/services/transports, migrations | Session drain/item state, admission, claims, finalization, recovery |
| Testenv and E2E | `/root` | `testenv/azents/e2e/**`, testenv API, provider fakes | barriers, inspection, deterministic evidence |
| Independent review | `/root/channel-ingress-reviewer` | read-only across each phase diff | requirement/design/security/data-loss/scope review report |

Owned implementation paths do not authorize overlapping edits by the reviewer. The
reviewer never modifies files.

## Removal Obligations

| Removal | Owning phase | Replacement | Absence verification |
| --- | --- | --- | --- |
| Scheduler-only `TaskExecutor` and `LocalTaskExecutor` execution boundary | 1 | common Job Runtime Scheduler handler adapter | static search finds neither executor class nor direct Scheduler handler invocation; Scheduler tests use Job Runtime only |
| independent AppContext creation for co-located devserver roles | 1 | one externally owned AppContext/DI base per process | lifecycle identity tests |
| multi-message External Channel mailbox payload | 2 | one message per mailbox row | migration and static payload assertions |
| `authorization`, `context_only`, `authorized_invocation`, `Authorization:` | 2 | canonical `prompt_role` contract | repository, DB, generated contract, fixture searches |
| synchronous provider history/mailbox work in normal callbacks | 3 | DB-only admission plus drain handler | callback barrier E2E and call counters |
| callback failure discarding already delivered Discord backlog | 3 | independent durable callback admission attempts | deterministic callback backlog test |
| normal-message Redis conversation lock correctness dependency | 3 | PostgreSQL Session lease and cursor CAS | Redis-unavailable test |
| immediate per-trigger mailbox wake | 3 | one non-empty processing-batch wake | wake counter assertions |
| completed ingress outcomes/tombstones | 3 | active rows plus failure-only logs | schema/repository absence tests |
| temporary plans | 4 | approved Design and promoted Living Specs | final tree absence check |

## Validation Matrix

- Phase-focused Python checks: Ruff, formatter, `ty`, and targeted pytest modules.
- Migration checks: generated revision chain, migration integration tests, latest-head
  assertions, upgrade validation, and `db-schemas/rdb/revision` alignment.
- Generated contracts: OpenAPI dump and required Python/TypeScript client regeneration.
- Helm/config: render tests proving one backend value reaches all relevant roles and
  unavailable Temporal fails startup.
- E2E: deterministic Slack and Discord provider fakes; required scenarios fail rather
  than skip when PostgreSQL, fake providers, or Runtime fixtures are unavailable.
- Optional live provider smoke tests may skip only when credentials are absent and do
  not replace deterministic CI evidence.
- Final full checks: Azents Python quality suite, affected TypeScript quality suite,
  testenv unit/E2E lanes, documentation validators, spec review, and stack CI.

## Prerequisites and Blockers

- PostgreSQL is required for migration, queue, CAS, and mailbox integration tests.
- Redis may be present for existing routing tests but must be removable from ingress
  correctness scenarios.
- Docker/Testcontainers are required for migration integration and deterministic E2E.
- No live Slack or Discord credential is required for mandatory CI evidence.
- Existing provisional Discord changes are preserved outside Phase 1. The callback
  backlog portion may be reapplied in Phase 3 only after scope review; reusable SDK
  authentication is omitted unless the approved mechanism implementation requires it.
- Any new product behavior, durable authority, compatibility fallback, or backend mode
  returns to feature design. Local implementation refinements remain `Design delta:
  None`.

## Review and Stack Policy

The exact independent reviewer for every phase is
`/root/channel-ingress-reviewer`. Review inputs are the confirmed Requirements, accepted
ADR, approved Design revision 1, current Specs, phase execution plan, and phase diff.
Review priority is Requirements/Design authority, security/privacy, data loss,
migration safety, source-of-truth duplication, compatibility fallbacks, and scope drift.

Each phase is committed and opened as a PR before the next phase starts. All four PRs
are created before CI monitoring. Dependent branches are rebased with the repository
stacked-PR workflow when an earlier phase changes. PRs are never merged without explicit
requester approval.
