---
title: "Conservative NOWAIT Contention Recovery Requirements"
created: 2026-10-05
implemented: 2026-10-05
tags: [backend, concurrency, memory, reliability]
document_role: primary
document_type: requirements
snapshot_id: contention-261005
---

# Conservative NOWAIT Contention Recovery Requirements

- Snapshot: `contention-261005`
- Document reference: `contention-261005/REQ`

## Problem

Transient database lock contention can terminate an otherwise valid Historical Memory attempt and impose long whole-attempt backoff. Across the product, nonwaiting row/advisory acquisition has inconsistent recovery, and dormant helpers obscure which fast-failure behavior is intentional.

## Primary System Outcome

Valid database operations survive temporary contention without duplicating external effects or weakening authority. Retain nonwaiting acquisition only where a concrete safety or maintainability advantage justifies it; remove unnecessary uses conservatively.

## Supporting Effects

- Historical Memory retains its existing attempt and work when a short database operation can recover.
- Operators and maintainers can distinguish transient contention from stale ownership, denied authority, and real deadline exhaustion.
- Every audited production NOWAIT use has a recorded retention or removal rationale.

## Goals

- Correct cheap-contention recovery rather than convert it into expensive whole-work failure.
- Simplify dormant or unnecessary locking without broad new coordination machinery.

## Non-Goals

- Remove every database lock or force every operation to wait.
- Introduce a global mutex, new authority source, provider fallback, or execution loop.
- Change historical publication shape, source eligibility, or authored-output validation.
- Deploy, merge, migrate production, change live settings, or force jobs.

## Requirements

### REQ-1. Retain NOWAIT only with concrete justification

Review all audited direct and indirect nonwaiting database paths. Preserve uses where releasing partial locks, an existing explicit busy contract, or an operator precondition makes fast failure safer or simpler. Remove dormant branches and uses with an equivalent simpler safe implementation.

**Acceptance criteria**

- The 35 audited direct SQL declarations and one active try-advisory path are accounted for individually.
- Retained uses have an actual operation-boundary rationale, not only an unexamined generic deadlock claim.
- Queue APIs and legitimate queue-claim behavior remain unchanged.

### REQ-2. Recover transient Historical Memory contention inside the same attempt

Temporary contention must not immediately terminalize an otherwise valid admitted attempt. Recovery must use the existing time/lease/cancellation boundaries and refresh current authority after contention.

**Acceptance criteria**

- Releasing a held writer lets the same claim continue without a new attempt, failed state, or failure/backoff increment.
- Preparation, model-output admission, heartbeat, files, usage and publication remain consistent when their local database operation retries.
- Initial lock waits/retries are covered by the permitted existing time boundary.
- Real revocation, owner replacement, deadline/lease loss and shutdown do not permit stale commits or continued unauthorized work.
- No additional memory-only token, call, turn or arbitrary retry-count cutoff is introduced.

### REQ-3. Preserve atomicity and one-time external effects

Recovery repeats only a rollback-confirmed database operation. Existing commit ambiguity and idempotency rules remain authoritative.

**Acceptance criteria**

- No duplicate physical model request, provider code exchange, side-effecting tool, mailbox, profile generation, audit, publication or notification is caused by database contention recovery.
- No sleep or external I/O occurs while a failed operation still holds a transaction's partial locks.
- Error/cancellation cleanup remains truthful and content-safe.

## Fixed Constraints

- Preserve Team/User isolation, membership identities, complete manifests, generation/token fences, atomic publication and current external authorization semantics.
- Preserve adopted prior Requirements/ADRs/Designs; current behavior updates belong in Living Specs.
- Start from freshly fetched main `584bda0540141481894b0464e306382315443ce9`.
- Reuse current repository-owned transaction boundaries and existing application execution machinery.

## Open Assumptions

- Existing explicit busy responses outside Historical Memory remain product contracts unless a behavior-preserving removal is demonstrably equivalent.
- This work does not promise absence of all contention; genuine deadline or authority failures remain visible.

## Confirmation

On 2026-10-05 the requester first required an exhaustive NOWAIT audit and removal proposal, then explicitly approved retaining genuinely beneficial uses conservatively and instructed implementation. This confirms REQ-1–3 within the previously discussed authority and no-live-operation boundaries. It supersedes the earlier all-removal research direction; it does not authorize unreported global lock or product-policy redesign.
