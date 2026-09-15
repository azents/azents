---
title: "Operational Schema Baseline Design"
created: 2026-09-15
implemented: 2026-09-15
tags: [database, migration, reliability, ci]
document_role: primary
document_type: design
snapshot_id: database-260915
---

# Operational Schema Baseline Design

- Snapshot: `database-260915`
- Document reference: `database-260915/DESIGN`
- Requirements: [database-260915/REQ](../requirements/database-260915-operational-schema-baseline.md)
- Decisions: [database-260915/ADR](../adr/database-260915-operational-schema-baseline.md)

## Current Behavior and Gap

The repository contains a consolidated September 10 baseline followed by sixteen
forward revisions. Applying the graph to an empty PostgreSQL database succeeds, but
`alembic check` reports stale tables, indexes, nullability, constraints, and enum
definitions. The production database at the same head revision passes
`alembic check` with the deployed application revision.

## Architecture and Source of Truth

The new baseline is generated through the repository Alembic revision workflow and
retains revision ID `097a97177350`. Its schema SQL is derived from a read-only,
owner-free, privilege-free production public-schema dump. The dump is accepted only
after the deployed application reports no Alembic model drift.

The migration includes only schema DDL and deterministic singleton seed rows. It
does not contain production application rows, ownership, privileges, or credentials.

## Migration and Rollout

1. Capture the production public schema through read-only Kubernetes exec.
2. Verify the deployed application at revision `8da2953aebb6` reports no new Alembic
   operations against production.
3. Generate an Alembic revision template, assign revision `097a97177350`, and make it
   the only revision with `down_revision = None`.
4. Normalize the schema dump for migration execution by removing client-only dump
   controls and public-schema creation.
5. Add deterministic singleton inserts for fresh databases.
6. Generate a dependency-safe downgrade from the schema dump.
7. Normalize reflected foreign-key deferrability before Alembic's structural
   comparison while preserving it in the physical baseline fingerprint.
8. Remove intermediate migrations and transition-only tests.
9. Update Living Spec migration code paths to the new baseline.

Existing deployments already at `097a97177350` skip migration. Fresh databases run
the single baseline.

## Failure and Recovery

- If production does not pass `alembic check`, the dump is not accepted as a
  baseline.
- If a fresh database fails upgrade, downgrade, schema fingerprint comparison, or
  `alembic check`, the change does not ship.
- Databases behind `097a97177350` must upgrade with an older release before adopting
  this consolidated graph.
- No live database write is part of validation or rollout preparation.

## Test Strategy

- Run pytest-alembic single-head, base-to-head upgrade, model-definition-versus-DDL,
  and up/down consistency checks on PostgreSQL.
- Compare a normalized schema fingerprint from the new baseline with the captured
  production public schema. The fingerprint includes complete PostgreSQL constraint
  definitions, including deferrability.
- Verify the three deterministic singleton rows.
- Run backend Ruff, type checking, and the complete migration test suite.
- CI runs the migration suite whenever Python paths change; schema drift is a
  required failure, not an optional live test.

Product E2E is not the primary verifier because this change preserves runtime
behavior and changes only fresh-database construction and CI invariants. PostgreSQL
migration integration tests are the authoritative coverage.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| September 10 baseline and later intermediate revisions | `database-260915/ADR-D1` | Single `097a97177350` operational baseline | Alembic versions directory | Exactly one revision and one head |
| Transition-only migration tests | `database-260915/REQ-2`, `database-260915/ADR-D1` | Current-schema invariants | `migration_tests/test_alembic.py` | No removed revision references |
| Stale Living Spec migration paths | `database-260915/REQ-1` | New baseline path | `docs/azents/spec/**/*.md` | Spec path search finds no deleted migration |
| Missing metadata drift gate | `database-260915/REQ-4`, `database-260915/ADR-D3` | pytest-alembic model-definition check | Migration CI suite | Deliberate metadata drift fails the test |
| Unmodeled historical FK timing | `database-260915/ADR-D4` | Physical baseline fingerprint plus narrow Alembic comparison normalization | Migration environment | FK structure/action drift remains visible and physical timing remains fingerprinted |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One baseline retains revision `097a97177350` with no parent | `database-260915/REQ-2`, `database-260915/ADR-D1` | decided |
| M2 | Read-only production schema plus successful model drift check defines accepted DDL | `database-260915/REQ-1`, `database-260915/ADR-D2` | decided |
| M3 | Fresh baseline seeds only deterministic code-owned singleton rows | `database-260915/REQ-3`, `database-260915/ADR-D2` | required |
| M4 | PostgreSQL migration CI runs model-definition-versus-DDL validation | `database-260915/REQ-4`, `database-260915/ADR-D3` | required |
| M5 | Preserve physical FK deferrability while normalizing only that option in model comparison | `database-260915/ADR-D4` | decided |

## Feasibility

- `REQ-1`: Feasible. Production at the deployed application revision passes
  `alembic check`, and its public schema is available as an owner-free schema dump.
- `REQ-2`: Feasible. Production already records `097a97177350`; retaining that head
  avoids live DDL.
- `REQ-3`: Feasible. Existing migration tests identify the required singleton rows
  and values.
- `REQ-4`: Feasible. pytest-alembic exposes the model-definition-versus-DDL
  invariant using the existing PostgreSQL fixtures.

## Design Approval

- Mode: `Autonomous execution of requester-confirmed direction`
- Decision owner: requester
- Approved on: 2026-09-15
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`
- Material scope: replace the stale migration graph with a production-equivalent
  current-head baseline and require Alembic drift detection in CI.
