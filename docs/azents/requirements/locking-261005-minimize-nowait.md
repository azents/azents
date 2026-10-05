---
title: "Removal-First Nonwaiting Lock Requirements"
created: 2026-10-05
implemented: 2026-10-06
tags: [backend, concurrency, reliability, memory, authorization]
document_role: primary
document_type: requirements
snapshot_id: locking-261005
---

# Removal-First Nonwaiting Lock Requirements

- Snapshot: `locking-261005`
- Document reference: `locking-261005/REQ`

## Problem

Temporary database contention can reject valid work immediately. The previous audit retained most nonwaiting acquisition on the basis of existing lock graphs or busy behavior without establishing whether safe alternatives could remove that need. The requester clarified that conservative retention means removing by default and keeping only genuinely necessary exceptions.

## Primary System Outcome

Valid operations normally survive temporary lock ownership by another transaction while retaining their existing authority, atomicity, cancellation and one-time effects. Nonwaiting refusal remains only where a demonstrated invariant cannot be maintained by a safe alternative within this task's scope.

## Supporting Effects

- Operators can distinguish genuine ownership/eligibility loss from transient contention.
- Every retained exception has concrete competing-operation and replacement evidence.
- Successful Memory publication and subsequent workspace cleanup remain intact.

## Goals

- Minimize production SQL NOWAIT and equivalent try-lock refusals rather than only remove dormant code.
- Replace unjustified immediate failure without weakening critical admission or recovery.

## Non-Goals

- Eliminate mutual exclusion, queue claims or legitimate asynchronous queue APIs.
- Change source visibility, principal identity, provider behavior or Memory output policy.
- Add a global mutex, alternative execution engine or arbitrary token/call/turn limits.
- Merge, deploy, modify production settings/data or force jobs.

## Requirements

### REQ-1. Removal is the default; retention requires necessity evidence

Reassess all remaining production nonwaiting database acquisitions against safe equivalent alternatives. Existing usage, implementation convenience or generic deadlock assertions are insufficient reasons to retain them.

**Acceptance criteria**

- Account individually for the 30 direct SQL NOWAIT declarations and the active try-advisory path at the starting baseline.
- For every retained exception, identify the concrete competing operations, invariant at risk, and why ordinary waiting, equivalent ordering or operation-level recovery cannot safely replace it.
- Remove all sites with a demonstrated safe replacement; do not impose an invented retention quota or treat uncertain research as proof of necessity.
- Queue APIs and SKIP LOCKED keep their queue-claim semantics.

### REQ-2. Preserve authority and atomicity during contention recovery

Waiting or recovery must not permit acceptance using an expired or superseded authorization observation. Required exclusion remains effective through the accepting commit.

**Acceptance criteria**

- Revalidate elapsed expiry, current ownership, membership, generation/token and exact target identities after waiting where relevant.
- Revocation, takeover, cancellation and real deadline/lease loss prevent stale acceptance.
- Complete manifests, subtree admission, finite work and published workspace retirement remain atomic.
- Manual quiescence checks remain authoritative rather than being substituted by successful lock acquisition alone.
- Existing operation timing/cancellation boundaries remain effective; no hidden Memory retry-count or spend cutoff is added.

### REQ-3. Recover only safe database boundaries

Contention handling must not repeat external effects or disguise unknown commit outcomes as confirmed rollback.

**Acceptance criteria**

- No duplicate model/provider request, OAuth exchange, tool effect, mailbox delivery, profile generation, audit, notification or publication is introduced.
- Any local recovery occurs only after the owning database operation has released its failed transaction/partial locks.
- Uncertain commits retain durable-outcome/idempotency handling.
- Controlled held-writer tests verify continuation, cancellation, expiry/refusal and exactly-once effects for each changed operation family.

## Fixed Constraints

- Start from current main `ae5fffc89ac30fcc58baaf2ac0a4f3f6dc8db03c`.
- Preserve Team/User isolation, complete-source authority, OAuth single-use identity, security fences and atomic accepted state.
- Historical `contention-261005` documents remain immutable records of the prior implementation; this snapshot supersedes its retention policy, not its verified one-time-effect and Memory recovery protections.
- Current user-directed outcome permits safe waiting instead of immediate contention refusal; a fundamentally new user-facing mode or new authority is outside this task.

## Open Assumptions

- Concrete irreducible partial-lock protocols may retain nonwaiting refusal if replacement evidence establishes its necessity.
- Genuine deadline, cancellation, denied authority and business conflicts remain legitimate failures.

## Confirmation

On 2026-10-05 the requester corrected the prior interpretation: remove nonwaiting acquisition by default and retain only sites with a necessary reason, rather than removing cautiously. After the separate Memory workspace and main CI fixes, the requester explicitly directed immediate return to this work and delivery through PR creation. These cumulative instructions confirm REQ-1–3 and direct implementation within the stated safety boundaries; no separate intermediate approval pause was requested.
