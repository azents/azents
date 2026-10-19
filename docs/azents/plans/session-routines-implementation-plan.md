---
title: "Session Routines Implementation Plan"
created: 2026-10-18
updated: 2026-10-19
tags: [routine, implementation, plan]
---

# Session Routines Implementation Plan

## Approved Baseline

- [Requirements](../requirements/routine-261018-session-routines.md): REQ-1 through REQ-18.
- [ADR](../adr/routine-261018-session-routines.md): ADR-D2/D3 and ADR-D4, which supersedes D1's independent judgment ownership.
- [Design](../design/routine-261018-session-routines.md): revision 2, requester-directed change and implementation authorization on 2026-10-18 KST.
- Approved mechanisms: `M1, M2, M4, M5, M6, M7, M8, M9, M10, M11, M12`; M3 is retired.
- Design delta: None.
- Primary implementation, integration and validation owner: `/root`.
- Single independent read-only reviewer for every complete stable phase diff: `/root/routine-reviewer`.
- Review corrections and all integrated checks remain root-owned.
- Original main and current refreshed main: `f045c138934aedb935baa538af93afc4489762d8`.
- No merge or production deployment is authorized by implementation approval.

## Delivery Shape

Create a five-PR stack, with reviewable implementation boundaries rather than
separate administrative/design-only PRs. Open each phase PR before starting the
next phase; construct the complete stack before waiting for all CI. Use titles
`session-routines [n/5]: <phase>`. Later phases target their preceding branch.

| Phase | Branch | Scope and interface | Mechanisms | Dependencies |
| --- | --- | --- | --- | --- |
| 1: Foundation | `feat/routine-261018-1-foundation` | Definition and record contracts/persistence, safe management primitives, Primary ownership/backfill, schema migrations and focused tests; approved documents and plans | M1, M6, M9, M11 | main |
| 2: Judgment | `feat/routine-261018-2-judgment` | Retained canonical Structured/no-tools call and isolated judgment observation contracts; no background lifecycle is activated | M7, M11; call contract retained by M12 after M3 retirement | phase 1 |
| 3: Execution | `feat/routine-261018-3-execution` | Bounded tick admission, internal judgment inbox action in the ordinary Run loop, Toolkit State, selected-work FIFO/continuation, tools/result/notification, lifecycle and bundled guidance; remove unactivated separate judgment ownership | M2, M4, M5, M10, M11, M12 | phases 1-2 |
| 4: Inspection | `feat/routine-261018-4-inspection` | Authorized read APIs, generated clients, desktop/mobile read-only UI, Routine activity/locales, usage-regression tests | M8; integrates M1, M6, M7, M9 | phases 1-3 |
| 5: Verification | `feat/routine-261018-5-verification` | Complete revised E1-E20 coverage, live prerequisites/evidence, Living Spec promotion, corrections and plan cleanup after verification | M1, M2, M4-M12 | phases 1-4 |

No phase activates a separate retry mode, destination fallback, definition version
history or generic tool-group framework. A new material mechanism returns to the
technical design workflow; a local detail within approved contracts does not
require renewed product approval.

## Interfaces and Integration

- Routine definition identity/content, source and retained-record contracts are
  shared by repositories, execution and later read APIs. Exact-content update is
  enforced in database owner operations.
- Session Primary refers to one authorized connected Binding, not an arbitrary
  destination on each Routine. Backfill preserves all Bindings and rejects
  ambiguity.
- Judgment appends a typed Session observation, never a normal turn marker,
  foreground phase, prompt snapshot or context-usage update.
- Judgment execution is an internal inbox action consumed by the existing Run
  loop. Reuse normal Session/Run/action owner and recovery; remove the unactivated
  separate judgment lease/pending-job lifecycle. The host Run retains its
  ordinary lifecycle, without forcing assistant inference for no-action.
- Toolkit State and typed Mailbox input own admitted work and continuation in the
  Scheduled execution model. Result submission settles one item only.
- Canonical result recording commits before optional authorized one-attempt
  publication; uncertain delivery is not replayed.
- Public API/event changes regenerate clients; frontend mutations are out of scope.

## Removal Obligations

Follow the approved Design removal table in the owning phase: no Routine use of
text-flattening structured helpers (phase 2), no normal turn/output mutation for
judgment (phase 2), no Scheduled Run-terminalizing result reuse (phase 3), and
explicit closed-union extensions instead of metadata fallback (phases 2-4).
Retain existing Scheduled/Goal/Channel behavior and all existing Bindings. Verify
absence through captured model requests, event history, partial-completion tests,
usage/prompt regressions and existing suites. No deployed Routine subsystem exists
to delete. Generated clients and bundled skill/locales are source-generated or
updated in their owning phase.

## Validation and Prerequisites

Each phase runs focused Ruff, type checking and tests; integration remains root
owned. Full behavior is proven through Design E1-E20 E2E matrix, deterministic
clock/model barriers, ordinary tools, API/history observations and Web inspection.
Provider contract tests cover all canonical lowerers, Structured/no-tools wire
requests, saved capabilities, native terminal proof, cleanup and normalized usage.

Docker client/server were observed available. Backend frozen dependencies have
been installed. No managed Session development environments were listed. A local
Session-owned E2E environment and generated clients still need preparation; no
other Session's data or credentials may be imported. Live provider/channel tests
are optional only with explicit prerequisites and safe destinations. Production
Binding cardinality has not been audited; the rollout preflight and ambiguous
migration fixture remain mandatory. No credentials belong in Git or evidence.

For runtime QA use an isolated Session-owned development environment and its
observed paths. Record readiness, actual API/browser and Runtime file/Shell checks, and
stop/restart persistence. Unit checks are not substituted for that evidence.

## Spec, Rollout and Cleanup

Run one complete spec review before final QA, update current Routine/domain and
execution/periodic/channel/lifecycle Specs, then mark matching Requirements and
Design implemented only after verified implementation. Phase-local schema changes
must document any behavior that cannot wait. Do not mark design claims as current
behavior prematurely.

Verify migration graph/revision, no ambiguous Primary selection and no unsupported
binary downgrade assumption. No production migration, automatic merge or
production notification is part of this plan.

Remove this plan and phase execution plans in phase 5 only after verified spec
promotion. The completed snapshot and useful verification evidence remain.

## Checkpoints

2026-10-18 KST: Design approved and implementation requested. One read-only
reviewer assigned and ready. Exact main unchanged after explicit-refspec fetch.
Phase 1 is preparing; no implementation tests or product behavior claimed yet.

2026-10-18 KST, phase 1 delivery: [PR #2328](https://github.com/azents/azents/pull/2328)
opened from `c925300a1`. Definition/record/Primary foundation was validated with
330 tests, full backend ty and commit hooks; independent P2 findings were closed.
CI exposed one historical Memory migration fixture coupled to current Session
ORM. The root-owned test-only correction `ab7834c36` passed the exact PostgreSQL
test and hooks, received clean bounded review from the same reviewer, and was
fast-forwarded onto the foundation branch. No production behavior was changed.

2026-10-18 KST, phase 2 implementation: canonical Structured/no-tools operation,
isolated typed observation/usage, PostgreSQL event migration and generated clients
are implemented. Two independent P2 findings were corrected and closed by targeted
same-reviewer verification: full custom-call history preservation and actual
Structured/output-tool capability context. Root validation passed 1570 integrated
backend tests, full backend ty/Ruff/format, generated-client template tests (16),
forced web/admin/session-core type checks and Session core tests (58)/lint/format.
Phase 2 [PR #2329](https://github.com/azents/azents/pull/2329) is open at
`6f795908e` atop the corrected foundation `ab7834c36`, with all commit hooks
passed. Post-rebase focused historical-fixture/judgment/DB checks passed 25 tests.
Phase 3 branch and execution plan are prepared. Scheduler/admission/notification
activation, inspection UI and product E2E remain phases 3-5. Design delta: None.

The initial phase 2 CI exposed PostgreSQL/ORM event-enum ordering drift. The
unmerged migration now inserts the judgment label at its declared position;
the dedicated migration suite (50 tests, including the exact DDL comparison)
and focused migration/persistence tests (2) passed before the correction was
pushed. Phase 1 CI is fully green. Phase 2 run `39134760932`, attempt `2`,
completed successfully at `6f795908e`. The unchanged Web duration gate passed
at 405s against a 427.6s baseline; the first attempt's distributed slowness remains
unexplained rather than attributed to a proven environment fault.

Phase 3 now follows requester-directed ADR-D4 and Design revision 2: judgment is
an internal inbox action processed by the ordinary Run loop, not an independent
background lifecycle. Unactivated judgment lease/claim machinery has been removed.
Source continuity, admitted Toolkit State, typed ordinary FIFO presentation,
database-only inbox admission/capture/settlement, canonical provider preparation
and internal operation dispatch/cancellation are implemented locally. Initial
no-action execution is verified without ordinary foreground preparation/inference.
Source-only Scheduler admission and resumed/subsequent Run boundary tests are also
implemented. Root-only tools, atomic per-item results, one-attempt current-Primary
or Session-chat delivery, normal idle continuation and compaction continuity are
connected. Explicit Stop composition also preserves definitions/completed work
while closing incomplete attempts under the normal owner fence. Archive/restore/
purge participation and narrow preserved-work owner recovery are connected.
Canonical Run input associations reject mixed ordinary work; purge waits without
fencing work still allowed to finish and verifies Routine namespace absence before
root deletion. The latest expanded matrix passed 627 tests; a separate overlapping
Event/Stop matrix passed 1,295 tests. Ordinary explicit failed-run retry now
atomically rebinds only incomplete started Routine occurrences to its existing
new pending Run, preserving admitted context and original start time. Completed
items remain complete. Bundled guidance and source-generated contracts are ready.
Internal judgment remains durable but is excluded from public pending/live action
execution and composer projections. The final backend run passed 13,214 tests
with 3 skips; Ruff, format and whole-backend ty passed. A separate final focused
Routine/retry/lifecycle/retention/fixture suite passed 139 tests. Forced TypeScript
typecheck/lint/format completed all 18 tasks; both regenerated Python clients
passed 16 tests each. The single independent review found three corrections:
expected judgment preparation failures now settle without stranding the queue;
ordinary Routine inputs contribute to the existing context breakdown without
judgment usage; and bundled guidance chooses Routine versus Scheduled Task by
output obligation. Root's post-correction full backend run passed 13,220 tests
with 3 skips in 318.85s, the expanded integrated suite passed 165 tests, and Ruff,
format, ty and skill packaging passed. These matrices overlap and are not
additive. Bounded same-reviewer confirmation closed all three findings without
remaining issues. Commit and Phase 3 PR creation are next. Phase 4 has not
started. Design delta: None.
