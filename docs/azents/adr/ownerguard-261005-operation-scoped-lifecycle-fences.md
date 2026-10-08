---
title: "Operation-Scoped Execution and Lifecycle Decisions"
created: 2026-10-05
tags: [backend, concurrency, execution, lifecycle]
document_role: primary
document_type: adr
snapshot_id: ownerguard-261005
---

# Operation-Scoped Execution and Lifecycle Decisions

Authority: [ownerguard-261005/REQ](../requirements/ownerguard-261005-operation-scoped-lifecycle-fences.md). The requested read/removal contract and existing execution/lifecycle outcomes determine these boundaries.

## D1 — Exact owned mutation fence, independent descriptions

Remove generic root/Agent/parent ownership locking from description and harmless private state operations. Critical dependent writes acquire only the existing exact Session ownership row mutation fence, compare owner generation and retain that exclusion through commit. Propagate the existing captured owner explicitly to the critical completed operation, not every transaction factory.

An unrelated INSERT with an `EXISTS(owner_generation=...)` condition alone does not serialize a concurrent owner change under PostgreSQL MVCC. An earlier read check or in-memory generation comparison is insufficient. A generic renamed manager that still gates every transaction is also rejected.

## D2 — Claims and hierarchy transitions own their mutation ordering

Use existing conditional status/generation/lease writes and exact claim rows to preserve single accepted work. Multi-row parent result disposition and mailbox admission stay in one exact conditional group. Critical child creation/Stop/purge/archive ordering can retain a mutation-only ancestor fence where required to prevent a child escaping a transition; ordinary tree enumeration does not inherit it.

Deleting all parent locks while merely selecting current descendants would weaken the existing hierarchy contract. Creating a new owner token/schema or global mode is unnecessary and outside authority.

## D3 — Exact resource and producer finalization, not newest description

Keep actual lease/attempt/generation/configuration/ack conditions at Runtime/resource/publication mutation. Remove status/cleanup-view serialization. Path claim preserves existing overlap safety at actual destructive ownership admission; exact-path uniqueness alone does not prove ancestor/descendant exclusion. Channel Work uses existing version/cycle/progress revision conditions rather than generic root fencing.

## D4 — Implementation progresses independently of CI waits

Implement the remaining coherent phases first while checking authored PR CI in parallel. Correct an observed failure on its owning PR without stopping independent next-phase work. This ordering follows the requester's explicit direction and does not waive correctness, required review or delivered-SHA verification.

## Risks

Shared wrappers obscure which operation consumes owner authority. Migrate actual critical compositions and their callers, not lock tokens alone. Preserve generation identity on every completion and atomic dependent mutation. Register remaining fences by exact outcome and deterministic evidence; broad security/lifecycle module names are not exceptions.

## D5 — Description fallback does not perform lazy persisted repair

Chat detail/list continues to return its existing fallback projection for a stale
applied profile, but GET does not lock Session/Agent or increment the persisted
applied-profile generation. Detached response identity is not a new admission
authority. Actual profile/operation admission retains its existing reconciliation,
captured-input and mutation conditions. Tests distinguish unchanged public
fallback response from unchanged stored bytes/generation after description.

Retaining a hidden UPDATE merely because a GET previously performed it would keep
the discarded blocking read policy. Returning an invented persisted generation,
changing fallback transport support or silently altering actual operation
acceptance is rejected.
