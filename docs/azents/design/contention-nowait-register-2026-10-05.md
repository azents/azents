---
title: "Conservative NOWAIT Retention Register"
created: 2026-10-05
tags: [backend, concurrency, memory, reliability]
document_role: supporting
document_type: supporting-audit
snapshot_id: contention-261005
---

# Conservative NOWAIT Retention Register

- Authority: [contention-261005/REQ-1](../requirements/contention-261005-nowait-policy.md#req-1-retain-nowait-only-with-concrete-justification) and [contention-261005/ADR](../adr/contention-261005-nowait-policy.md).
- Frozen census: `584bda0540141481894b0464e306382315443ce9`.
- Paths below are relative to `python/apps/azents/src/azents/repos/`.
- Line numbers identify baseline flag declarations, not moving implementation lines.
- Baseline: 35 direct SQL NOWAIT sites plus one active try-advisory primitive. Remove five direct sites, retain 30 with specific boundary evidence, retain the one advisory try protocol.
- Retention is not a claim that NOWAIT prevents every possible deadlock or that a whole transaction is nonblocking. Ordinary writes/table locks/advisory locks may wait. Recovery and cancellation remain operation-specific.

## Agent and Session hierarchy

| ID | Baseline site | Decision | Concrete reason and retained boundary |
| --- | --- | --- | --- |
| AS1 | `agent/__init__.py:142` | Remove helper | Sole syntactic caller is the writable-profile True branch; both production callers pass False. Delete dormant option and helper; preserve blocking NO KEY UPDATE and authorization. |
| AS2 | `agent_session/__init__.py:1240` | Retain | Subagent source/target admission can hold parent before a child whose terminal delivery needs parent. Savepoint rollback releases partial parent locks and retries. `hierarchy_operation_fences_test.py` proves child terminal progress and stale-owner rejection. |
| AS3 | `agent_session/__init__.py:1635` | Retain | Tree membership gate precedes Sessions, while terminal activity can hold Sessions before implicitly updating the same root node. Collision releases partial gated set instead of waiting through that actual inverse. |
| AS4 | `agent_session/__init__.py:1647` | Retain | Stop/archive/purge requires every tree Session. If later child is held while terminal delivery needs an earlier parent, the whole savepoint-acquired set rolls back before retry. Skipping a child is not valid subtree admission. |

`key_share=True` without `read=True` renders PostgreSQL NO KEY UPDATE. Both live hierarchy retry loops release post-savepoint locks only; preheld outer locks survive. Current production callers enter after reads or as their first database operation. No broad writer-order rewrite or extra send/interrupt capacity gate is part of this work.

## Historical Memory

| ID | Baseline site | Decision | Concrete reason and retained boundary |
| --- | --- | --- | --- |
| HM1 | `historical_memory_consolidation/authority.py:167` | Retain with local operation retry | Producer holds Agent before unit/manifest, while preparation/lifecycle may hold root/source before Agent. Immediate refusal rolls back that partial graph. Fresh DB-only operation retry preserves claim and checks current eligibility. |
| HM2 | `historical_memory_consolidation/authority.py:179` | Retain with local operation retry | Exact personal grant is held after Agent and before unit/manifest; membership/lifecycle writers share these participant rows. Refusal releases earlier authority locks and fresh grant identity is checked on retry. Team scope adds no grant. |
| HM3 | `historical_memory_consolidation/drafts.py:144` | Retain with local operation retry | Complete manifest root set follows owner locks, whereas preparation already holds source before root. Refusal releases prior owner/manifest locks; every root must remain present and eligible. |
| HM4 | `historical_memory_consolidation/drafts.py:159` | Retain with local operation retry | Manifest root-to-source ordering opposes preparation source-to-root. Roll back the complete DB operation, then recheck every source generation/hash/grant; never publish a partial influence set. |
| HM5 | `historical_memory_consolidation/ownership.py:211` | Remove NOWAIT | Terminal metadata has unit-to-attempt order, without Agent/grant/source acceptance locks. Ordinary waiting plus exact active owner/generation/token predicate is sufficient; caller cleanup cancellation remains. |
| HM6 | `historical_memory_consolidation/ownership.py:232` | Remove NOWAIT | Exact RUNNING attempt follows the locked unit; ID/unit/generation/token/state prevents double settlement and stale/completed/new-owner writes. No extra execution authority or hidden cleanup cutoff is introduced. |
| HM7 | `historical_memory_consolidation/lifecycle.py:33` | Retain | Source availability is composed after root/Agent lifecycle mutations hold outer locks. Blocking source can close preparation's source-to-root inverse. Refusal rolls back the parent transaction; this is not automatically covered by producer attempt retry. |
| HM8 | `historical_memory_consolidation/cutover.py:110` | Retain | Manual handover explicitly requires execution quiescence. A contended unit refuses the current page rather than quietly coexist with an active producer; earlier committed pages remain explicit. |
| HM9 | `historical_memory_consolidation/cutover.py:212` | Retain | Manual source reconciliation locks joined source/root/Agent participants and mutates derived enrollment under quiescence. Fast refusal preserves page rollback instead of hiding operational contention; it does not prove global quiescence. |
| HM10 | `historical_memory_consolidation/cutover.py:252` | Retain | Personal source enrollment requires exact current membership inside the same offline page. Contention rejects the page instead of silently waiting through a live membership change; missing eligibility is distinct. |

Repository-level retry repeats only complete rollback-confirmed producer database operations. Actual lifecycle parent transactions and manual handover are different boundaries; do not claim that a decorator makes them automatic same-attempt retries. Lease scheduling refreshes for each fresh operation while the absolute attempt deadline never restarts.

## External account link and OAuth

| ID | Baseline site | Decision | Concrete reason and retained boundary |
| --- | --- | --- | --- |
| L1 | `external_account_link/__init__.py:226` | Replace explicit lock | Exact-owner conditional revoke UPDATE serializes the real mutation; revoked-link replay needs only a scoped ordinary read. Existing bounded DB retry/busy remains, with refreshed auth and expiry after a wait. |
| L2 | `external_account_link/__init__.py:304` | Retain | Claimed-attempt finalization holds Section before attempt and then User/auth/link participants. Nonwaiting partial graph remains inside existing complete DB retry; one-time provider exchange is outside and never repeated. |
| L3 | `external_account_link/__init__.py:361` | Retain | Link owner uniqueness/finalization follows held attempt/User/auth participants while final Apply uses Link before User. Refusal rolls back the finalization graph; different-user identity conflict remains a business result, not generic retry. |
| L4 | `external_account_link/__init__.py:500` | Retain | User disable is excluded during claimed-attempt acceptance, already inside Section/attempt graph. Apply's Link-to-User opposing acquisition is real companion evidence; preserve partial refusal rather than change one edge alone. |
| L5 | `external_account_link/__init__.py:506` | Retain | Auth Session revoke/expiry is checked after held User/attempt guards in atomic link acceptance. Existing finalization DB retry preserves provider exchange separation and exact callback/session identity. |
| O1 | `external_account_oauth/repository.py:128` | Retain | Single-use callback admission holds Section then User/auth/attempt security graph before provider I/O. Preserve current nonwaiting security acquisition, not a new indefinite callback wait or provider replay. |
| O2 | `external_account_oauth/repository.py:136` | Retain | Live auth Session follows the held Section/User guard and protects exact state/session/callback admission. Unacquired security is not successful claim and must release the whole partial transaction. |
| O3 | `external_account_oauth/repository.py:161` | Retain | OPEN-to-CLAIMED selects a sole exact state/provider/config/session/URI winner after security guards. Conditional DML would introduce a different wait/expiry contract; a broader callback redesign is excluded from this scoped implementation. |

OAuth claim has no local contention retry/busy translation in the baseline. Retaining O1–O3 does not claim otherwise or treat absent deadlines as inherently desirable. These are retained as one single-use partial security admission unit; this work does not silently add callback recovery semantics. Link finalization and unlink have existing three-attempt transient transaction handling, but only unlink installs its two-second lock timeout. No numeric policy is invented here.

## External channel model settings

All sites below belong to `external_channel/model_settings.py`.

| ID | Baseline line | Decision | Concrete reason and retained boundary |
| --- | --- | --- | --- |
| M1 | 301 | Retain | Reopening an existing private draft refreshes and persists options; it is a write, not immutable description. Busy rollback preserves live owner/expiry/unapplied/cancelled predicates in the existing bounded transaction retry. |
| M2 | 562 | Remove NOWAIT read lock | Matching accepted mutation identity/target/profile/audit is committed immutable data. Ordinary replay observation retains fingerprint, unique interaction identity and final authority without blocking concurrent notice-outcome writes. |
| M3 | 855 | Retain | Connection is the first shared final Apply lifecycle/config participant after draft. Block/selector writers acquire this same graph; partial refusal is the existing busy contract. |
| M4 | 861 | Retain | Principal identity/eligible-human guard follows connection; callback/refusal must roll back previously acquired final Apply guards rather than wait through another identity writer while retaining them. |
| M5 | 867 | Retain | Connected Binding joins exact route/resource/session target acceptance and competing selection/access lifecycle writers; preserve full-graph rollback on collision. |
| M6 | 875 | Retain | Resource lifecycle follows Binding in Apply; selector/access writers use Resource before Binding. Refusal prevents waiting across that actual reverse order. |
| M7 | 881 | Retain | AgentRoute follows Resource/Binding in Apply while selector locks route/Agent before Resource/Binding. Keep bounded busy rollback rather than a single-edge blocking change. |
| M8 | 897 | Retain | Active identity link precedes User in Apply but follows User in OAuth finalization. Full transaction rollback releases the inverse partial graph. |
| M9 | 905 | Retain | Linked User disable acceptance follows Link; OAuth User-to-Link order is the opposing writer. A plain read or isolated blocking conversion is not equivalent. |
| M10 | 912 | Retain | Root Session lifecycle/profile guard precedes Agent in Apply; Agent configuration writes Agent then active Session profiles. Existing busy rollback is safer than waiting with the reversed pair. |
| M11 | 918 | Retain | Agent config/options follows held Session and precedes advisory/grants; preserve the same Session-to-Agent partial graph and fresh final authorization on each retry. |
| M12 | 944 | Retain | Matching Session/Agent grants are protected after the authorization key while revoke/block may own earlier participants. Refusal rolls back the entire security graph; absence/key protection and current grant predicates remain. |
| M13 | 1427 | Retain | Actual Apply owns exact live draft before the final authority graph; concurrent edit/cancel/Apply must remain serialized and a collision releases this earlier guard. |

Existing model transactions retry at most three times, with a 250ms per-lock timeout and typed busy exhaustion; no provider notice executes inside them. This policy is not a total operation deadline or a claim that every acquisition is instantaneous. Removal of M2 does not remove final authorization or the unique accepted interaction identity.

## Advisory equivalent

| ID | Baseline site | Decision | Concrete reason and retained boundary |
| --- | --- | --- | --- |
| A1 | `external_channel/model_settings.py:928` -> `external_channel/repository.py:3768` | Retain try-advisory | Same Agent/principal transaction key serializes final Apply against absent block insertion and hard-deleted grant revocation. Apply already holds the final security graph; failed key acquisition synthesizes retryable 55P03 and rolls back the whole bounded operation. Treating false as authorization or deleting the key is unsafe. |

Block creation and grant deletion already use the same blocking advisory helper. They are companion ordering participants, not extra NOWAIT sites. `pg_try_advisory_xact_lock` is not an automatic SQL range lock: unrelated inserts/updates must participate in the same key protocol.

## Absence and safety checks

- Production direct NOWAIT after implementation should be 30: hierarchy 3, Memory 8, external 19. Active try-advisory remains one.
- Dead Agent helper and profile True switch/callers must be absent; live Session admission helper remains.
- Changed external and Memory paths must have held-writer release/retry, cancellation, auth loss, exact owner and once-only effect evidence.
- Existing hierarchy partial-lock, offline handover, single-use callback and final external busy semantics remain unchanged.
- Keep queue APIs/SKIP LOCKED and historical records distinct from executable production policy.
