---
title: "Session Routines Implementation Plan"
created: 2026-10-18
tags: [routine, implementation, plan]
---

# Session Routines Implementation Plan

## Approved Baseline

- [Requirements](../requirements/routine-261018-session-routines.md): REQ-1 through REQ-18.
- [ADR](../adr/routine-261018-session-routines.md): ADR-D1 through ADR-D3.
- [Design](../design/routine-261018-session-routines.md): revision 1, approved 2026-10-18 KST.
- Approved mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11`.
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
| 2: Judgment | `feat/routine-261018-2-judgment` | Canonical full-context Structured/no-tools operation, isolated Session judgment event and usage, provider wire contracts and generated event clients | M3, M7, M11 | phase 1 |
| 3: Execution | `feat/routine-261018-3-execution` | Bounded dispatch, Worker-side overlap, Toolkit State, typed inbox/continuation, tools/result/notification, lifecycle and bundled guidance | M2, M4, M5, M10, M11 | phases 1-2 |
| 4: Inspection | `feat/routine-261018-4-inspection` | Authorized read APIs, generated clients, desktop/mobile read-only UI, Routine activity/locales, usage-regression tests | M8; integrates M1, M6, M7, M9 | phases 1-3 |
| 5: Verification | `feat/routine-261018-5-verification` | Complete deterministic E1-E20 coverage, live prerequisites/evidence, Living Spec promotion, corrections and plan cleanup after verification | M1-M11 | phases 1-4 |

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
