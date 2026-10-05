---
title: "Redis-Free Single-Process Operation Design"
created: 2026-10-05
implemented: 2026-10-05
tags: [backend, broker, runtime, reliability]
document_role: primary
document_type: design
snapshot_id: broker-261005
---

# Redis-Free Single-Process Operation Design

- Snapshot: `broker-261005`
- Requirements: [broker-261005/REQ](../requirements/broker-261005-memory-session-broker.md)
- Decisions: [broker-261005/ADR](../adr/broker-261005-memory-session-broker.md)

## Current System and Architecture

The all-in-one devserver already shares AppContext across API, Worker and
Scheduler, but the SessionBroker and Runtime Control coordination stores are
Redis-only. Broadcast, live projection, Runtime coordination, terminal
coordination, transfer/upload state and conversation locks already have memory
adapters. Enrollment admission also needs a memory rate limiter with the same
fixed-window limits.

`AZ_SESSION_BROKER_BACKEND=memory` selects the co-located mode; the existing
`redis` default remains. Broker endpoints share an application-owned memory
state, while preserving separate API and Worker identities. Related dependencies
select their process-local implementations in this mode. Runtime Control receives
the exact coordination store objects used by the API and Worker; its transfer,
upload and capacity state use existing memory implementations.

Broker state uses a condition-protected queue/ownership model with monotonic
expiry. Wake and stop bodies drain per Session only after accepted ownership;
mailbox hints reach only live owners. Activity retains a generation tombstone
until expiry; cutover barriers use exact token release/renewal and block new
ownership. Expiry/cancellation does not manufacture successful work.

## Lifecycle, Security and Recovery

The shared root owns all memory resources; close wakes blocked receivers and
clears ephemeral state. The Worker drains before root resources close. Reload
children and standalone role roots reject memory composition before work is
served. Existing Redis errors remain failures, not implicit memory fallback.

PostgreSQL remains execution and recovery authority. No API schema, permission,
durable transcript, retry or model behavior changes. Existing wake-up recovery
can recreate routing from an empty process state. Memory enrollment limiting
retains grant/source-address isolation and existing attempt/window limits.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Explicit co-located memory Session backend with shared state | REQ-1, REQ-4; ADR-D1 | required |
| M2 | Existing lease/heartbeat, activity-generation and barrier semantics in memory | REQ-2, REQ-3; ADR-D2; Run Resume Spec | derived |
| M3 | Shared memory Runtime/terminal coordination and existing ephemeral adapters | REQ-1; ADR-D1; existing adapter contracts | derived |
| M4 | Reject reload/independent roots that cannot share memory | REQ-4; ADR-D1; existing devserver ownership | derived |
| M5 | Preserve Redis defaults and durable recovery/authorization | REQ-3, REQ-4; ADR-D2 | existing |

## Removal and Replacement

| Unit | Removal authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Unconditional Session Redis composition | REQ-1 | Explicit backend selection | API/Worker dependencies | Memory-mode Redis factories reject every call in tests |
| Unconditional co-located Runtime Redis stores | REQ-1 | Existing memory stores shared with Control | All-in-one lifecycle | Store identity and Control composition tests |
| Redis-only enrollment limiter and Worker readiness | REQ-1, retained admission contract | Memory fixed-window limiter and memory-mode readiness | Process dependency composition | Limit/shutdown tests |

Redis-mode adapters, durable authority, historical documents and existing API
schemas are retained. No legacy compatibility layer or data migration is needed.

## Test Strategy

E2E primary matrix: Redis-free co-located startup, API-produced wake/stop reaching
Worker, live event delivery and empty-state durable recovery; existing Redis-mode
required journeys remain unchanged. Add deterministic native contract/composition
tests first to localize ownership, activity, barrier and lifecycle failures.

Use fake monotonic clocks and explicit events/conditions, never scheduler sleeps
for ordering. Exercise the real DI providers with Redis construction forbidden.
Control composition uses its existing deterministic test harness, retaining gRPC
service registration and shared store identities. Existing PostgreSQL testenv
recovery fixtures provide durable-state support when full model E2E is not needed.
Live provider credentials and live infrastructure are not prerequisites. Required
CI must pass; a missing prerequisite is reported rather than claimed as success.

## Feasibility and Risks

Existing AppContext lifecycle and memory coordination adapters support the scope.
The broker and limiter are new local adapters; expiry semantics and resource-close
ordering need explicit tests. Memory mode is not distributed coordination, and
unsupported roots fail closed. No unresolved product-scope choices remain.

## Implementation Verification

- Backend Ruff and whole-subproject `ty check --error-on-warning` pass.
- Full backend suite: 10,806 passed and three pre-existing optional skips. The
  subsequently added complete Worker/Scheduler composition test and final focused
  suite pass (47 tests).
- Real shared-container API production and AgentWorker dispatch deliver ordered
  wake/stop signals; the runner/recovery doubles isolate model execution.
- Production Worker and Scheduler dependency graphs resolve without overrides,
  and the shared Public API lifespan opens without Redis. Admin startup still
  requires its ordinary PostgreSQL bootstrap; this is not a Redis-free database
  or object-storage deployment.
- Runtime Control's native composition harness exercises both backends and
  rejects Redis construction in memory mode, verifies shared store identity,
  registers its services and closes resources. Its external database/object-store
  collaborators are test doubles, not live deployment evidence.
- Fresh memory roots accept retained recovery candidates through the existing
  recovery orchestration. Native PostgreSQL recovery and Redis regressions remain
  covered by the full backend suite. Required distributed E2E runs in PR CI;
  no live Provider or live infrastructure validation is claimed.

## Design Approval

- Mode: Collaborative, bounded direct implementation.
- Decision owner: requester for the confirmed topology and implementation scope.
- Approved on: 2026-10-05 through the explicit instruction to implement the fix.
- Approved Design revision: 1, limited to mechanisms entailed by that instruction
  and retained existing contracts; no separate design-review approval is claimed.
- Approved authority IDs: M1, M2, M3, M4, M5.
- Scope: Redis-free shared-memory single-process operation; retained distributed
  Redis mode, durable authority and existing product behavior.
