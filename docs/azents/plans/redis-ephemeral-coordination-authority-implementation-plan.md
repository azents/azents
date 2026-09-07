---
title: "Ephemeral Redis Coordination Authority Implementation Plan"
created: 2026-09-07
tags: [runtime, redis, postgresql, reliability, migration]
---

# Ephemeral Redis Coordination Authority Implementation Plan

## Authority and Scope

- Requirements: [Ephemeral Redis Coordination Authority Requirements](../requirements/redis-260907-ephemeral-coordination-authority.md) (`redis-260907/REQ`)
- ADR: [Ephemeral Redis Coordination Authority](../adr/redis-260907-ephemeral-coordination-authority.md) (`redis-260907/ADR-D1` through `ADR-D4`)
- Approved Design: [Ephemeral Redis Coordination Authority Design](../design/redis-260907-ephemeral-coordination-authority.md) revision `2` (`redis-260907/DESIGN`)
- Approved mechanisms: `M1` through `M13`
- Design delta: `None`

## Objective

Remove Redis/Valkey persistence as a correctness dependency. PostgreSQL becomes the durable Provider/Runner connection-generation issuer, Redis remains disposable volatile routing, existing Home subjects enter the `2^48` migration band, later identities start at generation one, and JSON-exposed connection generations use exact decimal strings.

## Delivery Stack

| Phase | Branch | Base | PR boundary | Approved mechanisms |
| --- | --- | --- | --- | --- |
| 1 | `feature/redis-ephemeral-1-authority-foundation` | `main` | Approved snapshot documents, additive generation-authority schema without a cutover marker or seed, `BIGINT` widening, repository primitives, focused migration/repository tests | `M1`, storage portion of `M7`, repository portion of `M12` |
| 2 | `feature/redis-ephemeral-2-runtime-cutover` | Phase 1 | Strict activation migration with marker and existing-subject seed, one-shot registration publication, Redis v2 namespace, runtime integration, JSON string contracts and generated clients, deployment cutover, ephemeral Valkey, empty-store E2E, Living Specs, implementation markers, and plan cleanup | `M2`-`M6`, remaining `M7`, `M8`-`M13` |

Phase 1 is additive and does not activate a second allocator or namespace. Phase 2 is one coordinated activation boundary so the new allocator, JSON contracts, namespace, deployment policy, and verification cannot be deployed independently.

## Integration Boundaries

- Phase 1 exposes database-only allocate, preflight, acceptance, and integrity primitives without changing `RuntimeCoordinationStore.register_connection()` callers.
- Phase 2 replaces store-owned allocation with candidate stage/promotion and composes Phase 1 primitives in the Runtime Control registration coordinator.
- Provider final acceptance includes authenticated connection history in the same DB transaction.
- Runner final acceptance revalidates Runtime and credential authority without adding Runner history.
- Redis, HTTP, gRPC, filesystem, object-storage, Provider, and infrastructure calls never occur inside a DB transaction.
- Protobuf `uint64` generation fields remain unchanged. Public/browser JSON generation fields cut directly from number to canonical decimal string with no union or fallback.

## Removal Obligations

- Remove Redis `INCR`/`PERSIST` generation counters and in-memory adapter counters.
- Remove the unversioned Runtime coordination namespace from active code.
- Remove numeric public/browser JSON connection-generation fields.
- Remove the Compose Valkey data volume and persistence behavior.
- Remove the Living Spec requirement for Redis-retained generation counters.
- Do not add Redis counter import, legacy namespace reads, dual writes, fallback allocation, or a second live connection authority.

Absence is verified by repository searches, contract tests, generated schema diffs, rendered deployment tests, and empty-store E2E.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Schema and migration | Alembic upgrade tests, existing-subject `2^48 - 1` seed, later-subject generation one, durable maxima guard, `BIGINT` round trip |
| Generation repository | Concurrent monotonic allocation, gaps, preflight, acceptance CAS, row retention/integrity |
| Registration publication | Candidate invisibility, exact token, reset invalidation, higher-generation fencing, crash point and ambiguous-outcome tests |
| Provider/Runner integration | Credential revalidation, Provider history atomicity, Runner observed-state monotonicity, stale heartbeat/report/result/revoke rejection |
| JSON and clients | OpenAPI/generated clients use strings, Terminal WebSocket uses opaque strings, no number/string union |
| Deployment | Runtime Control non-overlap, schema readiness, new Redis namespace, Compose Valkey without persistence |
| Empty-store recovery | Real PostgreSQL/Valkey/Runtime Control/Provider/Runner E2E proves reconnect, stale rejection, and new work |
| Other Redis paths | Lost operation/Transfer/Terminal fails closed; broker/External Channel recovery; enrollment window resets without credential authority |
| Quality | Ruff, format, `ty check --error-on-warning`, affected pytest suites, Helm tests, docs validation |

## Rollout and Rollback

- Phase 2 documents and renders the strict sequence: stop old Runtime Control, migrate, start only the new version, reconnect streams.
- The new Runtime Control refuses readiness without the required schema/cutover evidence.
- After a `2^48`-band generation is accepted, Runtime Control is roll-forward-only; the legacy allocator must not restart.
- No live Home deployment change, Helm sync, restart, Redis clear, or PR merge is performed by this implementation session.

## Spec and Documentation

Phase 2 updates the current Runtime Control and affected recovery Specs, operator/chart documentation, OpenAPI-generated documentation, and reference Compose contract. Requirements and Design receive the same `implemented` date only after all validation passes.

## Owners and Review

- Implementation owner: `/root`
- Independent reviewer for both phase PRs: `hardtack`
- GitHub PR title/body language: English
- Reviewer inputs: confirmed Requirements, accepted ADR, approved Design revision `2`, this plan, each phase plan, current diff, focused tests, and absence evidence.

## Context Checkpoints

At each phase boundary record completed behavior, changed interfaces, commands and results, removal evidence, remaining work, risks, and blockers. New material behavior returns to technical design. Local details stay within approved mechanisms.

## Cleanup

Phase 2 deletes this implementation plan and both phase execution plans after implementation, validation, Living Spec promotion, and implementation markers are complete.
