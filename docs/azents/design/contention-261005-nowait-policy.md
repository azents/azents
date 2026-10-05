---
title: "Conservative NOWAIT Contention Recovery Design"
created: 2026-10-05
implemented: 2026-10-05
tags: [backend, concurrency, memory, reliability]
document_role: primary
document_type: design
snapshot_id: contention-261005
---

# Conservative NOWAIT Contention Recovery Design

- Requirements: [contention-261005/REQ](../requirements/contention-261005-nowait-policy.md)
- Decisions: [contention-261005/ADR](../adr/contention-261005-nowait-policy.md)
- Baseline: `584bda0540141481894b0464e306382315443ce9`.

## Mechanisms

### M1. Explicit bounded retention inventory

Record every one of the 35 baseline SQL NOWAIT declarations and the one active advisory try path in a supporting decision register. Retain only actual producer/partial-security-graph exclusion, partial-lock rollback, or explicit operator refusal. Delete the unreachable Agent helper and model-profile True option; preserve the live Session helper. Historical audit artifacts remain historical.

### M2. Repository-only Memory retry

Use a typed operation wrapper on completed database-owning repository methods, not an async context manager that attempts to yield a transaction body twice. A failed invocation exits its transaction scope and finishes rollback before the wrapper yields/backoffs outside any session and invokes the same database operation again. Parameters and return typing stay intact. The wrapper uses the same principal and admitted time/lease identity; no host, model SDK, tool handler or external publication mechanism is repeated.

Cover setup/recovery/work, private draft observations and receipt mutations, source inventory/read receipts, scalar dispatch usage, output authorization, heartbeat renewal, freeze/coverage and local publication. Install retry around the private publication transaction inside its existing public uncertain-commit inspection boundary. Do not blanket-retry all DBAPI errors or add a physical-request/turn/retry-count budget.

Actual ownership, membership, permission, complete influence and commit-time identity predicates remain authoritative on each fresh transaction. Transient busy before model invocation or after provider output does not become an expensive failed attempt. Revocation/expiry/takeover still prevents acceptance. Initial claim has an explicit same-deadline database-only retry, not a whole-job restart.

### M3. Pre-lock time bounds and ordered terminal settlement

Observe durable matching owner/attempt time solely to schedule the operation timeout before Agent/membership/unit acquisition. This observation is not authority: locked exact owner/grant revalidation and fresh DB clock determine acceptance. PostgreSQL statement timeout and asyncio cancellation cover the first acquisition as well as dependent work; retry never replaces the absolute admitted deadline.

Terminal failure settlement uses ordinary unit-to-matching-attempt waiting locks and exact-current-owner predicates. It has no source/Agent/manifest access and cannot revive expired execution. Existing Job Runtime/caller cancellation owns cleanup lifetime. A completed or replacement owner wins; successful metadata settlement increments failure/no-progress once, not once per contention retry.

### M4. External behavior-preserving simplification

Replace unlink's explicit read-lock/ORM mutation with conditional exact-owner active-link UPDATE RETURNING and an ordinary idempotent revoked-link read. Preserve existing three-attempt/two-second-lock-wait busy policy. Refresh current User/auth Session and actual elapsed expiry after a DML wait before acceptance; rollback on lost authorization.

Read immutable matching accepted-model mutation identity/profile/audit as committed data without its redundant NOWAIT row lock. Preserve exact interaction fingerprint/actor/target checks, unique identity and final authorization; replay does not advance profile generation, create audit twice or send another notice.

The other external security guard graphs and advisory try protocol remain under their current partial-lock rollback/busy contracts. No new OAuth callback retry or provider code replay is introduced.

## Concurrency and ownership boundaries

- Repositories own sessions, commit and rollback; model/tool/provider/runtime/broker I/O remains outside.
- Transient retry must not treat committed output as absent or blindly reapply uncertain writes. Dispatch usage, mutation receipts and publication outcome remain idempotent authorities.
- Source and lifecycle NOWAIT preserve current real inversion avoidance; this work does not swap them for indefinite waits or partial manifests.
- Session/Subagent savepoint rollback remains because child terminal delivery needs a parent's partially held row. No extra root gate is added to send/interrupt.
- Current queue claims and async queue operations are unaffected.

## Removal and Replacement

| Removed unit | Authority | Replacement / retained boundary | Verification |
| --- | --- | --- | --- |
| Dormant Agent NOWAIT helper / writable-profile True option | REQ-1; ADR-D1 | Existing blocking exact-row helper and unchanged authorization | Production caller census; profile/availability tests |
| Immediate terminalization of rollback-confirmed Memory busy | REQ-2/3; ADR-D2 | Same-principal complete DB-operation retry within admitted time | Held-writer release succeeds with same attempt and no failure/backoff |
| Owner lock before its operation time bound | REQ-2; ADR-D3 | Pre-lock time scheduling plus locked reauthorization | Held initial Agent/unit lock timeout/cancellation |
| Terminal metadata unit/attempt NOWAIT | REQ-1/3; ADR-D1/D3 | Ordered ordinary locks, exact owner predicates and caller cleanup cancellation | Stale/completed/new owner and once-only metadata tests |
| Unlink exclusive read-lock mutation | REQ-1/3; ADR-D4 | Exact conditional DML plus current auth and idempotent replay | Held-lock release, repeated unlink, auth loss while waiting |
| Exclusive accepted-model replay read | REQ-1/3; ADR-D4 | Ordinary committed immutable identity observation | Replay under concurrent notice write; no second mutation/notice |

## Design Authority

- Design revision: `1`

| ID | Authority | Classification |
| --- | --- | --- |
| M1 | REQ-1; requester conservative-retention instruction; ADR-D1 | required |
| M2 | REQ-2/3; existing repository-owned transactions; ADR-D2 | derived |
| M3 | REQ-2/3; existing claim/deadline/generation/terminal fences; ADR-D3 | derived |
| M4 | REQ-1/3; existing external authority/idempotency/busy contracts; ADR-D4 | derived |

## Feasibility

Typed repository wrappers can repeat complete rollback-confirmed methods without copying the shared Agent execution loop. Current journals and committed-outcome checks support exact replay. Existing peer-holder tests establish retained partial-lock safety; current external conditional update patterns and typed return values support the limited unlink/replay replacements. First-acquisition time installation and cancellation races require deterministic real PostgreSQL verification. No schema, API-client, deployment or new authority change is expected.

## Test Strategy

Assembled-product Historical Memory E2E remains the primary publication/isolation regression, using a fresh image, prepared local fixtures and deterministic synthetic provider only. Exact database contention is verified with independent PostgreSQL connections and barriers at actual repository boundaries: externally forcing live writers or adding a public test API is not authorized and would be weaker evidence of atomic rollback.

The focused matrix includes:

- Agent/member/source/manifest writer release during setup, response authorization, files/receipts, dispatch settlement, heartbeat and publication; same attempt succeeds without failure/backoff or repeated provider/tool effects.
- Busy, transaction-abort retry, cancellation, lease/deadline exhaustion, revocation, new generation and completed publication; no stale commits or unobserved outcomes.
- Initial claim and unit wait are time-bounded before acquisition; sampled time alone grants no authority.
- Terminal metadata after cutoff waits safely, preserves primary failure and new/completed winners, and increments counters once.
- Unlink conditional write/replay and current auth/expiry loss after wait; existing busy exhaustion and owner nondisclosure unchanged.
- Accepted-model replay under a writer, unique Apply identity, generation/audit/notice exactly once.
- Dead helper/options absent; existing Session/Subagent partial-lock and queue semantics preserved.

Run scoped Ruff/type/tests, complete backend, existing relevant External Channel/Hierarchy tests, fresh Historical Memory E2E, independent targeted review and final-SHA CI. Local/paid/live prerequisites are not needed; a missing disposable substrate is a diagnostic blocker, not silent test success. Avoid concurrent heavy suites that can exhaust the Agent Runtime. Preserve command/results and source SHA in Session evidence; no production changes.

## Design Approval

- Mode: requester-owned scoped implementation delegation.
- Decision owner: requester for conservative retention and same-attempt recovery; implementation owner for equivalent local engineering details.
- Date: 2026-10-05.
- Approved scope: necessary NOWAIT retained sparingly with concrete rationale; unused/unnecessary uses removed; transient database contention recovered without new authority or duplicate external effects.
- Approved revision: 1; authority IDs M1, M2, M3, M4.
- Authority basis: the requester's direct implementation instruction after the audit and explicit beneficial-NOWAIT trade-off briefing. No undisclosed global writer-graph rewrite, new execution mode or live operation is included.

## Verified Implementation

Completed on 2026-10-05 against the recorded baseline:

- Production AST census: 30 direct SQL NOWAIT declarations and one retained try-advisory path, with all 35 baseline declarations individually accounted for.
- Complete backend: 10,850 passed, three skipped, no failures; final Memory repository/host matrix: 128 passed.
- Fresh current-source Docker Historical Memory E2E: three passed, covering publication, isolation, live access denial, lifecycle and policy roundtrip.
- Whole-backend Ruff, formatting and configured type checking, documentation validation/catalog tests, and diff whitespace checks passed.
- Independent Memory and non-Memory implementation reviews cleared the unchanged material mechanism set M1–M4. Final test corrections preserved distinct draft/publication identities and changed no product authority.
- No schema/API change, production operation, deployment or merge was performed. PR delivery and final-SHA CI remain delivery evidence rather than additional design authority.
