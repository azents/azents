---
title: "Ephemeral Redis Coordination Authority Phase 1 Plan"
created: 2026-09-07
tags: [runtime, redis, postgresql, migration, plan]
---

# Ephemeral Redis Coordination Authority Phase 1 Plan

## Phase Execution Plan

- Phase: `1 — durable generation authority foundation`
- Branch/base: `feature/redis-ephemeral-1-authority-foundation` → `main`
- PR boundary: Add the approved documentation snapshot and an unused additive PostgreSQL generation-authority schema with migration and repository evidence. The migration creates no cutover marker or subject seed, and Runtime registration continues using the legacy Redis allocator until Phase 2.
- Inputs: Confirmed `redis-260907/REQ`, accepted `ADR-D1` through `ADR-D4`, approved Design revision `2`, and the feature implementation plan.
- Deliverables: Generation-authority and cutover-marker RDB models, generated additive Alembic migration with empty authority tables, connection-generation `BIGINT` widening, database-only repository primitives, and focused migration/repository tests.
- Non-goals: No Runtime Control caller cutover, Redis candidate or namespace change, JSON contract change, deployment change, Valkey change, Living Spec promotion, or implementation marker.
- Interfaces: Repository primitives allocate a new generation, verify the current high-water, accept the current generation, and fail closed on missing legacy rows or exhaustion. They perform database work only and accept an explicit session.
- Approved Design mechanisms: `M1`, storage portion of `M7`, repository portion of `M12`.
- Authority references: `redis-260907/REQ-2`, `REQ-4`, `REQ-8`; `redis-260907/ADR-D1`, `ADR-D3`, `ADR-D4`; `redis-260907/DESIGN` revision `2`.
- Design delta: `None`
- Removal obligations: Widen the three existing persisted connection-generation columns from `INTEGER` to `BIGINT`. Do not remove the Redis allocator until Phase 2.
- Absence verification: Schema inspection proves only connection-generation columns changed; no Runtime Control or Redis behavior references the new repository yet; migration contains no Redis access or external call.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Snapshot and plans | `/root` | `docs/azents/requirements/**`, `docs/azents/adr/**`, `docs/azents/design/**`, feature files in `docs/azents/plans/**` | Approved Design | Tracked authority and execution scope | Snapshot validator, docs frontmatter, `git diff --check` |
| RDB model and data contract | `/root` | `python/apps/azents/src/azents/rdb/models/**`, new generation repository/data modules | None | Per-kind/per-subject high-water and accepted evidence | Ruff, type check, model/repository tests |
| Migration | `/root` | `python/apps/azents/db-schemas/rdb/**` | RDB model | Generated additive revision, `BIGINT` widening, empty authority/cutover tables | pytest-alembic migration suite, focused migration assertions |
| Repository primitives | `/root` | new repository module and focused tests | Model and migration contract | Allocate, preflight, accept, read/integrity methods | Concurrency/CAS/exhaustion tests |

- Integration order: finalize documents → define model/data contract → generate migration → implement repository primitives → add focused tests → run full Phase 1 validation.
- Independent review: `hardtack` reviews the Phase 1 PR for Requirements/ADR/Design traceability, schema correctness, migration safety, subject identity and retention, transaction-only repository behavior, and absence of premature Runtime/Redis activation.
- Final validation: `git diff --check`; docs snapshot validator; Ruff format/check; configured Python type checker; focused model/repository tests; pytest-alembic migration suite; repository search proving no Redis access from migration/repository code.
- Scope-drift check: Every change maps to `M1`, `M7`, or `M12`; no cutover marker row, subject seed, new source of truth, compatibility mode, Runtime caller change, or external call inside a DB transaction is permitted.
- Context checkpoint: Record migration revision, schema objects, repository interface, test commands/results, removal evidence, remaining Phase 2 integration, and any blocker before commit and PR creation.
