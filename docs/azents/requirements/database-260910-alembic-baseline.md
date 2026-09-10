---
title: "Alembic Baseline Consolidation Requirements"
created: 2026-09-10
implemented: 2026-09-10
tags: [database, migration, operations]
document_role: primary
document_type: requirements
snapshot_id: database-260910
---

# Alembic Baseline Consolidation Requirements

- Snapshot: `database-260910`
- Document reference: `database-260910/REQ`

## Problem

The RDB migration graph contains hundreds of historical revisions even though every
deployed Azents database has already reached the current head and schema rollback is
not an operational requirement. The accumulated history increases maintenance and
fresh-database setup complexity without serving a remaining deployment transition.

## Primary Context

### Primary System Outcome

Azents has one Alembic baseline that creates the complete current RDB schema on an
empty database, while databases already recorded at the current head continue
running without executing schema changes.

## Supporting Scenarios or Effects

- Migration verification no longer carries tests that exercise removed historical
  transitions.
- Future schema changes continue from the consolidated baseline as ordinary Alembic
  revisions.

## Goals

- Replace the existing migration graph with one current-schema baseline.
- Preserve startup compatibility for every currently deployed database.
- Verify that the consolidated baseline produces the same schema as the pre-
  consolidation migration graph.

## Non-Goals

- Preserve downgrade paths into removed historical schemas.
- Support a deployed database that is behind the current Alembic head.
- Modify production database data or revision markers as part of this repository
  change.

## Requirements

### REQ-1. Complete fresh-database schema

An empty supported PostgreSQL database must reach the current Azents RDB schema by
applying one Alembic revision.

**Acceptance criteria**

- Alembic reports exactly one revision and one head.
- Upgrading from base to head succeeds on an empty PostgreSQL database.
- The resulting schema is equivalent to the schema produced by the migration graph
  immediately before consolidation.

### REQ-2. Existing deployment compatibility

A deployed database already recorded at the current head must remain current after
the migration graph is consolidated.

**Acceptance criteria**

- The consolidated baseline retains the current deployed head revision identifier.
- Existing startup revision checks observe no revision mismatch and execute no DDL.

### REQ-3. Historical migration removal

Migration-only artifacts that depend on removed intermediate revisions must be
removed or updated to describe and verify the consolidated graph.

**Acceptance criteria**

- No retained migration or migration test references a removed revision.
- Current Living Spec code paths do not point at deleted migration files.

## Fixed Constraints

- Every deployed Azents database is already recorded at the current Alembic head
  `6b53a0a15d11`.
- Schema rollback into an intermediate historical revision is not required.
- The repository change does not write to a production database.

## Open Assumptions

- Any unpublished branch that adds a migration will rebase onto the consolidated
  baseline before merge.

## Confirmation

Confirmed by the requester on 2026-09-10 before implementation began.
