---
title: "Repository-owned Database Transactions Design"
created: 2026-09-08
tags: [backend, architecture, database, concurrency]
document_role: primary
document_type: design
snapshot_id: transaction-260908
---

# Repository-owned Database Transactions Design

## Intent and Current Evidence

Implement [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
under the fixed decisions in
[transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md).
The primary outcome is repository-owned database-only transaction lifetimes, not
an import-only cleanup.

The initial service scan found 700 lexical session contexts in 109 files. This
is a discovery count, not a verified violation count. The inventory additionally
covers Engine, Runtime, Worker, CLI, other applications, shared libraries,
scripts, test substrate, and TypeScript database entry points.

Two concrete priority paths are:

- Session title generation reads Agent/model integration state and invokes OAuth
  freshness handling before the read transaction ends. Conditional token refresh
  performs HTTP and separate persistence transactions.
- Session Project registration reads Session/access state and performs Runtime
  resolution and directory validation while the transaction remains open.
  Its helper calls and Skill invalidation paths also need lifetime inspection.

The configured session manager commits on normal context exit, rolls back on
exceptions, and closes its session. Existing explicit commits can end a
transaction before the surrounding context exits; later queries can start one
again. Coverage must record actual boundaries.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Domain-specific database-only repositories own complete transaction lifetimes and compose narrower repositories for atomic operations. | REQ-1; ADR-D1 | required |
| M2 | Services perform external I/O only between completed repository operations. | REQ-2; ADR-D1 | required |
| M3 | Final mutations retain atomic groups and revalidate existing authority predicates after external work. | REQ-3; ADR-D2 | derived |
| M4 | Full entrypoint and indirect-call coverage, explicit exclusions, regression checks, and bounded PR delivery. | REQ-4 | required |
| M5 | Avoid cross-I/O locks and maintain a reported exception ledger; no new distributed lock is introduced without concrete necessity and optional-Redis correctness evidence. | REQ-5; ADR-D3 | required |

All short authority references in this document belong to `transaction-260908`.
Class names, module boundaries within each domain, DTO names, and test fixture
composition are local implementation details, not new material decisions.

## Architecture and Interfaces

### Database boundaries

A domain operation repository receives the session factory and its narrow query
repositories through dependency injection. Each public operation accepts typed
domain input and returns detached data or a typed domain result. It opens and
resolves its own transaction before returning.

Atomic multi-repository work shares one session only inside the repository
boundary. Existing query primitives remain available to those repository
compositions; applications stop passing sessions to them. Repository methods may
perform pure validation and projection but may not call services, provider
clients, Runtime operations, Redis, brokers, filesystem APIs, or arbitrary
application callbacks.

When extraction moves a shared data/result type, update callers to its canonical
defining module. Do not introduce compatibility re-exports or general dispatch
wrappers to preserve the obsolete ownership interface.

### External work

The application service obtains completed database snapshots, performs external
work, and invokes an explicit final database operation when needed. An existing
durable operation identity remains the retry/idempotency authority. No transaction
is kept open merely to retain a Python object or to serialize external work.

For title generation, repository operations load the eligible generation,
Agent/model selection and integration, check current generation for retries, and
conditionally replace the initial title. OAuth freshness and model calls execute
outside those transactions. Provider title projection remains after successful
database completion; manual-title protection remains unchanged.

For Project operations, repository operations validate Session membership and
database path conflicts, and finalize registry/preset/catalog changes atomically.
Runtime target resolution and filesystem checks occur between those operations.
Finalization checks current Session access, working-folder binding, target
authority, and cleanup/path conflicts using the existing domain predicates.
Skill invalidation currently opens a nested database-only Toolkit State
transaction; it is not Redis or Runtime I/O. Extract its database mutation for
repository composition while preserving deletion failure semantics. Runtime Skill
projection remains outside database transactions. Do not classify an asynchronous
store call as external I/O without following its concrete implementation.

Other domains follow the same ownership contract, with exact atomic groups and
lock order recorded in their coverage evidence before extraction.

## Data, Security, and Lifecycle

No database schema, public request/response shape, event format, configuration
mode, or provider protocol changes are planned. Existing repository DTOs are
preferred to live ORM objects.

Authorization checks remain attached to the same operation. No expensive Runtime
work is initiated before existing access checks succeed. A preflight authorization
result alone does not authorize final mutation after external work.

Preserve existing identity/version fences, commit order, cancellation propagation,
retry bounds, terminal state checks, and lock order. Error results that previously
rolled back must not become partially committed. A caught error inside a
commit-on-exit manager needs explicit rollback or an equivalent narrow exception
boundary when earlier writes must be abandoned.

## Coverage and Delivery

Inventory application entry points and reachable helpers, including injected
callbacks, aliases, implicit transactions, nested factories, and post-commit
restarts. Each entry records area, path, enclosing callable, session boundaries,
external effects, atomic group, disposition, remediation, and verification.

Use explicit dispositions: confirmed ownership violation, confirmed active-
transaction external I/O, evidence-backed exclusion, corrected, or investigation
remaining. Do not promote a lexical scan or an uninspected callee to complete
coverage. Repository primitives, RDB infrastructure, migrations, generated code,
test setup, and read-only diagnostics are classified separately.

Prioritize confirmed external-I/O overlaps, then complete ownership migration by
bounded domain slices. A partial PR does not close the overall issue. Preserve an
exception ledger even when its result is that no new cross-I/O lock was necessary.
Report actual checks and residual work for each slice.

## Failure, Rollout, and Operations

Deliver normal code PRs without applying live infrastructure or migrations.
Rollback is code rollback; no new persistent state or configuration requires
conversion. Do not merge without requester authorization.

External failure must not leave uncommitted database work open. Preserve current
best-effort versus fatal behavior and post-commit publication ordering. Do not add
an outbox, retry policy, lock lease, or fallback merely to make extraction easier.
Any invariant that cannot be preserved by the fixed mechanisms is an explicit
exception report.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement / remaining authority | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Application-owned sessions and transaction control | REQ-1; ADR-D1 | Completed domain repository operations | Each migrated domain; repository-wide at completion | Imports, transaction entrypoints, caller and callback inventory |
| Active transaction spanning external effects | REQ-2; ADR-D1 | External work between repository calls | Every confirmed reachable path | Call-path review and transaction-state regression tests |
| Session-taking service helpers and mixed-I/O transaction callbacks | REQ-1, REQ-2 | Database-only repository composition plus explicit application orchestration | All callers in each migrated slice | Symbol/caller search and type checking |
| Tests that only reproduce service-owned session wiring | REQ-4 | Repository atomicity tests and service external-I/O boundary tests | Updated operation interfaces | Targeted regression suite and CI |

No executed migration, generated client, durable model, public API, or
configuration removal is currently needed; evidence so far concerns internal
ownership. Update this analysis if complete inventory reveals another surface.

## Test Strategy

Existing E2E flows are primary product-contract evidence: session creation/input
and title projection, Project registration/removal, Runtime lifecycle, External
Channel ingress/delivery, scheduled work, account/workspace authorization, and
model integration operations. Execute applicable existing required CI suites for
each PR; do not claim a pass while queued or skipped.

Internal transaction lifetime is not reliably observable from browser behavior.
Add focused repository/service tests that make external collaborators assert no
active transaction, verify completion before publication, and preserve atomic
failure behavior. Exercise OAuth fresh/refresh/failure paths, stale finalization,
access loss, cancellation, and existing idempotency/lock-order cases where affected.
Use deterministic barriers or authoritative state for concurrency tests, not
sleeps.

Use existing local database/testenv fixtures only where real PostgreSQL locking
or E2E prerequisites are necessary. No live provider credentials are required for
the deterministic boundary tests; fake provider results and isolated test data
must contain no production secrets. Record credential/prerequisite availability
without recording credential values. Optional live tests may be skipped only with
the exact missing prerequisite stated; failed required tests block that slice.

Evidence consists of commands, test counts, failure/skip reasons, changed-path
Ruff/format/type results, pre-commit results, PR links and CI state, and a
post-change inventory. New distributed coordination, if genuinely unavoidable,
also requires Redis-free standalone evidence, distributed Redis-loss safety
evidence, and an exception report. The standalone memory implementation is not an
automatic failover for Redis-backed multi-process deployments.

## Feasibility and Remaining Risks

The existing manager and detached repository data make scoped extraction feasible
without a schema migration. Title generation has a clear completed-read boundary.
Project registration needs explicit authority revalidation, and indirect
cross-domain callers require continued inspection.

Repository-wide feasibility is still being verified per domain. No complete
coverage or completed implementation is claimed by this Design. In particular,
the inventory must identify any path whose existing atomicity depends on external
serialization and report it under REQ-5 before choosing a new mechanism.

## Design Approval

- Mode: Collaborative; direct implementation request.
- Decision owner: requester.
- Request date: 2026-09-08.
- Execution scope: M1, M2, M3, M4, M5 are fixed consequences of the requester’s
  transaction rules, implementation request, and lock-exception reporting rule.
- Approval record: the requester authorized implementation of those constraints;
  no separate revision-bound approval of this written Design is claimed.
- Unresolved new mechanisms: none authorized. Any new material behavior or
  unavoidable locking exception is reported separately rather than silently
  treated as approved by this document.
