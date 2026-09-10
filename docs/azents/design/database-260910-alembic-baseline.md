---
title: "Alembic Baseline Consolidation Design"
created: 2026-09-10
implemented: 2026-09-10
tags: [database, migration, operations]
document_role: primary
document_type: design
snapshot_id: database-260910
---

# Alembic Baseline Consolidation Design

- Snapshot: `database-260910`
- Document reference: `database-260910/DESIGN`
- Requirements: [database-260910/REQ](../requirements/database-260910-alembic-baseline.md)
- Decisions: [database-260910/ADR](../adr/database-260910-alembic-baseline.md)

## Current Behavior and Gap

Azents has one linear Alembic head but retains 328 revision files. Fresh database
creation replays the entire graph, and migration tests preserve several historical
transition fixtures. All deployed databases are already recorded at the current
head, so the historical graph is no longer needed for deployment convergence.

## Architecture and Source of Truth

The schema produced by the pre-consolidation Alembic head is the consolidation
source of truth. The consolidated baseline is its deployable empty-database
representation, including PostgreSQL-specific types, defaults, constraints, and
indexes that may not be fully represented by SQLAlchemy autogeneration. The two
deterministic singleton rows produced by the historical graph are also part of the
fresh-database baseline state.

The checked-in `db-schemas/rdb/revision` file remains the startup target and keeps
the value `6b53a0a15d11`.

## Migration and Rollout

1. Generate an Alembic revision through the repository-supported Alembic command.
2. Assign the existing head identifier `6b53a0a15d11`.
3. Materialize the exact public schema produced by the pre-consolidation graph into
   the baseline, excluding Alembic's own version table.
4. Review the PostgreSQL enum, default, constraint, index, and dependency ordering.
5. Seed the current file-lifecycle settings and Runtime generation-cutover singleton
   rows that the historical graph creates on an empty database.
6. Delete every other revision file and every transition-specific migration test.
7. Update Living Spec code paths that name deleted migration files.
8. Verify graph invariants, base-to-head upgrade and downgrade, seed state, and
   schema equivalence against a database produced by the previous graph.

On existing deployments, startup reads `6b53a0a15d11` from both the revision file and
the database and skips Alembic upgrade. No production database mutation is part of
the rollout.

## Failure and Recovery

- If baseline verification differs from the pre-consolidation schema, the change
  does not ship until the baseline is corrected.
- If any deployment is discovered behind `6b53a0a15d11`, it must first be upgraded
  with the pre-consolidation release; the consolidated release does not recover that
  unsupported state.
- Repository rollback can restore the historical files, but database downgrade into
  those removed revisions is outside the supported rollout.

## Test Strategy

- Run the standard pytest-alembic single-head, upgrade, and up/down consistency
  checks against PostgreSQL.
- Create one database with the pre-consolidation graph and another with the
  consolidated baseline, then compare normalized public-schema catalogs.
- Run the Python formatter, linter, type checker, and relevant migration tests.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| 327 ancestor revision files | `database-260910/REQ-3`, `database-260910/ADR-D1` | Consolidated `6b53a0a15d11` baseline | Alembic versions directory | Exactly one revision file remains |
| Historical data-transition migration code | `database-260910/ADR-D2` | Deterministic current singleton seeds only; deployed data is already migrated | Removed ancestor revisions | Baseline contains no historical row transformation |
| Transition-specific migration tests | `database-260910/REQ-3`, `database-260910/ADR-D3` | Graph and schema-equivalence tests | `migration_tests/` | No test names a removed revision |
| Living Spec paths to deleted migrations | `database-260910/REQ-3` | Current model or baseline paths | Spec frontmatter | Spec review finds no stale code path |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One revision recreates the exact pre-consolidation head schema and deterministic empty-database seed state | `database-260910/REQ-1`, `database-260910/ADR-D2` | `derived` |
| M2 | The baseline reuses head `6b53a0a15d11` and existing deployments execute no DDL | `database-260910/REQ-2`, `database-260910/ADR-D1` | `decided` |
| M3 | Historical data transformations are omitted from the fresh-install baseline | `database-260910/ADR-D2` | `decided` |
| M4 | Historical revision tests are replaced by current graph and equivalence checks | `database-260910/REQ-3`, `database-260910/ADR-D3` | `decided` |

## Feasibility

- `REQ-1`: Feasible. The pre-consolidation graph can materialize an authoritative
  PostgreSQL schema snapshot and PostgreSQL-backed tests can validate the baseline.
- `REQ-2`: Feasible under the requester-confirmed fixed constraint that all
  deployments are at `6b53a0a15d11`.
- `REQ-3`: Feasible. Migration and spec references are repository-searchable and
  graph verification detects retained revision dependencies.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: 2026-09-10
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`
- Approved scope: consolidate the current Alembic graph into a single fresh-schema
  baseline while preserving the deployed head identifier and removing historical
  transition artifacts.
