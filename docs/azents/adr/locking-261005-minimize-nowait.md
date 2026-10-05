---
title: "Removal-First Nonwaiting Lock Decisions"
created: 2026-10-05
tags: [backend, concurrency, reliability, memory, authorization]
document_role: primary
document_type: adr
snapshot_id: locking-261005
---

# Removal-First Nonwaiting Lock Decisions

- Snapshot: `locking-261005`
- Authority: [locking-261005/REQ](../requirements/locking-261005-minimize-nowait.md)
- Decision owner: requester for the removal-first policy and preserved contracts; repository implementation details remain agent-owned.
- Scope: the 30 direct SQL NOWAIT declarations and one active try-advisory branch at `ae5fffc89ac30fcc58baaf2ac0a4f3f6dc8db03c`.

This snapshot supersedes the retention policy in `contention-261005`, without rewriting that historical snapshot. The requester directed implementation through a PR, not a new product mode or a broader locking architecture. The following decisions apply that instruction within the confirmed safety boundaries.

## D1. Remove nonwaiting refusal while retaining exact mutation fences

- Reference: `locking-261005/ADR-D1`
- Requirements: `locking-261005/REQ-1`, `locking-261005/REQ-2`.
- Accepted scope: replace all inventoried nonwaiting acquisitions when verified ordinary acquisition and operation recovery preserve their contracts; retain no exception without concrete failed-alternative evidence.

Keep existing row/advisory identities and sufficient lock modes. Repair concrete participant-order inversions locally and refresh authority after waiting. Contention does not authorize empty/partial manifests, stale identities or accepting an expired authorization. Existing queue SKIP LOCKED and asynchronous queue APIs are unchanged.

Rejected: retaining locks because they currently exist, convenience-based busy behavior, flag-only deletion without competing-writer closure, and an Agent/root-global mutex. None satisfies the confirmed outcome and constraints.

## D2. Recover only a completely aborted database operation

- Reference: `locking-261005/ADR-D2`
- Requirements: `locking-261005/REQ-2`, `locking-261005/REQ-3`.
- Accepted scope: explicitly enumerated DB-only owning operations may retry a database-confirmed aborted transaction after its scope closes and rollback releases every partial fence.

Retain original logical inputs and owner generation. Reopen a fresh scope and repeat authority checks. Only confirmed contention/serialization aborts qualify; cancellation, denial, expiry, stale owner, unrelated failure and uncertain commit do not. Commit belongs to the operation. Composing in-session helpers are never individually retried with outer mutations still live.

The finite hierarchy closure includes four Subagent mutations, seven tree lifecycle operations, twelve owned terminal operations and two standalone terminal-repair operations. This covers either possible deadlock victim without replaying the Engine/Worker, model, tool or lifecycle service. Existing external model mutation retry bounds remain unchanged; OAuth claim/finalization remain separate from the one-time exchange. Offline handover retries only an aborted page, not previously committed pages.

Rejected: retrying a complete Run/tool/service, only retrying the parent side of a two-sided deadlock, a generic SessionManager/SQL retry layer, catching ambiguous commits, and a new count/time/spend cap.

## D3. Waiting must not freeze or prevent legitimate Memory lease renewal

- Reference: `locking-261005/ADR-D3`
- Requirements: `locking-261005/REQ-2`, `locking-261005/REQ-3`; unchanged Memory ownership/heartbeat contract.
- Accepted scope: before exact unit acquisition, the immutable admitted attempt deadline bounds waiting; after unit acquisition, validate the current lease and reschedule within that same attempt cutoff.

Complete-influence operations discover only routing/manifest identities, wait for exact Agent/grant/root/source participants before owning the unit, then lock the original owner and revalidate the draft/attempt/revision evidence and complete current manifest. Changed planning evidence aborts the DB operation and repeats it after rollback; it is never acceptance authority. This preserves independent heartbeat renewal during source waits. Source preparation/publication uses explicit Agent -> membership -> root -> source acquisition, retaining sufficient writer modes and existing eligibility outcomes.

Rejected: freezing the initial lease before a wait; holding the unit while waiting for a source and thereby blocking renewal; periodic heartbeat-derived lock timeouts; incomplete influence scans; reusing observations as authority; and renewing genuinely expired work. A long actual critical write after unit acquisition can still exhaust its real live lease and must fail.

## Consequences and risks

- Ordinary lock waits replace immediate refusal, subject to existing operation cancellation and real lifecycle deadlines. OAuth claim and offline pages gain no invented local timeout.
- Existing external model mutation lock timeout and retry bounds still permit a busy result on exhaustion; they are not a total-operation deadline.
- PostgreSQL may choose either deadlock participant. The finite whole-operation boundary must be covered by integration tests, not inferred from sorting Session IDs.
- Memory planning must detect newly added/removed influence and stale revision/epoch before acceptance. Complete-set validation remains mandatory.
- No persistence schema, generated client, deployment setting, production mutation or compatibility mode is introduced. Current behavior is recorded in Living Specs only after implementation verification.
