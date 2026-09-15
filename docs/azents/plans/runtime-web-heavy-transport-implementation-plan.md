---
title: "Runtime Web Heavy Transport Implementation Plan"
created: 2026-09-14
updated: 2026-09-14
tags: [runtime-web, transport, implementation, testing]
---

# Runtime Web Heavy Transport Implementation Plan

- Requirements: [runtimeweb-260914/REQ](../requirements/runtimeweb-260914-heavy-workload-services.md)
- Decisions: [runtimeweb-260914/ADR](../adr/runtimeweb-260914-heavy-workload-services.md)
- Approved Design: [runtimeweb-260914/DESIGN](../design/runtimeweb-260914-heavy-workload-services.md), revision `1`
- Approved mechanisms: `M1` through `M15`
- Independent reviewer: `/root/runtime-web-heavy-reviewer`
- Primary owner: `/root`
- Delivery: four stacked PRs titled `Runtime Web transport [n/4]: <phase>`
- Design delta: `None`

## Stack

### 1/4 Core transport

Add the inactive replacement protocol, generated fingerprint, typed session and
stream state, hierarchical credit, fair scheduler, Redis/in-memory capacity
contract, additive Owner-session route, exact Owner lease manager, Runner session
offer, persistent Runner Web session, pooled loopback HTTP client, and authority
watcher grouping. The old path remains the sole active production behavior. Approved
mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M10`, `M11`, `M15`.

### 2/4 Gateway, relay, and operations

Add the inactive Gateway Control-session pool, browser logical-stream integration,
persistent one-hop Owner relay, Runtime capacity admission, OpenMetrics, Runner
telemetry, hard process ceilings, readiness/liveness, HPA, pressure metric, PDB,
preStop/drain, termination grace, and Ingress contract. The replacement remains
unavailable from production readiness. Approved mechanisms: `M1`, `M2`, `M3`, `M5`,
`M7`, `M8`, `M9`, `M10`, `M11`, `M12`.

### 3/4 Clean cutover, removal, and validation substrate

Add the maintenance preflight and replacement activation, apply the destructive
migration, remove every old RPC/message/intent/table/setting/channel/compatibility
surface/test/fixture/generated surface, and add deterministic Redis/in-memory parity,
asset, transfer, slow-peer, SSE, WebSocket, local/relay, fault, cutover, and load
harness coverage. Approved mechanisms: `M4`, `M8`, `M12`, `M13`, `M14`.

### 4/4 Final validation, Specs, and cleanup

Run the complete real-Runtime E2E and bounded performance matrix, correct
implementation defects, audit M1 through M15 in both directions, update Living Specs,
record validation evidence, set matching implemented dates only after success, and
remove all implementation and phase plans. Approved mechanisms: `M10`, `M12`, `M13`,
`M14`, `M15`.

## Dependencies and Interfaces

- Phases are strictly sequential; each branch is based on the prior phase branch.
- Phase 1 fixes every shared protocol, Owner, and Runner interface needed by later
  phases while keeping production behavior unchanged.
- Phase 2 fixes Gateway, relay, and operations before activation.
- Phase 3 is the only phase that activates the replacement and removes old behavior.
- Phase 4 promotes validated current behavior into Specs and deletes temporary plans.
- No phase may add a protocol version, backward-compatibility branch, fallback,
  direct Gateway-to-Runner path, durable capacity authority, active-stream replay, or
  a different numeric profile.

## Ownership

| Phase | Implementation owners | Primary paths | Reviewer |
| --- | --- | --- | --- |
| 1 | `/root/runtime-web-protocol-owner`, `/root/runtime-web-owner-runner-owner`, `/root` integration | replacement proto/shared library, Runtime models/repos/Owner manager, Runner Web transport, migration, approved docs/plans | `/root/runtime-web-heavy-reviewer` |
| 2 | assigned at phase start | Gateway, Control relay/broker, settings, metrics, Helm | same reviewer |
| 3 | assigned at phase start | production composition, destructive migration, old removal, Python integration and `testenv/azents` | same reviewer |
| 4 | `/root` plus responsible fix owners | validation records, Specs, plans | same reviewer |

## Validation

Every phase runs focused Python format, lint, type, and tests for changed subprojects
plus generated-surface validation. Phase 3 and 4 run repository absence searches.
Phase 4 runs approved real-Runtime E2E and scheduled/release performance evidence
where the dedicated prerequisite is available.

## Removal Obligations

All Removal and Replacement rows in `runtimeweb-260914/DESIGN` are owned by phase 3
unless replaced earlier by an inactive implementation. Phase 3 must prove no old
active state before destructive migration and no old source/config/test/generated
surface afterward. Phase 4 verifies absence again before plan cleanup.

## Spec and Rollout

Living Specs remain current behavior until phase 3 activates the replacement. Phase
4 updates `agent-runtime-control`, `agent-runtime-persistence`, E2E strategy, and any
other impacted current Specs. Live infrastructure is not modified by this stack;
clean-cutover execution remains an operator action after merge and release evidence.

## Blockers

None at plan revision. REQ-1, REQ-2, and REQ-4 remain conditional on the approved
performance gates. A missed threshold is an implementation defect unless evidence
requires a reapproved Design change.
