---
title: "Repository Session Capabilities Decisions"
created: 2026-10-04
tags: [repository, concurrency, session-capabilities]
document_role: primary
document_type: adr
snapshot_id: sessioncaps-261004
---

# Repository Session Capabilities Decisions

- Snapshot: `sessioncaps-261004`
- Authority: [Requirements](../requirements/sessioncaps-261004-repository-session-capabilities.md)

## D1. Method-level capability protocols

Use `ReadSession` with `read_session`, and `WriteSession` extending it with
`write_session`. These are explicit requester decisions. Do not bind an entire
mixed repository to one write-only session type or weaken its writes to a read
type. Payload/result generics remain independent.

## D2. Private concrete session and database read-only scope

Concrete wrappers retain one private SQLAlchemy session; read/write properties
return that same object. Factories apply PostgreSQL connection characteristics.
Read-only scopes are not a SQL sandbox or replica router: raw SQLAlchemy access
and PostgreSQL advisory locks remain separate enforcement concerns.

## D3. Mechanical migration before lock removal

Preserve existing SQL, locking and transaction lifetimes in the first PR.
Read-named methods that lock or mutate remain write-capable. Existing owner-fenced
scopes remain write scopes. Remove neither locks nor admission semantics here.
This separates interface migration failures from later concurrency changes.
