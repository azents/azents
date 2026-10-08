---
title: "Conservative NOWAIT Contention Recovery Decisions"
created: 2026-10-05
tags: [backend, concurrency, memory, reliability]
document_role: primary
document_type: adr
snapshot_id: contention-261005
---

# Conservative NOWAIT Contention Recovery Decisions

- Requirements: [contention-261005/REQ](../requirements/contention-261005-nowait-policy.md)

## D1. Retain justified nonwaiting acquisition instead of replacing every writer graph

REQ-1 and the requester's implementation instruction authorize conservative selection rather than unconditional removal. Preserve the current savepoint-based Session/Subagent partial-lock rollback, external final Apply and OAuth security acceptance graphs, and explicit handover quiescence refusal. Retention must be supported by an actual participating-writer or busy/admission contract; lack of a convenient implementation is not itself justification.

Remove the dormant Agent NOWAIT helper and unreachable profile option. Simplify unlink to an exact-owner conditional mutation and immutable accepted-mutation replay to an ordinary committed read. Terminal Memory metadata has a single unit-to-attempt order and no source/Agent acceptance locks; use ordinary waiting locks there while retaining exact-current-owner predicates.

Rejected: mechanical deletion of every flag, replacing exact authority rows with SKIP LOCKED, removing advisory absence protection, and a new global mutex. These would trade contention for unsafe admission, broad serialization, or new wait cycles. A global lock-order rewrite is not required for the narrowly retained partial-lock protocols.

## D2. Retry rollback-confirmed Memory database operations, not model/tool execution

REQ-2/3 require cheap transient contention recovery inside the admitted attempt. Repository-owned database-only operation boundaries repeat after the prior transaction has completely rolled back. Retain the same principal, model response, dispatch/receipt identifiers and logical-turn position. The existing attempt/lease deadline and cancellation bound recovery; no token/call/count retry budget is added.

Retained Agent/grant and complete source-manifest NOWAIT locks continue breaking concrete lifecycle/preparation inversions. A busy guard is temporarily unavailable, not revoked authority. Revalidate current eligibility, grant identity, owner generation/token and complete manifest on each fresh operation. A heartbeat uses the same recovery mechanism rather than terminalizing on its first busy sample. Actual stale/revoked/expired authority remains terminal.

Only normalized lock contention and database errors that guarantee a transaction abort can be retried. Unclassified connection loss or uncertain commit does not enter automatic replay; existing durable publication outcome and idempotency checks remain authoritative.

Rejected: restarting the host/provider call or the whole service, retrying arbitrary DBAPIError, reusing an aborted transaction, or sleeping while partial locks remain held. These can duplicate external effects or lose current authority.

## D3. Install time boundaries before owner acquisition and preserve terminal cleanup

REQ-2 requires the permitted execution time to cover initial acquisition too. A nonauthoritative durable owner/time observation supplies only a scheduling bound before the first producer lock; it does not authorize a mutation. Locked reauthorization and fresh DB time still determine acceptance. The absolute admitted deadline never restarts with a retry.

Initial claim repeats its complete database operation within the submitted deadline. Terminal metadata retains the previous exact active unit/attempt/generation/token/RUNNING predicates and existing caller cancellation/Job Runtime cleanup lifetime, even when execution time has elapsed. It does not reacquire body/source/publication authority. Removing terminal NOWAIT does not add a new hidden time policy or allow stale-owner settlement.

## D4. Keep existing external busy and single-use contracts

REQ-1/3 permit behavior-preserving external simplifications, not new callback recovery machinery or provider retries. Unlink may use normal conditional-DML waiting under its existing lock-timeout/transaction retry contract, followed by fresh auth/expiry revalidation. Immutable matching Apply replay may be observed without its redundant exclusive row lock; once-only profile/audit/notice acceptance remains unchanged.

Retain the final Apply's rollback-and-busy acquisition protocol and shared Agent/principal advisory key because participating revoke/block/route/profile writers have real opposing orders and the key protects absent blocks and hard-deleted grants. Retain OAuth's single-use admission and finalization security guards; do not claim this work supplies a new callback retry contract. A broader callback/lock-order redesign requires separate explicit authority.

## Scope and authority

The requester directly approved necessary NOWAIT retention conservatively and instructed implementation on 2026-10-05 after the exhaustive audit and trade-off briefing. These decisions implement that scoped policy and REQ-1–3, without a new authority source, global mutex, provider fallback, or live operation. Ordinary queue nonblocking APIs, SKIP LOCKED queues, authored-output validation and publication product shape are unchanged.
