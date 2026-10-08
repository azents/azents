---
title: "Repository Session Capabilities Design"
created: 2026-10-04
tags: [repository, concurrency, session-capabilities]
document_role: primary
document_type: design
snapshot_id: sessioncaps-261004
---

# Repository Session Capabilities Design

- Snapshot: `sessioncaps-261004`
- Revision: 1
- Authority: [Requirements](../requirements/sessioncaps-261004-repository-session-capabilities.md)
  and [decisions](../adr/sessioncaps-261004-repository-session-capabilities.md).

## Mechanisms

### M1. Structural capability contracts

Define protocols in `rdb/session_capabilities.py`. Read methods use
`session.read_session` for SQLAlchemy reads. Writes and row locks use
`session.write_session`. Pass the capability wrapper itself to repository
collaborators. A read/write implementation also satisfies the read protocol.

### M2. Scope factories and private wrappers

Construct `ReadOnlySession(session=...)` and `ReadWriteSession(session=...)` around
private storage. Factories use SQLAlchemy PostgreSQL read-only characteristics
before the first query. The existing generic session-manager protocol remains
covariant. Scope exit commits on success and rolls back on error/cancellation.
Preserve explicit intermediate commits and subsequent transactions; do not put
the whole scope in a forced `session.begin()` context.

### M3. Mechanical repository and caller migration

Classify every method using SQL, ORM mutation, transaction-control calls,
conditional locking and downstream capability requirements. Retain write
managers for existing mixed or owner-fenced compositions. New independent read
scopes can use read-only factories. Adjust captured state handles and VFS
protocols without exposing commit or write forwarding on a read-only wrapper.

## Verification and Removal

Remove raw `AsyncSession` repository-argument contracts and raw-yielding caller
factories at the migrated boundary, not SQLAlchemy infrastructure callbacks.
Verify absence through inventory, types and complete caller checks. Preserve
all existing lock sites and SQL semantics in this phase.

Use actual PostgreSQL tests for read-only DML/row-lock rejection, same-transaction
composition, rollback and pool restoration. Run existing repository/service
tests and required E2E for unchanged product behavior, including execution-owner
and lifecycle concurrency tests. Structural typing does not prove runtime
transaction identity or block arbitrary mode-changing SQL.

## Design Authority

Revision 1 has M1–M3: M1 is required by REQ-1/ADR D1; M2 is decided by
REQ-2/ADR D2; M3 is required by REQ-3/ADR D3. These record the requester-confirmed
foundation and first-PR migration, not authority for later lock removal.

## Removal and Replacement

Replace raw repository session-argument contracts with capability protocols and
raw-yielding migrated factories with private concrete wrappers. Replace incompatible
VFS/captured-state session bounds without removing payload/result generics.
The boundary is this first PR; inventory/type/caller checks establish absence.
No SQL, lock, schema, persisted-state, configuration or public API removal is
authorized here.

## Test Strategy

Required product E2E is the unchanged-behavior gate. Existing repository/service
tests and actual PostgreSQL tests provide transaction/locking evidence that UI
tests alone cannot expose. Use existing local container fixtures, no live
credentials or deployment. Record exact commands, collection coverage and CI SHA;
optional fixture skips do not count as passing a required verification.

## Design Approval

This records the requester-approved foundation shape and mechanical first-PR
scope. It does not approve a new lock-removal mechanism. New material behavior
must not be added while resolving migration type errors.
Mode: requester-directed implementation; owner: requester; date: 2026-10-04.
Revision 1 authority set: M1–M3 under REQ-1–REQ-3 and ADR D1–D3.
