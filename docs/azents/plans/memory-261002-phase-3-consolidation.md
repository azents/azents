---
title: "Agentic Historical Memory Phase 3 — Internal Consolidation Host"
created: 2026-10-03
tags: [memory, engine, backend, implementation, security]
---

# Phase 3 Execution Plan

- Branch/base: `feat/memory-261002-3-consolidation` → `feat/memory-261002-2-storage-vfs`, exact parent `d639f001cf32106e40c410266161b2033148fd3c` / PR #2085. Phase 1 dependency: PR #2069.
- Inputs: confirmed [Requirements](../requirements/memory-261002-consolidated-history.md), accepted [ADR](../adr/memory-261002-consolidated-history.md), approved [Design revision 2](../design/memory-261002-consolidated-history.md), [feature plan](memory-261002-implementation-plan.md), reviewed Phase 1 core and Phase 2 scoped storage/VFS.
- Approved mechanisms: M2–M11 and M15; prepare M12 canonical publication envelope without activating foreground assembly.
- Authority: REQ-1–REQ-4/REQ-6–REQ-8; ADR-D1–D7/D10–D13; unchanged current source/Saved/foreground Specs and DB-only transaction constraints.
- Design delta: **None**.
- Implementation/integration/validation owner: `/root`, directly. Exactly one read-only reviewer: `/root/memory-implementation-reviewer`.
- Goal: complete all remaining feature phases and final stack CI without stopping at an individual phase. No merge, live migration, rollout or infrastructure mutation is authorized.

## Deliverables and Non-goals

Deliver a real multi-turn Lightweight internal host on the shared iteration/tool/stream core, an independent RAM-only transcript, a closed scoped source/draft catalog, durable exact work dispositions/recovery, fenced host validation/publication and approved budgets/scheduling/cleanup. Input, failures, telemetry and retry state must not contain another unit's identity/content or a fabricated foreground Run/Session.

This phase does not change foreground automatic snapshot shape/selection, activate the final cutover, add aggregate CRUD/settings/model selectors, reinterpret old snapshots, create shadow/dual-write modes, promote Saved Memory or deploy. Phase 4 owns automatic assembly/live aggregate integration and coordinated cutover/rollback; Phase 5 owns full product E2E/capacity QA, final Spec promotion and plan cleanup.

## Fixed Interfaces

- Continue through `ModelToolIterationCore` and `ParallelIterationTools`; required ordinary tools remain usable without optional V4A. Provider-native lowering/normalization gains an execution-neutral message envelope, preserving every existing foreground provider contract rather than constructing Events with invented Session IDs.
- Candidate resolution/credential transport/health use the Agent Lightweight chain. Physical dispatch admission includes retries, reserves counters/tokens before sending, and fails closed if an adapter cannot honor that contract. Provider continuation cannot cross a candidate change.
- Attempt/unit database authority remains `ConsolidationJobPrincipal`; the heartbeat renews independently every 30 seconds and cancellation/fencing deny late writes. No external I/O occurs during a repository transaction.
- Work pages contain at most 50 exact rows up to the attempt's finite upper sequence. Presentation, evidence, explicit omission/consideration and published disposition are separate durable states. Work arriving/committing late remains independently discoverable.
- `summary.md` is the sole host publication artifact. Required semantic headings are `Historical Context` and `Source Routes`; routes bind exact canonical permitted summary URIs plus nonempty descriptions. Forged managed locators anywhere fail validation. Empty context/routes can publish an explicit empty outcome, not filler. Other private files are not concatenated.
- Canonical self-contained unit rendering includes scope/provenance/data-boundary guidance and all separators within 10,000 UTF-8 bytes. No truncation or peer-dependent budget exists. Final prose merely ends execution; the host rechecks and atomically publishes frozen draft bytes, complete manifests and exact draft-bound dispositions.
- Recovery rechecks all influence and denial continuity; invalidated work/conversation is abandoned and rebuilt cleanly. Draft expiration resets unpublished dependent work, while current-owner work and snapshot-referenced published revisions remain protected.
- Approved limits: attempt 10 minutes, 32 physical model requests, 96 tool calls, cumulative 250k input/16k output with truthful unknown usage, input checkpoint at 70%, 120-second lease, source pages 50, text results 12k, draft 16 files/256 KiB, no-progress threshold 3, preparation default 12/consolidation 2/combined cap 14, five-minute discovery, 24-hour inactive draft eligibility.

## Workstreams

| Workstream | Owner | Owned paths | Depends on | Output / validation |
|---|---|---|---|---|
| Work/recovery/publication repositories | `/root` | `repos/historical_memory_consolidation/{work,publication,recovery,operations,ownership,drafts,authority,discovery,cleanup}.py`, tests; existing scoped models only if a missing approved field is necessary | Phase 2 | Exact dispositions, finite paging, complete manifests, owner-fenced atomic publish/replay, denial cleanup and bounded queries |
| Authored output and envelope | `/root` | `core/historical_memory_consolidation*.py`, new publication/output module and tests | Authority/routes | Whole 10k envelope, forged-route/empty/Unicode tests; no foreground cutover |
| Neutral provider message plumbing | `/root` | `engine/events/{protocols,types,responses_output,openai_responses,pydantic_ai_output,pydantic_ai_lowering,responses_lowering,iteration*}.py`, provider adapters/tests; `engine/model_stream.py`, `engine/run/model_transport.py` | Shared core | No fabricated foreground identity; all lowerers/normalizers and native retry paths retain regression parity |
| Internal host and closed bindings | `/root` | `services/historical_memory/{consolidation*,draft_vfs,source_vfs}.py`, tests; existing `engine/tools` read/mutation factories | Repositories/provider plumbing | Genuine multi-round reads/edits/final host validation; scoped RAM-only history; no Runtime/Saved/Skill/subagent exposure |
| Model route and budget admission | `/root` | `core/model_operation.py`, existing model-operation/health repository interfaces, `repos/historical_memory_consolidation/operations.py`, adapter dispatch gates/tests | Candidate chain | Lightweight-only, quota-only advancement, counted physical retries, token/usage truthfulness |
| Job admission and cleanup | `/root` | `services/historical_memory/{discovery,job,constants,concurrency*,consolidation_job}.py`, `job_runtime/registry.py`, scheduler handler/tests, deployment values for the approved existing concurrency setting | Host | Coalesced independent unit jobs, periodic reconciliation/cleanup, 12+2 limit and recovery without Redis |

## Integration and Verification

1. Complete exact work/disposition/recovery and publication primitives plus direct PostgreSQL tests.
2. Add strict authored-output/envelope validation and empty-outcome tests.
3. Generalize provider message/output plumbing and physical-dispatch admission; run supported-provider foreground regressions.
4. Bind the internal shared-core host, closed catalog, RAM-only history, candidate health and independent heartbeat; run deterministic multi-turn/scoped/cancellation/budget tests.
5. Register discovery/job/cleanup and approved concurrency defaults with tests; preserve Stage 1 source preparation semantics.
6. Root runs focused integrated tests, complete backend Ruff/format/Ty/Pytest, migration parity if schema changes, shared/native regression suites and docs/whitespace checks. Freeze complete integrated diff, request the same reviewer, resolve findings, rerun invalidated checks and obtain required targeted re-review.
7. Record phase evidence, commit and create dependent Phase 3 PR; immediately proceed to Phase 4. Create the full remaining stack before CI monitoring, then own correction until all required checks pass.

## Removal, Scope Drift and Context Checkpoints

Replace the preparation concurrency default 15 with approved 12 and audit deployment settings; verify no old 15 default/reference remains authoritative. Replace any new internal transcript coupling directly with the neutral envelope, not nullable foreground identity fields or adapters that invent Sessions. No second production model/tool orchestration loop, one-shot fallback, publication-submit tool, hidden model mode or body archive may appear.

Retain Stage 1 projection/source preparation, Saved CRUD/settings, source/original-history VFS, public foreground event persistence and existing Runtime semantics. Old automatic packing/snapshot replacement remains explicitly owned by Phase 4 and its QA/Spec obligations by Phase 5.

At every checkpoint record completed behavior, interfaces, commands/environment/evidence, review findings/fixes, exact branch/base/PR, remaining work and risks. Current main risks are neutral provider normalization without regression, physical retry accounting, source work coverage versus prose edits, complete-manifest recovery and cancellation/publication races. These are implementation/validation tasks, not external credential blockers or reasons to stop the end-to-end Goal.

## First Integration Checkpoint

- Added exact presented work identities, explicit considered/omitted choices tied to a draft revision, persisted finite pass bounds, strict whole-envelope/route validation, immutable atomic publication and durable original-outcome inspection. Unseen/peer work is not acknowledged; content drift leaves newer work pending, and archive/restore invalidates contaminated bytes.
- Generated linear migration `66aa52336fc8` after `3be144f78dca` adds local private work/pass fields and a bounded content-free physical-dispatch reservation/usage ledger. Canonical sources, Saved and public route schemas remain unchanged.
- Budget primitives reserve every physical request/tool dispatch before I/O, reconcile known scalar usage idempotently, retain unknown usage conservatively rather than fabricate zero, and durably record actual over-budget usage while blocking later admission/publication. SDK dispatch hooks are not connected yet and physical proxy evidence remains pending.
- Reusable complete-manifest checking now serves draft and published recovery. Recovery keeps authorized partial work, drops whole denied drafts/evidence/receipts, resets unpublished choices, re-enrolls the permitted remainder after publication loss and preserves counters. Expiry/sweeping and full scheduling are still pending.
- Added a separate RAM-only canonical message envelope with no Session/id/time fiction and shared payload invariants. Lowerer/normalizer/transport binding and the actual multi-turn host remain pending.
- Root-owned evidence: initial artifact/publication/storage/migration matrix **49 passed**, budget/publication/storage/migration matrix **53 passed**, recovery/large-manifest/budget/publication matrix **17 passed**, transient/public event invariant regressions **38 passed**. These overlap and are not a summed unique-test count. Whole backend Ty and focused Ruff/format passed at these checkpoints. Environment is Python 3.14 and disposable PostgreSQL 17/Redis containers; no production migration or provider call occurred.
- Phase 3 remains uncommitted and incomplete, with no review/PR yet. Next: candidate health/operation binding, neutral provider lowering/output factories and physical admission hooks, closed real internal host/heartbeat, discovery/cleanup/concurrency, complete integrated validation and the same reviewer. Continue directly to phases4–5 and stack CI afterward; Goal remains active.

## Second Integration Checkpoint

- Connected the independent host to the existing model/tool iteration and parallel-call cores, provider lowerers, transient normalizers and physical HTTP/thread/WebSocket admission. Internal messages and read ledgers remain RAM-only; no Session/Run identity, foreground Memory prompt, Saved write, Runtime, Skill, original-history or subagent surface is bound.
- Added exact pending-work inventory reads, admission-frozen sibling writer observations, current mutation observation advancement and replay protection against installing old revisions. Real multi-turn storage tests cover source reads, draft creation/edits, ordinary applicability feedback, exact coverage, host-only publication, empty outcomes, input checkpoint rejection and uncertain-result inspection.
- Added Lightweight operation snapshots, quota-only route-matched progression and atomic publication settlement. Per-request output reservation is a bounded quarter of the approved cumulative allowance, further clamped by candidate/provider limits and the remaining attempt budget; this leaves room for truthful unknown-usage retry reservations without changing the attempt's approved hard limits or introducing a setting.
- Reused the existing OpenAI WebSocket deployment setting with an independent execution-local transport state. Native HTTP stored-response recovery and WebSocket sends use distinct committed physical reservations; rejected requests retain unknown usage rather than fabricated zero.
- Corrected shared usage normalization: SDK default zero on one missing counter, or unrelated SDK details, is not complete native usage evidence. Explicit native zero remains known. Shared cancellation now quiesces siblings after admission failure and retains original shutdown cancellation if late settlement loses authority.
- Registered coalesced exact-unit jobs and productive continuation, independent 30-second heartbeat and ten-minute supervision, five-minute reconciliation, private-payload expiry/denial cleanup and preparation-triggered dispatch. Cleanup protects live owners and published bytes/manifests, resets only unpublished choices, and preserves an unfinished finite pass when deleting completed private payloads.
- Capacity is preparation default 12 plus consolidation 2, with combined maximum 14 of 16 local slots. The existing preparation setting validates the combination; no new configuration selector was added. Searches found no explicit old concurrency override in the registered Azents chart or Home repository. No deployment or live configuration change occurred.
- Resolved the Job Runtime registry/discovery import cycle at handler composition boundaries. Added safe no-progress warnings and failure labels without recording request/result bodies.
- Root-owned evidence before the final matrix: operation/budget/publication **17 passed**, committed-dispatch journal **3 passed**, multi-turn host **6 passed**, broad Memory/storage/shared-core/scheduler **154 passed**, expanded matrix **162 passed**, provider/host matrix **194 passed**. These overlap and describe distinct checkpoints, not a summed unique-test count. The latest native gateway/cleanup/usage matrix exposed fixture-only SDK usage/schema and HTTP-versus-WebSocket protocol differences; those fixtures were corrected and are included in the final full-backend run.
- Whole-backend Ruff, formatting and Ty pass at the latest code checkpoint. Full backend Pytest is running in Python 3.14 with disposable PostgreSQL 17/Redis containers. Remaining before Phase 3 delivery: inspect the final matrix, resolve failures, verify migration/docs/whitespace, freeze the integrated diff, request the same single reviewer, correct findings, commit and open the dependent PR. Published-revision collection must also protect the actual automatic snapshot references introduced in Phase 4.
- `Design delta: None`. Phase 3 is still uncommitted, with no review/PR yet; Phase 4 has not started. The end-to-end Goal remains active through Phases 4–5 and final-SHA stack CI. No merge, deployment, production migration or automatic cutover is authorized.

## Final Root Validation Before Independent Review

- Whole backend: **7,397 passed, 3 skipped**, with one failure in the old registry assertion that only ingress reruns on coalescence. The approved event-driven preparation/consolidation handlers now also consume coalesced edges; only that legacy test expectation was corrected afterward.
- Corrective integrated matrix: registry, reserved capacity and native consolidation gateway **10 passed**. This includes real PostgreSQL reservation observations before native HTTP continuation retry and WebSocket sends, and conservative unknown-usage settlement. Production code was unchanged after the whole-backend run, so its other evidence remains valid.
- Whole-backend Ruff/format and Ty pass. `git diff --check` and documentation catalog validation pass. Disposable PostgreSQL migration application/parity and recovery tests are included in the backend matrix; no production migration or external-provider generation ran.
- Shared provider usage tests verify missing/default-zero counters remain unknown while explicit native zero remains known. Shared parallel cancellation tests verify late authority failure cannot replace original shutdown cancellation.
- The complete Phase 3 root-integrated diff is ready for the mandatory read-only review by `/root/memory-implementation-reviewer`. Root owns correction and invalidated validation. Review/commit/PR are not yet complete; continue immediately to Phase 4 only after the Phase 3 PR exists.

## Independent Review Correction Checkpoint

- The single reviewer completed read-only inspection of all 68 frozen changed/untracked paths and found one P2 lifecycle gap: initial preparation/runtime resolution and quota handoff occurred outside per-host lease/deadline supervision. No other grounded Phase 3 finding was reported.
- Root replaced per-host supervision with one claimed-attempt execution boundary. The same heartbeat and absolute claim deadline now remain active during recovery, selection, OAuth/runtime resolution, every shared-core host and quota-candidate handoff. Fresh RAM/native transport state still starts per candidate; no second inference loop or authority source was introduced.
- The attempt owns partially constructed/current SDK resources and closes them on deadline, ownership loss, cancellation or completion. Late cleanup failures preserve the original terminal/cancellation cause. A committed publication still wins a heartbeat-loss race during final quiescence by authoritative outcome inspection.
- Root validation after correction: whole backend Ruff/format/Ty pass; initial focused supervision/host matrix **18 passed**; expanded Memory/storage/Job Runtime/shared-core/scheduler integration **192 passed**. Deterministic cases block initial runtime resolution and replacement-candidate resolution, verify renewal before a host exists and across handoff, revoke renewal ownership, and expire the absolute deadline without starting another host or dispatching a model. Publication-race and late-cleanup cancellation regressions pass.
- Correction scope is the private consolidation job lifecycle and its tests; shared provider/authority interfaces are unchanged. The same `/root/memory-implementation-reviewer` completed targeted re-review with **Review-clear**, confirming the frozen correction hashes and no remaining finding.
- Final root-owned post-correction full backend run: **7,406 passed, 3 skipped** in 310.35 seconds with disposable PostgreSQL 17/Redis and Python 3.14. Whole-backend Ruff/format/Ty, documentation catalog and whitespace validation pass. No external generation, production migration, merge or deployment occurred.
- Phase 3 is ready for commit and its dependent PR. Phase 4 starts only after that PR exists; the end-to-end Goal remains active through Phase 5 and final-SHA stack CI. `Design delta: None`.
