---
title: "Runtime System Metrics Overview Implementation Plan"
created: 2026-08-24
updated: 2026-08-24
tags: [runtime, metrics, implementation, api, frontend]
---

# Runtime System Metrics Overview Implementation Plan

## Authority

- Requirements: [runtime-260824/REQ](../requirements/runtime-260824-system-metrics-overview.md)
- ADR: [runtime-260824/ADR](../adr/runtime-260824-system-metrics-overview.md)
- Approved Design: [runtime-260824/DESIGN](../design/runtime-260824-system-metrics-overview.md), revision `1`
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Current Specs:
  - [Agent Runtime Persistence](../spec/flow/agent-runtime-persistence.md)
  - [Workspace & Membership](../spec/domain/workspace.md)
- Design delta: `None`

The plan decomposes only the approved Runner-only metrics path. It does not add
Provider collection, Kubernetes Metrics API access, sidecars, privileged collectors,
PostgreSQL state, migrations, Admin surfaces, RBAC, configuration, push delivery,
alerting, or changes to `AgentRuntimeResponse`.

## Fixed Integration Contracts

- The Runner is the only reporter and advertises optional capability
  `runtime.system-metrics.v1` without changing the required Runner protocol version
  or transfer capability.
- One additive Runner message carries Runtime identity, a positive monotonic sequence,
  closed execution scope, and independent CPU, memory, and disk observations. It
  carries no timestamp, free-form diagnostics, path, hostname, Provider identity, or
  infrastructure identifier.
- Connected reads select only the current Runner connection generation from the
  Coordination Store. Disconnected reads may select only the Runtime's exact durable
  last-known Runner generation. Reconnect or replacement never searches or falls back
  to another generation.
- A successful store read with no retained series returns an empty unavailable or
  unsupported overview as appropriate. A store I/O exception fails only the dedicated
  metrics endpoint; the existing lifecycle endpoint and Runtime behavior remain
  unaffected.
- For each metric, the latest accepted observation is authoritative even when it is
  `unavailable` or `unsupported`; the service never falls back to an older available
  value or interpolates a missing interval. `stopped` and `disconnected` override the
  current presentation while retaining trend. Otherwise an available latest
  observation is `fresh` through three minutes inclusive and `stale` after three
  minutes. No sample for a capable current generation is `unavailable`; capability
  absence is `unsupported`.
- The public overall-summary enum is exactly `fresh`, `partial`, `stale`,
  `unavailable`, `unsupported`, `stopped`, or `disconnected`. It is a bounded
  projection of the same three current metric states, not a new source of truth:
  1. `stopped` when the Runtime lifecycle summary is stopped;
  2. otherwise `disconnected` when no current Runner connection exists;
  3. otherwise `fresh` when all three metrics are fresh;
  4. otherwise `partial` when at least one metric is fresh;
  5. otherwise `stale` when at least one metric is stale;
  6. otherwise `unavailable` when at least one metric is unavailable; and
  7. otherwise `unsupported` when all three metrics are unsupported.
  Per-metric state remains the authoritative detail, and mixed-state tests cover
  every projection branch.
- The ring contract atomically rejects duplicate or lower sequences, appends accepted
  samples, retains at most 60, refreshes one-hour expiry, and filters measurements
  older than one hour in both Redis and memory implementations.
- The Public API uses existing Agent access, returns privacy-safe normalized values,
  and is the sole contract consumed by both product entry points.

## Delivery Stack

### Phase 1/2 — Runtime pipeline and Public API

- Branch: `feat/runtime-system-metrics-1-runtime-api`
- Base: `origin/main` at `62ac03598`
- Owner: primary implementation agent `/root`
- Independent reviewer: `runtime-metrics-reviewer`
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M8`
- Deliverables:
  - approved snapshot documents and tracked plans;
  - Runner collector, immediate/60-second scheduling, and capability advertisement;
  - additive protobuf and generated shared Runtime Control models/client operation;
  - generation-, capability-, and sequence-fenced Control admission;
  - equivalent Redis and in-memory one-hour/60-sample ring;
  - Agent-authorized metrics service and dedicated Public API route;
  - regenerated Public OpenAPI specification and Python/TypeScript clients;
  - deterministic protocol, collector, store, admission, service, authorization, and
    API tests.
- Non-goals:
  - web tRPC wiring, overview component, stories, browser E2E, or Living Spec
    promotion;
  - Provider, chart, database, migration, lifecycle-response, or configuration edits.
- Integration boundary: the generated Public client is complete and reviewable, but no
  product UI consumes the endpoint until Phase 2.
- Context checkpoint: complete in the Phase 1 execution plan. The additive protocol,
  collector scope rules, generation-keyed atomic ring, dedicated privacy-safe API,
  generated clients, validation evidence, absence audit, and independent approval are
  recorded. Remaining UI, browser E2E, and Spec-promotion work stays in Phase 2.

### Phase 2/2 — Product UI, E2E, Specs, and completion

- Planned branch: `feat/runtime-system-metrics-2-product-ui`
- Base: Phase 1 PR branch after the Phase 1 PR is opened
- Owner: primary implementation agent `/root`
- Independent reviewer: `runtime-metrics-reviewer`
- Approved mechanisms: `M5`, `M6`, `M7`, `M8`, with integration verification for
  `M1` through `M8`
- Inputs: opened Phase 1 PR and stable generated Public client contract
- Deliverables:
  - generated-client-backed web tRPC query;
  - shared responsive chat-panel/settings overview and dependency-free SVG trends;
  - visibility-scoped 60-second polling and lifecycle invalidation;
  - loading, empty, partial, unavailable, unsupported, stale, stopped, disconnected,
    gap, and metrics-only query-error stories/tests;
  - required Docker Runtime E2E through product APIs/UI without direct database writes;
  - Spec review and updates to the Runtime persistence and owning Workspace/UI Specs;
  - matching `implemented: 2026-08-24` markers only after complete verification;
  - removal of this implementation plan and both phase execution plans after validated
    Spec promotion.
- Non-goals: Admin UI/API, configurable polling, browser-owned history, interpolation,
  push transport, or infrastructure-specific diagnostics.
- Context checkpoint: record UI states, responsive evidence, Docker Runtime E2E,
  complete M1–M8 drift audit, Spec promotion, implementation markers, and plan-removal
  evidence before opening the PR.

## Dependencies and Integration Order

1. Complete and review the Phase 1 execution plan.
2. Implement the shared protocol model and generated protobuf surface.
3. Implement Runner collection and scheduling against the shared model.
4. Implement Coordination Store types and Redis/memory parity.
5. Implement Control admission using current connection metadata and the ring contract.
6. Implement the Agent-authorized read service and Public API models/route.
7. Regenerate OpenAPI and both Public clients.
8. Run Phase 1 focused and integrated validation, independent review, and open PR 1/2.
9. Create the Phase 2 branch and tracked execution plan from the open Phase 1 branch.
10. Implement product integration, stories/tests, and required Docker Runtime E2E.
11. Run Spec review, promote current Specs, add matching implementation markers,
    validate complete authority coverage, and remove temporary plans.
12. Open PR 2/2, then monitor the complete stack CI without merging.

## Validation Matrix

| Boundary | Required evidence |
| --- | --- |
| Shared protocol | Generated protobuf diff; closed enums; identity, sequence, numeric, optional-total, privacy, and explicit 4 KiB message-size validation; additive compatibility test |
| Runner collector | cgroup v1/v2, host/VM/container, procfs/meminfo/filesystem fixtures, CPU baseline/reset/zero-elapsed behavior, partial failure, cancellation and reconnect baseline |
| Runner scheduler | Immediate partial report, fixed 60-second cadence with fake monotonic time/events, no catch-up or independent retry loop |
| Control admission | Current generation and capability required; invalid, stale, duplicate, or lower sequence dropped without stream closure or lifecycle mutation; append failure isolated |
| Coordination Store | Redis and memory contract with injected time; atomic sequence append, concurrent ordering, maximum 60, one-hour filter and expiry, empty restart behavior |
| Public service/API | Existing Agent access/404 behavior, runtime-free and capability absence, exact generation selection, all overall-summary mixed-state branches, overlay/freshness boundaries, no fallback, percentages only with totals, privacy-safe schema, and store-read exception isolation from the lifecycle route |
| Generated clients | Source-generated OpenAPI, Python client, and TypeScript client; no manual generated edits |
| Product UI | Generated-client use, visible-only polling, no browser accumulation/interpolation, responsive shared component, complete state stories/tests |
| Required E2E | Repository Docker Runtime fixture; product setup and lifecycle actions; non-machine-specific values; panel reopen; settings parity; access and capability absence |
| Documentation | Docs validation, Spec review, `last_verified_at` updates, matching implementation markers, and removal of temporary plans |

Deterministic tests use fake clocks, events, queues, or authoritative state rather than
fixed sleeps. Exact metric percentages or machine-specific capacity values are never
asserted in CI.

## Removal and Absence Verification

The approved Design identifies no obsolete metrics implementation to remove. Each
phase must instead prove that adjacent authorities remain unchanged:

- no Provider source, capability, deployment, or chart metrics path;
- no PostgreSQL model, migration, backup, or history path;
- no lifecycle reconciliation or `AgentRuntimeResponse` expansion;
- no Admin, RBAC, configuration, alerting, billing, scheduling, or destructive use;
- no Runtime, Runner, Provider, connection, generation, hostname, path, mount, device,
  process, or raw infrastructure identifiers in the new Public metrics response or
  raw metric sample logs. Existing internal structured Runtime/Runner correlation
  fields may remain in bounded warning/error logs, but raw metric values and device
  identities are never logged;
- no second API, push stream, browser history, or alternate legacy metrics format.

Absence evidence is the final path/schema diff plus focused source searches and
existing compatibility tests.

## Rollout and External Actions

- The feature requires no database migration, Provider rollout, Kubernetes action,
  credential, external service, or live infrastructure change.
- Server/API/web and Runner deployment order remains additive. The implementation must
  verify how an old server handles the new protobuf oneof payload; if existing stream
  behavior cannot ignore it safely, implementation stops and returns to Design rather
  than adding an unauthorized fallback.
- Pull requests are opened as a two-PR stack. No PR is merged without explicit
  requester approval.

## Blockers

- No current authority blocker.
- Any finding that requires a new reporter, source of truth, persisted identity,
  failure policy, compatibility path, configuration mode, API contract, or lifecycle
  effect returns to Requirements or Design before implementation.
