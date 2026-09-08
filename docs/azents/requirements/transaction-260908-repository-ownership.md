---
title: "Repository-owned Database Transactions Requirements"
created: 2026-09-08
tags: [backend, architecture, database, concurrency]
document_role: primary
document_type: requirements
snapshot_id: transaction-260908
---

# Repository-owned Database Transactions Requirements

- Snapshot: `transaction-260908`
- Document reference: `transaction-260908/REQ`
- Related issue: [#1718](https://github.com/azents/azents/issues/1718)

## Problem

Database transaction ownership currently extends into application orchestration. Some database reads remain in open transactions while dependent external work runs. An import-only convention change would not remove these transaction lifetime violations.

## Primary System Outcome

Every application database transaction has an explicit repository-owned lifetime and contains database work only, without changing the product's authorization, atomicity, or failure semantics.

## Supporting Scenarios or Effects

- External API and Runtime latency does not prolong an unrelated open database transaction.
- Multi-record operations remain atomic while repository responsibilities remain bounded.
- A full inventory exposes remaining violations instead of treating a partial conversion as complete.

## Goals

- Audit every database transaction entry point and its reachable application calls.
- Correct confirmed transaction ownership and external-I/O violations.
- Submit tested, reviewable implementation changes rather than only a convention update or report.

## Non-Goals

- Change user-visible authorization, lifecycle, retry, delivery, or data-retention policy.
- Introduce a new database or broker technology.
- Rewrite generated clients or already-executed migrations.
- Treat direct test fixture database setup or database migration infrastructure as user-facing application transaction ownership.

## Requirements

### REQ-1. Repository-owned atomic database work

Application transactions begin and finish in the repository layer. Operations spanning multiple repository responsibilities remain atomic through repository composition.

**Acceptance criteria**

- Services, API routes, workers, and tools call completed repository operations rather than owning application transactions.
- A composing repository can use narrower repositories in one transaction without exposing that live transaction to application callers.
- A session alias, general callback wrapper, or relocation without ownership change does not count as remediation.

### REQ-2. No external I/O during open transactions

An open database transaction contains only database work. External API, Redis, broker, filesystem, provider, and Runtime operations execute outside it.

**Acceptance criteria**

- Inspection follows helper calls and injected callbacks, including conditional external calls.
- Both read and write transactions are checked, accounting for implicit transaction start and restart after a prior commit.
- A lexical session context without an active database transaction is distinguished from an actual transaction lifetime violation.
- Failure, cancellation, and retry paths do not introduce external I/O while a transaction remains open.

### REQ-3. Preserve correctness across separated phases

Transaction isolation changes preserve existing atomic outcomes, authorization, lock order, idempotency, concurrency checks, and observable error handling.

**Acceptance criteria**

- Related writes that must be atomic commit or roll back together.
- Database authority necessary for the final mutation is revalidated after external work.
- External work does not become an implicit retryable database callback or gain duplicate effects.
- Existing supported behavior and product contracts remain intact.

### REQ-4. Complete coverage and verified delivery

The inspection covers the repository's application database paths, not only the seven External Channel service files originally reported.

**Acceptance criteria**

- Every discovered entry point has an owning area and an inspected, corrected, or evidence-backed excluded outcome.
- Infrastructure, migrations, tests, generated code, and read-only diagnostics are classified explicitly rather than silently skipped or broadly rewritten.
- Targeted regression checks, applicable quality checks, and PR CI validate each delivery phase.
- A final inventory and call-path review identify remaining violations and incomplete coverage.

### REQ-5. Avoid cross-I/O locks and report unavoidable exceptions

Prefer existing idempotency, version fences, conditional database updates, and short database-only transactions over locks spanning external work. Cross-I/O serialization is a last resort, not the default transaction replacement.

**Acceptance criteria**

- Every proposed cross-I/O lock identifies the exact invariant and why lock-free alternatives cannot preserve it.
- An unavoidable cross-I/O lock supports Redis-backed distributed coordination and an in-memory implementation for a Redis-free single standalone deployment, such as a development server.
- Each exception report records the affected path, rejected lock-free alternatives, protected scope, lifecycle, failure and cancellation handling, standalone behavior, and Redis-loss behavior in a distributed deployment.
- The in-memory implementation is the standalone deployment alternative, not an automatic Redis-outage failover for a multi-process deployment.
- External I/O remains outside database transactions even for an approved locking exception.

## Fixed Constraints

- The requester requires repository-owned transactions, repository composition for atomic database work, and no external operations within open transactions.
- Preserve existing product behavior; do not add compatibility fallbacks or override conventions to accommodate current violations.
- Use separate reviewable PRs as needed. Do not merge without explicit requester authorization.
- Implemented Requirements, ADRs, and Designs remain immutable; new decisions are recorded in this snapshot.

## Open Assumptions

- The preliminary 109-service-file / 700-context scan is a candidate inventory, not complete coverage or a confirmed violation count.
- Additional transaction factories, aliases, and non-service entry points require explicit inspection.

## Confirmation

The requester established the three transaction rules and then explicitly requested both implementation/PR submission and a repository-wide inspection on 2026-09-08 KST. This snapshot records that direct execution request; it does not claim approval of any undisclosed implementation mechanism.
