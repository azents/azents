---
title: "Repository-owned Database Transactions"
created: 2026-09-08
tags: [backend, architecture, database, concurrency]
document_role: primary
document_type: adr
snapshot_id: transaction-260908
---

# Repository-owned Database Transactions

This snapshot records the requester's fixed transaction decisions for
[transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md).
It does not change product authorization, lifecycle, delivery, or retry policy.

## D1. Repository-owned, database-only transaction lifetimes

- Reference: `transaction-260908/ADR-D1`
- Decision owner: requester
- Accepted: 2026-09-08
- Authority: `transaction-260908/REQ-1`, `transaction-260908/REQ-2`

Application transactions begin and finish inside the repository layer. A
database-only composing repository combines narrower repositories when multiple
records must change atomically. Services orchestrate completed database operations
and external work; neither services nor injected application callbacks receive a
live transaction.

The initial implementation keeps narrow, session-taking query primitives where
they are needed by composing repositories. Their presence does not authorize
application callers to manage sessions. The completed migration removes such
callers from services, routes, tools, workers, and Runtime orchestration.

Rejected alternatives are service-owned transactions with renamed session
types, general transaction callbacks, and moving mixed-I/O service classes
wholesale into repositories. Each preserves the original lifetime defect.

Read transactions count. A lexical session context is not sufficient evidence:
inspection follows implicit starts, commit/rollback boundaries, and subsequent
queries that begin a new transaction.

## D2. Preserve database authority across external work

- Reference: `transaction-260908/ADR-D2`
- Decision owner: requester; derived implementation obligation
- Accepted: 2026-09-08
- Authority: `transaction-260908/REQ-2`, `transaction-260908/REQ-3`

External work runs between completed database operations. Any mutation relying on
authority observed before that work revalidates its existing authorization,
identity, generation, version, conflict, and terminal-state predicates inside its
final database transaction. Existing atomic groups and database lock ordering
remain intact. Existing conditional updates and durable operation identities
remain the source of truth.

Merely committing before an external call is not adequate when it allows stale
authority to authorize a later mutation. Splitting related writes into
independently committed repository calls is likewise rejected.

No new retry loop, provider effect, delivery guarantee, or persisted lifecycle is
authorized by this refactor. A path needing such a change must be reported rather
than silently assigned new semantics.

## D3. Prefer no cross-I/O lock; report unavoidable exceptions

- Reference: `transaction-260908/ADR-D3`
- Decision owner: requester
- Accepted: 2026-09-08
- Authority: `transaction-260908/REQ-5`

First use existing idempotency, conditional database mutation, generation fences,
and database-only atomic operations to avoid locks spanning external work.
Distributed coordination is a last resort when a concrete invariant cannot be
preserved without it. Redis remains optional and an in-memory fallback is
mandatory.

An exception must identify its path, protected invariant, rejected lock-free
alternatives, ownership and release lifecycle, cancellation behavior, and behavior
without Redis or after Redis loss. Process-local memory coordination cannot be
claimed to exclude work in other processes; database correctness must survive that
limitation. Adding a lock that depends on Redis for correctness is not authorized.

This decision authorizes evaluation of unavoidable exceptions, not blanket
introduction of distributed locks. None is introduced by the initial design.
External I/O remains forbidden inside database transactions in all cases.

### D3 clarification: standalone memory implementation

The requester clarified on 2026-09-08 that memory fallback means a Redis-free
single standalone deployment, such as a development server. It does not mean
automatically replacing distributed coordination with independent process-local
locks when Redis fails in a multi-process deployment. Exception evaluation must
distinguish those deployment modes and preserve safety during distributed
coordination loss; no new outage fallback behavior is authorized.
