---
title: "Ephemeral Redis Coordination Authority Phase 1 Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [runtime, redis, postgresql, migration, plan]
---

# Ephemeral Redis Coordination Authority Phase 1 Plan

## Phase Execution Plan

- Phase: `1 — durable generation authority foundation`
- Branch/base: `feature/redis-ephemeral-1-authority-foundation` → `main`
- PR boundary: Add the approved documentation snapshot and an unused additive PostgreSQL generation-authority foundation. The activation seed, future-subject triggers, cutover marker row, Runtime caller cutover, and new Redis namespace remain Phase 2.
- Inputs: Confirmed `redis-260907/REQ`, accepted `ADR-D1` through `ADR-D4`, approved Design revision `2`, and the feature implementation plan.
- Deliverables: Generation-authority and cutover-marker RDB models, generated additive Alembic migration with empty authority tables, connection-generation `BIGINT` widening, database-only repository primitives, signed-`BIGINT` exhaustion enforcement, and focused migration/repository tests.
- Non-goals: No activation seed/trigger/marker row, Runtime Control caller cutover, Redis candidate or namespace change, deployment change, Valkey change, public/protobuf/TypeScript schema change, Living Spec promotion, or implementation marker.
- Interfaces: Repository primitives read the required subject row, allocate a new generation, verify current high-water, accept the current generation, and fail closed on a missing row or `2^63 - 1` exhaustion. They perform database work only and accept an explicit session.
- Approved Design mechanisms: `M1`, storage portion of `M7`, repository portion of `M12`.
- Authority references: `redis-260907/REQ-2`, `REQ-4`, `REQ-8`; `redis-260907/ADR-D1`, `ADR-D3`, `ADR-D4`; `redis-260907/DESIGN` revision `2`.
- Design delta: `None`
- Removal obligations: Widen the three existing persisted connection-generation columns from `INTEGER` to `BIGINT`. Do not remove the Redis allocator until Phase 2.
- Absence verification: Schema inspection proves only connection-generation columns changed; the foundation migration contains no subject seed, trigger, marker row, Redis access, or external call; no Runtime Control or coordination caller uses the new repository yet.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Snapshot and plans | `/root` | `docs/azents/requirements/**`, `docs/azents/adr/**`, `docs/azents/design/**`, feature files in `docs/azents/plans/**` | Approved Design | Tracked authority and execution scope | Docs snapshot validation through pre-commit, `git diff --check` |
| RDB model and data contract | `/root` | `python/apps/azents/src/azents/rdb/models/runtime_connection_generation.py`, `python/apps/azents/src/azents/core/enums.py`, generation repository data modules | None | Per-kind/per-subject high-water and accepted evidence over positive signed `BIGINT` | Ruff, type check, model/repository tests |
| Foundation migration | `/root` | `python/apps/azents/db-schemas/rdb/**`, focused migration test | RDB model | Generated additive revision, `BIGINT` widening, empty authority/cutover tables | Migration upgrade tests, schema assertions |
| Repository primitives | `/root` | `python/apps/azents/src/azents/repos/runtime_connection_generation/**` | Model and migration contract | Read, allocate, preflight, accept, exhaustion, and integrity methods without lazy row creation | Concurrency/CAS/exhaustion/missing-row tests |

- Integration order: synchronize approved documents and plans → correct model/data constraints → correct generated foundation migration → correct repository primitives → update focused tests → run Phase 1 validation.
- Independent review: `redis-implementation-reviewer` reviews the stable Phase 1 diff read-only against `redis-260907/REQ`, ADR-D1 through D4, Design revision `2`, and this phase contract. Review criteria are schema safety, signed-`BIGINT` exhaustion, subject-row integrity, transaction-only repository behavior, no premature activation, required removal boundary, and no unauthorized mechanism. Output is prioritized file/line findings or explicit approval.
- Final validation: `git diff --check`; pre-commit documentation and snapshot validation; Ruff format/check; configured Python type checker; focused generation repository tests; migration authority tests; repository search proving no Redis/external access from migration/repository code.
- Scope-drift check: Every change maps to `M1`, the storage portion of `M7`, or the repository portion of `M12`; no activation seed, future-subject trigger, cutover marker row, new source of truth, compatibility mode, Runtime caller change, or external call inside a DB transaction is permitted.
- Context checkpoint: Record migration revision, schema objects, repository interface, test commands/results, removal evidence, remaining Phase 2 integration, risks, and blockers before commit and PR update.
