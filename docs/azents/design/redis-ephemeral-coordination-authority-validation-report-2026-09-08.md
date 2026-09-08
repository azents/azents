---
title: "Ephemeral Redis Coordination Authority Validation Report"
created: 2026-09-08
tags: [runtime, redis, postgresql, validation, e2e]
document_role: supporting
document_type: supporting-validation-report
---

# Ephemeral Redis Coordination Authority Validation Report

## Result

The `redis-260907` implementation satisfies the confirmed Requirements and approved
Design revision 2 without a Design delta. PostgreSQL now owns Provider and Runner
connection-generation authority. Redis/Valkey contains only disposable coordination
state, and a real empty-Valkey Runtime journey recovered both Provider and Runner
registrations with higher durable authority before rejecting stale Runner traffic and
completing new work.

No live Home cluster resource, ArgoCD Application, Redis instance, or Kubernetes
workload was changed. The remaining operational action is the documented Home
scale-zero, migrate, and scale-up release after the complete PR stack is approved,
merged front to back, and a matching snapshot is available.

## Deterministic Evidence

| Boundary | Evidence | Result |
| --- | --- | --- |
| Full backend regression | `python/apps/azents`: `uv run pytest -q` | `5125 passed, 2 skipped` |
| Backend typing | `python/apps/azents`: `uv run ty check --error-on-warning` | passed |
| Empty-Valkey Runtime recovery | required Docker Runtime Provider E2E clears Valkey, requires Provider re-registration and a higher Runner generation, rejects stale heartbeat/report/result/revoke traffic, then creates and reads a Workspace directory | `1 passed` |
| Durable activation | migration seed, future-subject triggers, cutover marker, downgrade fence, signed-`BIGINT` bounds | passed |
| Candidate publication | Redis/in-memory parity, invisibility, exact token, reset loss, stale generation, ambiguous failure behavior | passed |
| Registration authority | DB-only transaction checks, current Provider expiry, locked Runner revalidation, Provider history atomicity, non-blocking replacement observer | passed |
| String boundaries | Redis fixed-width maximum, public nullable canonical string, Terminal WebSocket, Transfer/Terminal records, generated clients | passed |
| Public Python client | generated unittest suite | `716 passed` |
| TypeScript | format, lint, typecheck, and Azents Web tests | `217 passed` |
| Deployment contract | Helm scale-zero/HPA/PDB render tests, ephemeral Compose Valkey contract, Compose render | `16 passed` and valid render |
| Enrollment rate limiting | real Redis window exhaustion, `FLUSHALL`, fresh best-effort admission, and continued public rejection of consumed, revoked, and expired durable grants | passed |
| Independent review | full Phase 2 review and targeted authorization/data-boundary re-review | approved |

The E2E test uses public APIs to create Workspace, integration, Runtime Profile, Agent,
and running Runtime state. It performs no direct database write. It clears the
test-owned Valkey instance, then requires a numerically higher public Runner generation,
an additional Docker Provider registration, ready lifecycle authority, and Runner
operation availability. It then opens short-lived valid Runner probe streams, waits for
the real Runner to replace them, submits stale heartbeat, failed state report, final
operation result, and stream-close revoke attempts, and verifies the current durable
Runtime projection remains unchanged before a successful new Agent Workspace directory
operation.

## Findings Corrected During Validation

- Transfer dispatch initially formatted generation-scoped stream IDs differently from
  Runtime Control claims. Both now use the canonical fixed-width Redis generation.
- The activation downgrade guard initially could accept an already allocated existing
  subject when high-water and accepted generation advanced together. Downgrade now
  permits only untouched zero rows or untouched legacy-seed rows.
- Runner final authorization now locks the Runtime row before accepted-generation
  mutation.
- Provider final acceptance now checks credential and external evidence expiry at a
  fresh acceptance timestamp while preserving the original connection timestamp.
- A never-connected Runtime exposes `runner_generation: null`; positive public
  generations remain canonical strings.
- Post-commit Runner replacement observer failures are logged without hiding the
  committed registration acceptance.
- Foundation downgrade now includes durable accepted-generation authority even when
  the legacy Runner projection has not observed that accepted generation.
- Provider and Runner registration cancellation after promotion revokes the exact
  promoted route before cancellation propagates.
- Empty-Valkey E2E now proves Provider recovery and stale Runner
  heartbeat/report/result/revoke fencing, not only Runner generation advancement.
- Enrollment reset validation now proves a fresh abuse window cannot make consumed,
  revoked, or expired PostgreSQL grants usable through the public exchange.
- Full-suite stale revision, Runtime Control composition, and Transfer namespace
  assertions were updated to the activated schema.

## Design Authority Coverage

| Mechanism | Validation conclusion |
| --- | --- |
| `M1` | Per-kind/per-subject PostgreSQL high-water and accepted evidence is active and retained. |
| `M2` | Allocation, preflight, and acceptance are DB-only transactions separated from external calls. |
| `M3` | Candidate staging and promotion are invisible, token-bound, one-shot, and reset-safe. |
| `M4` | Provider history, credential use, binding evidence, audit, and generation acceptance commit atomically. |
| `M5` | Runner acceptance revalidates the locked Runtime without a second history authority. |
| `M6` | Existing Home subjects enter the `2^48` band; future subjects start from zeroed trigger rows. |
| `M7` | PostgreSQL/Python/protobuf integers, Redis 19-digit strings, and public/browser nullable canonical strings preserve signed `BIGINT`. |
| `M8` | Runtime Control refuses startup without the cutover marker; Helm renders the non-overlap scale-zero procedure. |
| `M9` | Runtime, Transfer, and Terminal use fresh v2 schemas without legacy readers. |
| `M10` | Empty-Valkey E2E proves Provider and Runner reconnect, stale Runner traffic rejection, and new work; existing durable broker, file, External Channel, and Scheduled Task recovery remains authoritative. |
| `M11` | Reference Compose Valkey has no volume and disables snapshot/AOF persistence. |
| `M12` | Migration, cancellation races, reset, stale heartbeat/report/result/revoke authority, durable invalid-grant rejection, maximum string values, deployment, clients, and real E2E have deterministic coverage. |

## Removal and Absence Evidence

Repository searches found:

- no Runtime coordination `register_connection` allocator API;
- no Runtime coordination generation-counter key helper;
- no Runtime coordination `INCR` or `PERSIST` path;
- no active legacy Runtime, Transfer, or Terminal namespace;
- no Redis counter import, generation fallback, dual write, or compatibility reader;
- no public/browser numeric connection-generation field;
- no reference Compose `valkeydata` volume or append-only persistence.

The only legacy counter namespace reference is the explicit Redis cutover test proving
that v2 state neither reads nor mutates it. Internal Python and protobuf connection
generations intentionally remain integers; the numeric-removal boundary applies to
Redis JSON and public/browser JSON.

## Spec Promotion

`docs/azents/spec/flow/agent-runtime-control.md` version 76 is the current authority
for durable generation allocation, one-shot volatile publication, empty-store
recovery, canonical generation strings, best-effort enrollment limiting, and the
strict Home rollout. Existing broker, live projection, file exchange, External
Channel, and Scheduled Task Specs already describe PostgreSQL-backed recovery and
Redis as notification, lock, or volatile projection state, so no contradictory
current authority remains.
