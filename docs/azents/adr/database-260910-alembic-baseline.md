---
title: "Alembic Baseline Consolidation Decision"
created: 2026-09-10
tags: [database, migration, operations]
document_role: primary
document_type: adr
snapshot_id: database-260910
---

# Alembic Baseline Consolidation Decision

- Snapshot: `database-260910`
- Document reference: `database-260910/ADR`
- Requirements: [database-260910/REQ](../requirements/database-260910-alembic-baseline.md)

## Context

The current graph has 328 Alembic revisions and every deployed database is already
recorded at head `6b53a0a15d11`. Process entrypoints compare the checked-in revision
file with `alembic current` and run an upgrade only when they differ.

## Decisions

### database-260910/ADR-D1. Reuse the deployed head identifier for the baseline

Replace the implementation of revision `6b53a0a15d11` with a complete base-to-
current-schema migration and set its `down_revision` to `None`.

This keeps existing deployed databases current without a production stamp operation
or a bridge release. Empty databases execute the replacement baseline because they
have no Alembic revision marker.

Rejected alternatives:

- **Allocate a new baseline revision:** existing deployments would require an
  explicit stamp or would fail to resolve the removed current revision.
- **Use a two-release bridge:** it preserves historical revision immutability but
  adds a deployment cycle that is unnecessary when every deployment is already at
  the same head and the requester explicitly authorized consolidation.

Risk:

- A database behind `6b53a0a15d11` can no longer upgrade through the deleted graph.
  This is accepted by `database-260910/REQ`.

### database-260910/ADR-D2. Treat the baseline as a fresh-install schema

The baseline creates current tables, PostgreSQL enums, constraints, indexes, and
server defaults directly. It also creates the two deterministic singleton rows that
an empty current database receives from the historical graph. It does not replay
historical row transformations.

Historical row transformations have already run on all deployed databases. Fresh
databases have no historical rows to transform, but they still require the current
file-lifecycle settings and Runtime generation-cutover singleton state.

### database-260910/ADR-D3. Remove transition-specific migration tests

Delete tests whose fixtures and assertions target removed intermediate revisions.
Retain graph-level verification and add schema-equivalence coverage for the
consolidated baseline.

The removed tests no longer describe a reachable migration path after consolidation.
