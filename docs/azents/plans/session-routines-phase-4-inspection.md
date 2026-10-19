---
title: "Session Routines Phase 4 Inspection"
created: 2026-10-19
tags: [routine, implementation, plan, frontend]
---

# Phase Execution Plan

- Phase: 4 of 5, authorized read-only inspection and semantic activity presentation.
- Branch/base: `feat/routine-261018-4-inspection` -> `feat/routine-261018-3-execution` at `9c61a379663b3ef4397b1387f490c75954b7f96e`, rebased onto main `2bdbcc2e187fecb0a279553606bfb0801b8238fc`.
- PR boundary: Session Routine inventory/detail read APIs and generated clients, Session supporting-panel UI, low-emphasis judgment disclosures and localized Routine tool presentation.
- Inputs: [Requirements](../requirements/routine-261018-session-routines.md), [ADR](../adr/routine-261018-session-routines.md), [Design revision 2](../design/routine-261018-session-routines.md), [implementation plan](session-routines-implementation-plan.md), [Phase 3 PR #2335](https://github.com/azents/azents/pull/2335). Phases 1 and 2 are PRs #2328 and #2329.
- Approved Design mechanisms: M8; integrate M1, M6, M7, M9 and existing M11 authorization. M12 execution remains unchanged.
- Authority references: REQ-15, REQ-16, REQ-17; definition/record contracts from REQ-1, REQ-9, REQ-13, REQ-14; ADR-D2/D3/D4; current Session Context Inspector, conversation, Scheduled Task and Agent execution Specs.
- Design delta: None.
- Primary implementation, integration, validation and correction owner: `/root`.
- Single independent read-only reviewer: `/root/routine-reviewer`.
- Deliverables: exact authorized Session inventory/detail; wrapped objective/source/latest execution/retained records with distinct result, hint, notification choice/message/delivery; low-emphasis initially collapsed judgment indication and available model/call usage; separate Routine activity category and localized known-tool actions with truthful non-success details; desktop/mobile and keyboard coverage.
- Non-goals: management mutation APIs or UI, manual execution, new timing or notification policies, execution lifecycle changes, arbitrary destinations, new judgment retention limits, definition versioning, new generic activity-group framework, private reasoning generation, production rollout.
- Interfaces: API routes call a service; one completed read-only repository snapshot authorizes the exact requested Agent/Session and current public Session resource access, then returns detached definition/record data. No parent/root fallback or write lock is used. Frontend tRPC queries use generated public-client functions. Shared Session core owns reusable typed history/activity projections; the Web layer owns localized UI. Existing ordinary turn-marker usage and prompt/context provenance remain authoritative.
- Removal obligations: explicitly extend affected closed event/activity/panel/tool unions and all consumers; replace raw-name/JSON primary summaries for known Routine tools with semantic rendering. Retain generic diagnostic fallback for unknown or invalid tool payloads. Keep passive judgment separate from tool groups and ordinary usage; preserve existing Scheduled/Goal/Channel behavior.
- Absence verification: no Routine mutation route/button/form/manual Run; no arbitrary metadata dispatch or alternate execution owner; no judgment usage adoption by ordinary gauges/activity usage/context; no successful mutation copy for rejected/failed/cancelled output.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Authorized inspection reads | /root | `repos/routine/inspection*`, `services/routine/inspection*`, narrow `api/public/chat/v1/{__init__,data}*` and API tests | existing definitions/records and Session resource authority | bounded exact-Session list/detail reads, no mutations | real DB and API tests: inventory/detail/empty/deleted/not-executed, wrong Agent/Workspace/member/private owner, archived/unavailable; read-only scopes |
| Generated contracts | /root | public/admin OpenAPI and generated Python/TypeScript clients | stable read DTO/routes | source-generated wire contract | OpenAPI dump, client generation/tests, full consumer type checks |
| Read-only Session panel | /root | `features/session-routines/**`, Session panel types/refresh/navigation/tests, `ChatSessionView`, `AgentSessionPage`, tRPC router/composition | generated API | list/detail within Chat Session context; desktop panes/mobile Back; wrapped long content and distinct loading/empty/error states | static stories and play assertions, locale tests, component build and actual desktop/mobile browser rendering |
| Judgment history | /root | Session-core typed projection/types and tests; Web Chat event projection, dedicated disclosure component/stories and transcript rendering | existing routine_judgment events | initially collapsed Routine label, considered candidates/Structured decision/failure/model/available call usage | live/reload projection, passive-usage isolation, expansion/keyboard/long-content stories; no new call/reasoning |
| Semantic tool activity | /root | Session-core activity category/tests; Web known-tool adapter/details/card paths/stories/tests | existing tool arguments/results | Routine grouping; create/list/inspect/context/update/delete/result action summaries; separated intended/actual fields | success/failed/rejected/cancelled/invalid fixtures; update compare/change/outcome; completion objective/result/hint/notification/delivery |
| Localization and integration | /root | aligned existing message namespaces under all locales and tests; phase checkpoint docs | completed components | English/Korean labels and natural non-success copy | web tests, forced lint/format/typecheck, builds, normal usage regressions, docs/diff checks |

## Integration Order

1. Confirm existing read authorization, repository/DTO contracts, Session panel navigation and closed history/activity consumers.
2. Implement bounded authorized read snapshots and routes with real DB/API tests; generate clients from OpenAPI.
3. Add typed reusable judgment/activity projections and regressions without changing ordinary usage selection.
4. Build read-only list/detail components and state containers; connect existing Session supporting panel and generated-client tRPC queries.
5. Add low-emphasis judgment disclosure and semantic known Routine tool presentation, aligned locale copy and static state stories.
6. Run integrated backend/client/Session-core/Web checks and actual desktop/mobile/keyboard rendering. Record any remaining full product E2E obligations for phase 5 rather than claiming fixture checks are product E2E.
7. Freeze the complete integrated phase diff; request one read-only review from the assigned reviewer; root fixes findings and reruns affected validation. Apply same-reviewer targeted re-review criteria only when required.
8. Record checkpoint, commit through hooks, push and create Phase 4 PR before starting phase 5.

## Final Validation

Root owns execution and evidence. Run whole-backend Ruff/format/ty and affected repository/service/API/history/usage tests, generated Python client tests, Session-core and Web unit tests, forced TypeScript typecheck/lint/format, relevant builds and Storybook interaction/render checks. Verify desktop/mobile long content and Back navigation, keyboard expansion/focus, empty/loading/error/not-yet-executed states and no mutation controls. Preserve actual browser evidence and distinguish it from fixture-only results. Run documentation catalog and diff checks. Run a full backend matrix when corrections cross shared interfaces or authorization.

## Scope Drift and Context Checkpoint

Phase 3 is committed and open as PR #2335 at `746f26b80`; its final backend run passed 13,220 tests with 3 skips, expanded integrated checks passed 165 tests, and all three independent findings were closed by bounded same-reviewer confirmation. Its CI is running, not yet claimed green. No phase 4 implementation exists at this checkpoint. Existing UI has a Session supporting panel and Scheduled Task navigation; no Routine read API or inspection entry is present. Existing canonical public Session resource authorization is available and must be reused rather than relying on membership alone. No new product decision or material mechanism is needed. Design delta: None.

Full product E1-E20, live prerequisites, Living Spec promotion, implemented snapshot dates, plan removal and complete stack CI confirmation remain phase 5. No merge, deployment, production migration or live provider/channel test is authorized by this phase.

## Authorized Read and Initial Panel Checkpoint

- Added one completed read-only inspection repository and service. Canonical
  public Session resource authorization checks the exact requested Agent/Session
  and personal-root ownership; Workspace membership alone cannot disclose
  another user's Session. Missing, denied, archived and wrong-Agent reads stay
  not-found-safe. No root/primary Session fallback is used.
- Public Chat GET inventory/detail routes expose current exact content, latest
  occurrence status/times and bounded retained work with independent objective,
  result, hint, notification and delivery fields. Run/owner authority and admitted
  internal context are not exported. No mutation route was added.
- Real DB/HTTP and existing context/DTO regressions passed 26 tests. This includes
  a PostgreSQL-enforced read-only transaction and 101-to-100 record retention,
  private owner versus other Workspace owner, wrong Agent/Session, archive,
  deletion, active/completed work, empty inventory and absent mutation methods.
  Backend ty and focused Ruff/format passed.
- Regenerated public OpenAPI and Python/TypeScript public clients from source;
  admin OpenAPI did not change. Python template/client tests passed 16 tests.
- Added generated-client tRPC queries and an initial read-only Session supporting
  panel with list/detail states, refresh, mobile Back, wrapping and focus
  ownership. Added static stories and four aligned locale namespaces. Locale
  composition initially exposed a redundant namespace wrapper and missing
  registry entry; both were corrected without relaxing structural tests.
- Web unit tests passed 743 tests; forced TypeScript typecheck completed eight
  uncached tasks. Initial no-undefined lint findings were corrected with explicit
  nullable selections. These are partial-phase checks, not final UI validation.
- Storybook build initially failed while loading SWC: its installed native
  package rejected the default Runtime cache because of an untrusted writable
  ancestor. The Runtime's `/tmp` also lacked sticky protection. Root selected a
  private cache below a verified trusted owner-only home directory instead;
  native loading and Storybook build then passed. Product configuration, global
  directory permissions and cache trust checks are unchanged. This is build
  evidence, not yet a screenshot or executed Storybook interaction test.
- Remaining phase scope: finish meaningful read-panel states and actual
  desktop/mobile/keyboard render verification; typed judgment history and
  initially collapsed disclosure; semantic Routine tool grouping, localized
  action/result details and usage/live/reload regressions; final integrated
  checks, stable-diff review, commit and PR. No phase 4 review or PR exists.
  Design delta: None.

## Dependency CI Reproduction Checkpoint

Phase 3 run `39157639739`, attempt 1, passed all four Required lanes and the Web
functional lane. Its duration aggregate failed: Web call time was 535.545531s
against phase 2's 405.018466s (+32.23%, existing 20% limit). The Web call multiset
is identical (32 tests, all passed); the union of Required planned files is
identical (70 files), though adaptive lane assignment differs. Browser, Runtime
gateway and GitHub creation tests contribute distributed increases; setup time
also increased. Neither a product regression nor an environmental cause is yet
proven.

Root preserved attempt-1 metadata, duration report, candidate/base Web timing and
test-plan artifacts before requesting one full unchanged-SHA rerun. Attempt 2
was confirmed queued at exact SHA `746f26b809ea2ec6b8844e0389752ccd5a298271`.
The gate, test coverage and production code are unchanged. CI remains unfinished;
do not claim success or repeatedly rerun without new diagnosis.

## Integrated Phase 4 Validation Checkpoint

- Implemented typed judgment and admitted-work projections, low-emphasis
  initially collapsed judgment disclosure, explicit call-owned usage and
  truthful unavailable/failed/cancelled states. Live/reload regressions preserve
  ordinary message and activity usage. Invalid Structured evidence never becomes
  a synthetic no-action result.
- Added Routine-specific activity grouping and semantic details for all seven
  tools. Identity requires both the reserved Routine source slug and type;
  missing/null/foreign identity remains generic. Requested inputs, actual saved
  output, failed/cancelled calls, duplicate completion and delivery failure remain
  distinct. Added aligned four-locale copy and static component fixtures.
- Root ran whole-backend Ruff/format/ty; Routine repository/service/API and
  canonical Session authorization tests passed 114 tests with three existing
  deprecation warnings. Python generated-client/template tests passed 16.
  Web tests passed 756 and Session-core tests passed 67. Forced TypeScript
  checks ran 18 uncached tasks; a test-only no-undefined finding was corrected
  and the affected Web checks rerun. Counts overlap earlier evidence.
- Root executed the repository's real Chromium Storybook component runner:
  30 tests across three new story files passed. The first run exposed a shared
  mutable heading ref in story args; each render now owns its ref. Synthetic
  user-event key events did not invoke the browser's native details toggle;
  the story tests use clicks and the separate native-browser check verifies
  Enter/Space disclosure behavior. One subsequent tester-iframe initialization
  timed out before any test began; an unchanged rerun passed all 30.
- Storybook build passed with the trusted private SWC cache. Native Chromium QA
  exercised 40 stories at 1280x900 and 390x844, DPR 1, light theme, en-US and
  UTC, with loaded Geist fonts and product CSS/providers. All 80 states passed
  page-error and horizontal-overflow checks; native keyboard disclosure and
  mobile Back/reselection passed. PNG inspection found a shrinking mobile
  Refresh label; the button now keeps its intrinsic width, and the rebuilt
  80-state check and image inspection passed. These are real component renders,
  not full product E2E or authenticated application screenshots.
- Evidence is preserved in the Session verification directory under
  `routine-phase4-final-*`, `routine-phase4-components-final2.log` and
  `routine-phase4-visual/`, alongside the reproduction script. Storybook's
  existing missing global timezone and React script-tag warnings remain
  visible; capture conditions explicitly fix the browser timezone.
- All four stacked branches were mechanically rebased without conflicts onto
  main `2bdbcc2e1`; Phase 1-3 range-diff equivalence and repository hooks passed.
  Phase 4 WIP was restored without conflicts. Exact old-tip force-with-lease
  conditions atomically updated the three open PR branches. Phase 4 is not
  pushed yet; its preserved stash remains a recovery copy.
- Phase 3's old-SHA CI attempt 2 again failed only the duration gate:
  Web 505.819013s against 405.018466s (+24.89%, unchanged 20% threshold),
  with the same 32 passing Web test IDs. No repeated rerun or gate relaxation
  followed. New rebased-stack CI is separate evidence and not yet claimed green.
- Scope drift: no new product behavior, execution owner, mutation route/manual
  Run control, definition versioning or notification destination. Existing
  authority and removal obligations remain satisfied. Design delta: None.
- Stable-diff review by the assigned single reviewer, hook commit, push and
  Phase 4 PR remain pending. Phase 5 E1-E20 product QA, live prerequisites,
  Living Specs, implemented dates and plan cleanup have not started.

## Independent Review Correction

The single read-only review identified one P2 inspection mismatch: an unfinished
Routine retains `phase="started"` when its ordinary host Run fails, so the phase
alone cannot prove active progress. Root changed the four localized labels to
neutral incomplete-work wording rather than introducing a new Run lifecycle or
exporting private execution ownership.

A new real HTTP/DB regression reads the unfinished occurrence while the host
is terminal failed, requests the existing explicit retry, verifies rebinding to
a pending retry Run, and reads the same detached incomplete occurrence again.
The panel story asserts "Work incomplete" and absence of "In progress".
API/inspection/retry tests passed 15 tests; whole-backend ty, focused Ruff/format,
Web 756 tests, Web lint/typecheck and all 30 Chromium component tests passed.
The correction changes no API schema, execution state or retry authority.
Bounded same-reviewer confirmation closed the P2 with no remaining defect in
the correction. The rebuilt Storybook and native 80-state check passed again;
desktop/mobile incomplete-work PNGs were inspected. Hook commit and Phase 4 PR
are next. Phase 2's rebased CI run `39163261112` and Phase 3's `39163260578`
completed successfully at their exact current heads. Phase 1's duration-gate
failure remains open and is not overridden by those results.
