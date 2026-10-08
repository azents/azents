---
title: "Removal-First Nonwaiting Lock Design"
created: 2026-10-05
implemented: 2026-10-06
tags: [backend, concurrency, reliability, memory, authorization]
document_role: primary
document_type: design
snapshot_id: locking-261005
---

# Removal-First Nonwaiting Lock Design

- Snapshot: `locking-261005`
- Intent: [locking-261005/REQ](../requirements/locking-261005-minimize-nowait.md)
- Decisions: [locking-261005/ADR](../adr/locking-261005-minimize-nowait.md)
- Baseline: `ae5fffc89ac30fcc58baaf2ac0a4f3f6dc8db03c`.

## Current behavior and gaps

Thirty direct SQL NOWAIT declarations remain: three hierarchy locks, eight Memory locks, four account-link locks, three OAuth claim locks and twelve native model-setting locks. One authorization advisory helper still has an active try-lock caller. Existing fragment retries release only newly acquired rows, while other writers can own inverse-order participants. Immediate refusal is not proven necessary. Existing durable ownership, full-manifest, single-use and idempotency behavior is authoritative and remains intact.

Current behavior was researched in `spec/domain/memory.md`, `spec/flow/periodic-execution.md`, `spec/flow/agent-execution-loop.md`, `spec/flow/run-resume.md`, `spec/flow/external-channel-authorization.md` and `spec/flow/external-channel-provider-ingress.md`, and checked against actual declarations, callers and competing writers.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Ordinary acquisition retains exact security/lifecycle row and advisory fences; no unproven nonwaiting exception | REQ-1, REQ-2, ADR-D1 | decided |
| M2 | Finite complete DB-operation rollback recovery covers hierarchy admission and both terminal victims; original owner and inputs retained | REQ-2, REQ-3, ADR-D2; existing execution ownership/terminal atomicity | decided |
| M3 | External mutations refresh current identities and elapsed expiry after waits; exchange/notice remain outside retry | REQ-2, REQ-3, ADR-D1/D2; current authorization and ingress Specs | derived |
| M4 | Memory waits before exact unit ownership use admitted attempt deadline; current lease is checked under unit ownership, complete influence is prelocked and revalidated | REQ-2, REQ-3, ADR-D3; current Memory heartbeat and manifest contracts | decided |
| M5 | Canonical source writer acquisition and exact offline page revalidation preserve continuity and per-page recovery | REQ-1, REQ-2, REQ-3, ADR-D1/D2/D3; current Memory lifecycle/handover contracts | derived |
| M6 | Queue claims, read-only inspection, uncertain outcomes, publication and post-commit effects remain unchanged | REQ-2, REQ-3; current execution/Memory/authorization Specs | existing |

## Architecture and ownership

Repositories continue to own transactions. There is no global transaction wrapper, new coordinator, root mutex, state store or runtime mode. Purpose-specific typed operation helpers may be shared only by the enumerated entrypoints. Identifiers, helper layout and detached planning data are implementation details, not new authority.

### Hierarchy: three removals

- Remove `AgentSessionRepository.lock_by_id_nowait`; `_admit_mutation` uses blocking NO KEY UPDATE on the sorted exact source/target Session set, with existing capacity root gate only where needed.
- `lock_root_tree_sessions` ordinarily acquires the root membership node and complete sorted Session set. Remove its NOWAIT-only savepoint loop. Missing root still returns the existing empty result; contention never means a partial tree.
- Four Subagent owning mutations (`spawn`, `send_message`, `followup_task`, `interrupt`) repeat only their complete failed DB transaction.
- Seven tree owners are chat archive/restore, chat Stop, archived purge prepare/finalize, Agent retirement and owner retirement. Cleanup between prepare/finalize is outside recovery.
- Terminal victim closure: four Worker terminal operations; seven Engine finalization operations; failed-run finalization; standalone terminal finalization and result delivery. Their composing in-session helpers are not decorated. Tail commits remain inside the recovered operation; no successful result escapes a failed commit.
- SQLSTATE-confirmed abort recovery occurs after scope exit and release, with cancellation propagated and no new retry count/time limit. Original source generation/Run/task identity never refreshes to gain authority. Ownership loss remains ownership loss, not a failed tool result.
- Broker/UI notifications, model/tool/provider execution and materialization remain outside these DB operations. Mailbox enqueue and Run disposition stay atomic and idempotent.

### External account/OAuth: seven removals

- Claim ordinarily acquires Section advisory -> User -> auth Session -> exact OPEN Attempt; refresh ORM state, DB time, status and all exact context predicates after waiting. Elapsed auth/Attempt expiry or revoke/disable denies claim; exchange is never entered.
- Finalization acquires Section -> User -> auth Session -> exact CLAIMED Attempt -> current active Link. Recheck User/auth expiry after Link acquisition; do not add a new post-exchange Attempt-expiry contract. Retain uniqueness conflict reconciliation and existing three DB-only attempts.
- Claim and finalization remain separate owning transactions around one provider exchange. No guessed claim/finalization timeout or service-wide retry is installed. Cancellation/DB failure rolls back before propagation; finalization never exchanges again.

### Native model settings: twelve removals plus advisory

- Keep current 250ms per-acquisition lock timeout and three complete transaction attempts; this is not a whole-operation deadline.
- Apply locks exact draft and actual routing participants in Connection -> Route -> Resource -> Binding order, then the same authorization advisory key before Principal/Agent exclusive fences.
- User precedes active Link; Agent precedes root AgentSession; relevant grants use stable order. All locked rows refresh existing ORM state and exact discovered identities are validated. Rerun authorization and obtain DB time after the final wait, including draft expiry/cancel/applied/fingerprint checks.
- Reopen refreshes current authorization and time after its draft wait before flushing.
- Replace the advisory helper's boolean/nowait mode with unconditional `pg_advisory_xact_lock`; update grant/block callers and remove synthetic busy plumbing once unused.
- Retain immutable replay as a descriptive read, one profile generation, unique audit and unknown notice plan. Notice delivery is post-commit and replay does not send another notice.
- Residual archive/web-profile inversions are handled by existing Apply timeout/full rollback and fresh retry; do not claim a universal lock order or expand unrelated lifecycle architecture.

### Historical Memory: eight removals

- Agent and membership locks remain shared; complete sorted root/source manifests remain shared and never partial. Unit/attempt ownership locks retain existing modes.
- Install SQL/async attempt cutoff before the first potentially blocking acquisition. After locking the original unit/attempt, read DB time and the current renewable lease, reject true loss, and narrow the operation timeout to the current lease and immutable attempt cutoff.
- Complete-influence operations preplan exact draft/attempt/revision evidence and complete source IDs without treating them as authority. Acquire Agent/grant -> complete sorted roots/sources -> unit/attempt, then revalidate owner, epoch, revision and complete current influence. Changed planning evidence triggers full rollback and same-operation restart. The finite closure is twelve manifest-owning entries: draft inventory/observe/replay-receipt/mutate; budget authorize/reserve-model/reserve-tools; operations begin; recovery prepare (both revision and draft branches); work record-coverage; publication freeze/private publish. Composing influence helpers are covered by those owners. Record-usage and quota-advance have no manifest acquisition and retain ordinary owner admission. Three new-exposure entries additionally prelock their exact candidate sets: source inventory/read and work page. Candidate routes, filters and IDs are revalidated under ownership; a fresh query cannot expose additional unlocked rows. Include recovery's immutable revision dependencies and the absent-draft seed case; do not rely on old draft IDs alone.
- Heartbeat uses Agent/grant -> unit, with no manifest. An independent heartbeat can extend the lease while source/authority admission is blocked; no periodic synthetic lock timeout is added. A truly long unit-owned write can still expire normally.
- Stage 1 preparation and publication explicitly acquire Agent -> associated membership -> root Session -> canonical source, then fresh eligibility/generation/grant predicates. Remove joined unspecified ordering and source-before-root/Agent admission. Provider summarization remains outside DB recovery.
- Lifecycle continuity ordinary source acquisition remains atomic in its actual parent operation, including availability generations and exact enrollment. Enrollment does not acquire units; source/grant FK/unique writers remain part of verification. The Agent memory-toggle admission guard uses the existing sufficient NO KEY UPDATE mode (`key_share=True`, without `read=True`) rather than FOR UPDATE: it protects non-key settings while allowing enrollment's Agent FK KEY SHARE. This removes the concrete toggle-Agent -> source / archive-source -> Agent-FK cycle without adding another retry family. Candidate page planning includes pagination lookahead where it affects the returned cursor/has-more signal, with exact revalidation before exposure.
- Offline unit/source pages ordinarily wait, then recheck actual reset/eligibility/quiescence predicates. Candidate discovery is bounded only by the existing page size. Explicit sorted Agent/grant/root/source acquisition replaces the joined lock. Confirmed abort repeats only that page from its committed cursor, never the entire handover. Ambiguous page commit is not blindly repeated.

## APIs, state, migration and rollout

Public APIs, payloads, events, tables, indexes, grants, source generations, output formats and generated clients are unchanged. No migration, backfill or production setting edit is needed. Only lock waiting/recovery within existing operations changes. Deliver one focused PR; do not merge or deploy. Rollback is a code revert that leaves existing persisted idempotency/ownership state compatible.

## Failure and operational risks

- Denied/expired/stale authority and business conflict remain authoritative failures. They are not contention signals.
- Recover only database-confirmed aborts after full scope closure; uncertain commit retains existing durable inspection/idempotency. Do not retry arbitrary DBAPI/connection failures.
- Waiting operations retain actual cancellation/deadline boundaries. No claim/page/public request is asserted to have a local finite timeout unless code establishes one.
- Existing logging/error ownership remains unchanged. No provider data, token, code or private body is persisted for retry.
- Deadlock victim selection and new manifest influence must be tested. Static ordering alone is insufficient evidence. A failed test returns to local safe replacement analysis, not convenience-based retention.

## Removal and Replacement

| Existing behavior | Removal authority | Replacement/remaining authority | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| 30 direct SQL NOWAIT modifiers | REQ-1, ADR-D1 | M1/M3/M4/M5 exact waiting fences | Enumerated production sites | AST/caller census plus held-writer tests |
| Hierarchy NOWAIT helper and fragment loops | REQ-1/3, ADR-D2 | M2 complete owning operation recovery | Four mutation/seven tree owners and terminal closure | No helper/loop callers; both-victim regressions |
| Try-advisory mode and synthetic conflict | REQ-1, ADR-D1 | Same-key blocking advisory and existing model retry | Authorization helper/all callers | No `pg_try_advisory_xact_lock` or boolean mode |
| Source-first/joined unspecified locking | REQ-2, ADR-D3 | M5 explicit exact participant acquisition | Stage 1 and handover DB owners | Acquisition-order and current-authority tests |
| NOWAIT-specific lock intent/tests/spec prose | REQ-1/2/3 | Blocking/recovery/cancellation acceptance evidence | Related tests and Living Specs | Search plus spec review |
| State/configuration/generated surfaces | None: no obsolete persisted or generated surface found | Existing schemas/APIs/modes unchanged | No migrations/client edits | Diff and catalog validation |

Historical implemented documents are retained unchanged. New snapshot Requirements/Design become immutable only after verification.

## Test Strategy

E2E primary product matrix retains existing assembled Memory publication/workspace cleanup, web Session/Subagent Stop/archive/restore and authenticated external authorization/model flows in required CI. This patch introduces no new UI, fixture API or live provider prerequisite. Deterministic PostgreSQL repository integration is the primary diagnostic evidence for internal lock graphs because browser timing cannot reliably choose a deadlock victim or observe unit/heartbeat ownership.

Fixtures use the existing migrated isolated PostgreSQL test database and detached Agent/User/Session/Run/source/draft state. No production DB or paid provider call is required; provider/exchange/notice counters are credential-free fakes. Use explicit query/DB lock-observation barriers, not sleeps to establish ordering. Elapsed time is used only for actual expiry/deadline behavior.

Required focused matrix:

1. Each changed row/advisory family: hold a writer, observe actual wait, release, same operation commits once.
2. Hierarchy: parent send/child terminal and root gate/activity cycles, both possible victims, complete subtree/capacity, sibling cross-send, stale generation/Stop while waiting, cancellation releases partial locks.
3. External: held User/auth/Attempt/Link and every model guard; post-wait expiry/revoke/configuration/target/grant loss; one claimant/exchange, one generation/audit/notice; inherited busy exhaustion and immutable replay.
4. Memory: held Agent/grant/root/source/unit, same captured model response/claim, independent heartbeat extension past original lease, absolute attempt exhaustion/cancellation, newly changed manifest epoch/revision, authority denial and no partial/full-manifest omissions.
5. Source/lifecycle/handover: concrete former writer inversions, exact availability/enrollment atomicity, all three handover actions, post-wait actual false preconditions, page retry without earlier-page replay, no unit locks in enrollment.
6. Non-contention/ambiguous commit propagates without retry; external-effect counters, durable mailbox/receipt/audit/publication counts remain one.
7. Census reaches target zero direct row NOWAIT/try-advisory while SKIP LOCKED/queue APIs remain unchanged.

Evidence: record commands, final revision, counts and concurrency outcomes; run focused suites, integrated Memory/source/external/hierarchy suites, full backend pytest, Ruff and configured type checker, independent review and spec-impact review. Required failures are corrected, never silently skipped. Optional paid/live journeys are not invoked without prerequisites and authorization; existing required CI E2E must pass at final PR SHA. No generated output or credential snapshot is committed.

## Authority and feasibility validation

The three bounded current-code investigations establish exact declarations, reachable owning callers, real writer edges and safe DB/external boundaries. REQ-1 maps to all removal groups, REQ-2 to fresh fences/time/manifest checks, and REQ-3 to complete rollback scopes and one-time effects. No mechanism uses discovery or approval as authority. Independent authority validation cleared M1–M6 within the confirmed scope. Independent static feasibility validation found the design feasible for implementation after correcting the twelve manifest plus three exposure closure, pagination lookahead, FK-compatible Agent toggle guard and pre-unit attempt/current-lease scheduling. No remaining architectural blocker was identified. Recovery retains its existing denied/invalid-manifest invalidation and rebuild outcome: missing or denied participants must not become perpetual replan retries. Only a genuinely changed planning snapshot is a local replan signal.

The implemented concurrency matrix, integrated regressions and targeted production re-reviews passed. Whole-backend verification completed with 10,982 passed and three pre-existing skips, alongside Ruff, formatting, type checking and catalog validation. All 30 row NOWAIT declarations and the active try-advisory branch were removed without a retained exception. The individual register and overlapping focused evidence are recorded in the [validation register](locking-nowait-validation-2026-10-06.md). Final-SHA required CI remains a delivery gate, not new implementation authority.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-10-06` (KST)
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`
- Approved scope: all inventoried nonwaiting acquisitions are replaced with exact waiting fences and finite DB-only recovery, preserving authority, current renewable lease, complete manifests, cancellation and one-time external effects.
- Approval record: after the complete documents and clear authority/static-feasibility results were presented, the requester directed modification. No new product mode, authority, budget or external replay is authorized. Any material scope change returns to the requester.
