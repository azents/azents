---
title: "Toolkit Friendly Identifiers Phase 1 Foundation Persistence"
created: 2026-10-01
updated: 2026-10-01
tags: [toolkit, backend, database, migration, testing]
---

# Toolkit Friendly Identifiers Phase 1 Foundation Persistence

## Phase Execution Plan

- Phase: `1/3 Foundation namespace persistence`
- Branch/base: `feature/toolkit-identifiers-1-foundation-data` → `origin/main`
- PR boundary: add and populate namespace authority without changing current Public API,
  Web, duplicate-Slug, or runtime-prefix behavior
- Inputs: confirmed `toolkit-261001/REQ`, accepted `toolkit-261001/ADR`, approved
  `toolkit-261001/DESIGN` revision 1, current Toolkit Spec, current migration head
  `4550a9c9083a`
- Deliverables: namespace reservation and sequence schema; deterministic existing-row
  backfill; repository domain models and allocator; write-path allocation, reuse, and
  retirement; current duplicate rejection and Slug indexes preserved
- Non-goals: optional Name/Slug APIs, Web placeholders, dropping unique indexes, removing
  conflict errors, runtime prefix cutover, Tool Search/event changes, Living Spec
  promotion, live deployment, or merge
- Interfaces: ToolkitConfig Name/Slug storage, AgentToolkit attachment identity,
  ToolkitConfig revisioning, current Public API and generated clients, current runtime
  `ToolkitBinding.slug` behavior, credential and authorization boundaries remain fixed
- Approved Design mechanisms: `M3, M4, M7`
- Authority references: `toolkit-261001/REQ-3`, `REQ-4`, `REQ-5`;
  `toolkit-261001/ADR-D2`, `ADR-D3`, `ADR-D4`; approved Design M3, M4, M7; current
  Toolkit Spec; repository transaction and generated-migration constraints
- Design delta: `None`
- Removal obligations: `None`; this Foundation phase intentionally retains the old
  runtime Slug-prefix authority, duplicate conflict paths, and Slug indexes until phase 2
  and phase 3 activate their approved replacements
- Absence verification: prove no Public API/OpenAPI/Web/runtime-source behavior changed;
  schema inspection proves current Slug indexes remain; repository search confirms
  conflict paths remain reachable

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved snapshot and plans | `/root` | `docs/azents/{requirements,adr,design,plans}/**`, generated `docs/azents/INDEX.md` | approved revision 1 | committed implementation authority and phase contract | snapshot validator and docs index check |
| RDB schema and migration | `/root` | `python/apps/azents/src/azents/rdb/models/toolkit.py`, `python/apps/azents/db-schemas/rdb/**` | M3, M4, current migration head | reservation/sequence tables, constraints, FK behavior, deterministic backfill | generated Alembic revision, migration-focused tests, schema assertions |
| Namespace repository | `/root` | `python/apps/azents/src/azents/repos/toolkit/**` or one bounded namespace repository module | RDB schema | typed reservation/sequence models, active lookup, allocation, retirement, parity reads | repository tests including cross-base collision and no-reuse |
| Shared Toolkit transactions | `/root` | `python/apps/azents/src/azents/repos/toolkit_operations/**` | namespace repository | attach reuse/allocation, shared Slug-update reallocation, delete retirement, stable Agent lock order | operation repository and concurrency tests |
| Agent-owned Toolkit transactions | `/root` | `python/apps/azents/src/azents/repos/toolkit_operations/owned.py`, related data/tests | namespace repository | create allocation, Slug-update retirement/reallocation, delete retirement, disable/enable stability | owned operation and service transaction tests |
| Foundation validation | `/root` | affected backend tests only | integrated phase diff | proof that namespace state is complete while product behavior is unchanged | focused pytest, Ruff, format check, `ty`, migration upgrade/backfill evidence |

- Integration order: models and generated migration → typed repository and allocator →
  shared operations → Agent-owned operations → migration/backfill and concurrency tests →
  integrated quality checks → independent review
- Independent review: `/root/toolkit-identifiers-reviewer`; root requests a read-only
  review only after all workstreams are integrated and the diff is stable, covering M3,
  M4, M7, data-loss/concurrency risk, migration correctness, transaction boundaries,
  retained compatibility behavior, and unauthorized runtime/API changes
- Final validation: root-owned migration generation and upgrade/backfill tests; focused
  Toolkit repository/operation/service tests; `uv run ruff check`, `uv run ruff format
  --check`, `uv run ty check --error-on-warning`; docs snapshot/index checks; repository
  searches proving indexes/conflict paths/current API contracts remain
- Scope-drift check: M3, M4, and phase-1 portions of M7 must be complete; M1, M2, M5, M6,
  M8 behavior must not be activated; no lazy runtime allocation, compatibility fallback,
  administrator namespace field, live action, or new source of truth may appear
- Context checkpoint: approved authority is committed on this branch; implementation is
  unstarted; current shared and owned operation repositories already own complete
  transactions and Agent locking; current runtime continues asserting unique effective
  Slugs; largest risks are backfill SQL correctness, retirement semantics under Toolkit
  deletion, cross-base namespace collisions, and deadlocks during shared Slug updates
