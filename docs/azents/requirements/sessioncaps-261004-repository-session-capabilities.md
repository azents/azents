---
title: "Repository Session Capabilities Requirements"
created: 2026-10-04
tags: [repository, concurrency, session-capabilities]
document_role: primary
document_type: requirements
snapshot_id: sessioncaps-261004
---

# Repository Session Capabilities Requirements

- Snapshot: `sessioncaps-261004`
- Reference: `sessioncaps-261004/REQ`

## Primary System Outcome

Repository method contracts expose whether an operation requires only read access
or also write/locking access. Callers provide an appropriate concrete session
without changing existing operation behavior during the initial migration.

## Requirements

### REQ-1. Explicit read and write capabilities

Read methods require a protocol exposing `read_session`. Mutation and locking
methods require that capability plus `write_session`. Classification follows
actual operations and their callees, not method names.

**Acceptance criteria**

- All repository session arguments use the appropriate capability.
- A read-only implementation cannot satisfy a write-method argument.
- Conditional locking and mutation paths retain write-capable contracts.

### REQ-2. Concrete caller scopes

Read-only scopes enforce PostgreSQL read-only mode. Read/write scopes may also
satisfy read contracts when composition requires one transaction.

**Acceptance criteria**

- Concrete implementations retain a private underlying session.
- Read/write attributes refer to the same session and transaction.
- Normal read examples use read-only scopes; the database rejects ordinary
  writes and row locks there.
- Connection modes do not leak through pool reuse.

### REQ-3. Behavior-preserving first migration

Migrate every repository and affected caller/test mechanically.

**Acceptance criteria**

- SQL, existing locks, transaction boundaries and observable outcomes remain.
- Existing mixed transaction scopes remain mixed scopes.
- No raw-session forwarding compatibility path bypasses the new contracts.
- Type checks, existing tests and independent review verify integration.

## Non-Goals

Lock removal, static-prompt lifecycle correction and MCP refresh-frequency
changes are subsequent work. This snapshot does not authorize deployment,
merging, new API behavior, replica routing or a new cache authority.

## Confirmation

The requester confirmed the foundation sample and private-session correction,
then explicitly requested this behavior-preserving repository-wide migration on
2026-10-04. Implementation delegation was requested for this first PR only.
