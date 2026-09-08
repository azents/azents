---
title: "Ephemeral Redis Coordination Authority Implementation Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [runtime, redis, postgresql, reliability, migration]
---

# Ephemeral Redis Coordination Authority Implementation Plan

## Authority and Scope

- Requirements: [Ephemeral Redis Coordination Authority Requirements](../requirements/redis-260907-ephemeral-coordination-authority.md) (`redis-260907/REQ`)
- ADR: [Ephemeral Redis Coordination Authority](../adr/redis-260907-ephemeral-coordination-authority.md) (`redis-260907/ADR-D1` through `ADR-D4`)
- Approved Design: [Ephemeral Redis Coordination Authority Design](../design/redis-260907-ephemeral-coordination-authority.md) revision `2` (`redis-260907/DESIGN`)
- Approved mechanisms: `M1` through `M12`
- Design delta: `None`

## Objective

Remove Redis/Valkey persistence as a correctness dependency. PostgreSQL becomes the durable Provider/Runner connection-generation issuer, Redis remains disposable volatile routing, migration-time Home subjects enter the `2^48` band, every later subject atomically receives zeroed authority, Redis and public JSON use exact canonical generation strings, and lost volatile work fails closed before automatic reconnect or durable reconciliation.

## Delivery Stack

| Phase | Branch | Base | PR boundary | Approved mechanisms |
| --- | --- | --- | --- | --- |
| 1 | `feature/redis-ephemeral-1-authority-foundation` | `main` | Approved snapshot documents, additive generation-authority schema without activation seed/marker/triggers, connection-generation `BIGINT` widening, DB-only repository primitives, and focused migration/repository tests | `M1`, storage portion of `M7`, repository portion of `M12` |
| 2 | `feature/redis-ephemeral-2-runtime-cutover` | Phase 1 | Activation migration with table-locked seed, future-subject triggers and marker; one-shot candidate publication; Provider/Runner registration integration; fresh Runtime/Transfer/Terminal Redis schemas; canonical Redis/public generation strings and generated clients; Home cutover controls; ephemeral Valkey reference contract | `M2`-`M9`, `M11`, integration portion of `M12` |
| 3 | `feature/redis-ephemeral-3-validation-specs` | Phase 2 | Empty-store and cross-capability validation, string-boundary evidence, Living Spec promotion, implementation markers, removal audit, and plan cleanup | `M10`, validation completion for `M1`-`M12` |

Phase 1 is additive and unused. Phase 2 is the coordinated activation boundary and must deploy only through the Home Runtime Control scale-to-zero procedure. Phase 3 proves the complete behavior before promoting current Specs and removing temporary plans.

## Integration Boundaries

- Phase 1 exposes database-only allocate, preflight, acceptance, and integrity primitives without changing current Runtime registration callers.
- Phase 2 activation migration seeds existing subjects, installs `AFTER INSERT` generation-row triggers, and records the marker in one table-locked transaction.
- Phase 2 replaces store-owned generation allocation with candidate stage/promotion and composes Phase 1 repository primitives in one registration coordinator.
- Provider final acceptance includes authenticated connection history, credential use, binding state, and audit evidence in one DB-only transaction.
- Runner final acceptance revalidates Runtime and credential authority without adding Runner history.
- Redis, HTTP, gRPC, filesystem, object-storage, Provider, and infrastructure calls never occur inside a DB transaction.
- PostgreSQL, Python, and protobuf retain positive signed-`BIGINT` integers. Redis uses canonical 19-digit connection-generation strings; public/browser JSON uses canonical unpadded strings; TypeScript uses opaque exact equality.
- Phase 3 may fix defects in the owning earlier phase but cannot introduce a new material mechanism.

## Removal Obligations

- Remove Redis `INCR`/`PERSIST` generation counters and in-memory adapter counters.
- Remove the unversioned Runtime coordination namespace from active code.
- Remove numeric Redis, public, and browser JSON connection-generation fields without adding a compatibility reader or union.
- Remove rolling mixed-version activation for the allocator boundary while retaining normal rolling behavior after cutover.
- Remove the Compose Valkey data volume and any persistence implication.
- Remove the Living Spec requirement for Redis-retained generation counters.
- Do not add Redis counter import, legacy namespace reads, dual writes, lazy missing-row initialization, timestamp-based migration classification, fallback allocation, or a second live connection authority.

Absence is verified by repository searches, store contract tests, migration tests, rendered deployment assertions, and empty-store E2E.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Schema and migrations | Additive foundation upgrade; activation seed/trigger/marker transaction; blocked-insert race; `BIGINT` round trip; missing-row integrity; `2^63 - 1` exhaustion |
| Generation repository | Concurrent monotonic allocation, retained gaps, preflight, acceptance CAS, row retention, and no external calls |
| Registration publication | Candidate invisibility, exact token, reset invalidation, higher-generation fencing, exact cleanup, crash boundaries, ambiguous-outcome failure |
| Provider/Runner integration | Final authorization revalidation, Provider history atomicity, Runner observed-state monotonicity, stale heartbeat/report/result/revoke rejection |
| String contracts | Redis Lua/cjson, Runtime Transfer/Terminal schemas, public API, Terminal WebSocket, generated clients, and TypeScript preserve exact consecutive values through `2^63 - 1` without numeric coercion |
| Deployment | Runtime Control scale-to-zero procedure, temporary HPA/PDB suspension, schema readiness marker, new namespace, and later restoration of normal rollout settings |
| Empty-store recovery | Real PostgreSQL/Valkey/Runtime Control/Provider/Runner E2E proves reconnect, stale rejection, and new work |
| Other Redis paths | Lost operation/Transfer/Terminal fails closed; broker/External Channel recovery; enrollment window resets without credential authority |
| Quality | Ruff, format, `ty check --error-on-warning`, affected pytest suites, migration suite, Helm tests, docs validation, code review, and Spec review |

## Rollout and Rollback

- Phase 2 documents and renders the strict Home sequence: disable HPA/PDB constraints, scale Runtime Control to zero, confirm no legacy endpoint, migrate, deploy the new namespace and binary, restore replicas/HPA/PDB, and verify reconnect.
- The new Runtime Control refuses readiness without the required schema and cutover marker.
- Before first new-band acceptance, deployment may restore the legacy procedure. After acceptance commit, Runtime Control is roll-forward-only and the legacy allocator must not restart.
- No live Home deployment change, Helm sync, restart, Redis clear, PR merge, or Kubernetes write is performed by this implementation session.

## Spec and Documentation

Phase 3 updates the current Runtime Control and affected recovery Specs plus operator/chart documentation. Requirements and Design receive the same `implemented` date only after code, migration, deployment-contract, E2E, and Living Spec verification complete.

## Owners and Review

- Implementation owner: `/root`
- Exact independent read-only reviewer for every phase: `redis-implementation-reviewer`
- GitHub reviewer requested on every PR: `hardtack`
- GitHub PR title/body language: English
- Reviewer inputs: confirmed Requirements, accepted ADR, approved Design revision `2`, this plan, the active phase plan, current diff, focused test evidence, and absence evidence.

## Context Checkpoints

At each phase boundary record completed behavior, changed interfaces, commands and results, removal evidence, remaining work, relevant paths, risks, and blockers. New material behavior returns to technical design. Local details remain within approved mechanisms.

## Cleanup

Phase 3 deletes this implementation plan and all phase execution plans only after implementation, validation, Living Spec promotion, implementation markers, and final absence verification complete.
