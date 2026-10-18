---
title: "Session Routines Phase 3 Execution"
created: 2026-10-18
updated: 2026-10-19
tags: [routine, implementation, plan]
---

# Phase Execution Plan

- Phase: 3 of 5, bounded checking, ordinary execution, independent completion and lifecycle integration.
- Branch/base: `feat/routine-261018-3-execution` -> `feat/routine-261018-2-judgment` at `6f795908e`.
- PR boundary: activate approved checking and execution through existing Scheduler, internal inbox action/Run loop, Session FIFO/Toolkit State and lifecycle boundaries; retain read-only inspection UI/API for phase 4.
- Inputs: [Requirements](../requirements/routine-261018-session-routines.md), [ADR](../adr/routine-261018-session-routines.md), [requester-directed Design revision 2](../design/routine-261018-session-routines.md), [implementation plan](session-routines-implementation-plan.md), foundation [PR #2328](https://github.com/azents/azents/pull/2328), judgment [PR #2329](https://github.com/azents/azents/pull/2329).
- Approved Design mechanisms: `M2, M4, M5, M10, M11, M12`; integrate existing M1/M6/M7/M9. M3 is retired and its unactivated separate judgment ownership is removed.
- Authority references: REQ-2 through REQ-14, REQ-16 and REQ-18; ADR-D2/D3/D4; existing Scheduled Task, periodic execution, Agent execution, Conversation lifecycle and External Channel delivery Specs.
- Design delta: None.
- Deliverables: 30-minute bounded Scheduler source admission and typed internal judgment inbox action; judgment inside the ordinary Run loop using existing action/Session owner and canonical context; atomic judgment observation/selection admission; immutable admitted Toolkit State; typed selected-work FIFO and continuation; root-owned Routine tools and guidance; per-item idempotent completion with separate one-attempt authorized delivery; ordinary Stop/shutdown/archive/restore/purge participation.
- Non-goals: inspection UI/read APIs, unsupported sources, immediate check on creation, exact-threshold timers, semantic freshness checks/rejudgment, alternate model/fallback, delivery retry/outbox, generic tool-group framework, independent Routine-domain execution table or deployment role, production rollout.
- Interfaces: the Scheduler performs bounded database admission and ordinary wake publication only. An internal judgment action runs at the existing Run loop's normal FIFO/action boundary. Ordinary inbox/action execution owns pending work and recovery, not a separate Routine lease or Worker JobRuntime task. Source bookkeeping and admitted item snapshots remain in Toolkit State. Selected work retains immutable context; completion settles only one item, never unrelated Run/Channel Work.
- Removal obligations: remove unactivated judgment-specific pending snapshots, claim/lease/handover operations and obsolete tests; no judgment JobRuntime handler/scanner. Do not connect Routine completion to Scheduled terminal submission or use ordinary output admission for judgment observations. Extend closed action/input consumers explicitly. Preserve source-input bookkeeping, admitted context and all existing Scheduled/Goal/Channel behavior.
- Absence verification: partial-result/ordinary-work tests, captured judgment side-effect tests, exhaustive type checks, no Routine execution table/new broker execution envelope, existing Scheduled/Goal/Channel regressions, no automatic resend after uncertain delivery.

| Workstream | Owner | Owned paths | Dependencies | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Source bookkeeping and admitted state | /root | `core/routine*`, `repos/routine/*`, Toolkit State and narrow Session fences | phase 1 definitions/records and phase 2 decisions | typed source/delay continuity and admitted snapshots; remove independent judgment state | competing tick admission, ordinary owner/Stop, deletion/edit/incomplete exclusion and delay tests |
| Internal judgment action | /root | `scheduler/{registry,routine_source_dispatch}*`, typed internal action models/registry, common Mailbox promotion, `worker/run/executor.py`, operation-action executor, `services/routine/*`, shared context composition | source bookkeeping, phase 2 call | bounded Scheduler inbox action; normal Run-loop action execution, neutral no-action, atomic observation/selection and ordinary recovery | FIFO boundary under held ordinary work, no second owner/Run inference, failure/Stop/handover and context capture |
| Ordinary FIFO and continuation | /root | `core/mailbox_data.py`, Session input/continuation contracts, `repos/mailbox/*`, `services/mailbox.py`, `repos/idle_continuation.py`, `worker/session/{inbox,idle_continuation}*`, canonical event variants/lowerers | admitted immutable state | initial full contexts, existing model-boundary polling, current-Run association, first full oldest-incomplete context/rest IDs and context read | FIFO/interleaving/partial completion, deterministic ordering, stop/failure/no-forced-continuation and compaction continuity regressions |
| Tools, results and presentation | /root | `engine/tools/routine*`, Toolkit registry/deps/catalog integration, `services/routine/*`, `repos/routine/*`, authorized lower-level External Channel/Session presentation composition | phase 1 operations, admitted authority, current Primary | create/list/inspect/exact update/delete/context/result operations; per-item canonical completion and one-attempt message effect | owner/cross-Session rejection, notify/message cross-field rules, deleted-definition late result, idempotency, Primary/no-Primary/disconnect/failure with no fallback |
| Stop and lifecycle | /root | Routine lifecycle participant and registry dependencies; narrow existing `repos/session_lifecycle*`, `repos/user_stop*`, worker finalization/cleanup composition | admitted/started item authority and check ownership | archive removes future/pre-start authority, preserves only allowed started work; restore does not recreate; purge waits then verifies absence | real DB archive/mixed ordinary+Routine exemption rejection, restore, stop, preserved completion and purge matrix |
| Guidance and coherence | /root | `resources/vfs/toolkits/routine/**`, bundled skill registration; generated schemas/clients when affected; phase plans | stable tools/input variants | release-bundled Routine guidance and source-generated wire coherence | schema/tool tests, skill projection tests, full backend/consumer type checks and generated client checks |

## Integration Order

1. Read current Specs and exact Scheduled Toolkit State, internal inbox/action execution, ordinary context/prompt, provider publication and lifecycle operations.
2. Fix typed check/admitted/result interfaces, including current-owner/Stop/started boundaries, in core and completed repository operations.
3. Remove superseded independent judgment state; add bounded Scheduler internal-action admission and ordinary Run-loop execution using the phase 2 call and atomic observation/selected admission.
4. Extend FIFO promotion, ordinary current-Run association, typed event lowering, per-item continuation and compaction continuity.
5. Wire root-only automatically connected Routine tools, bundled guidance, independent canonical completion and existing authorized presentation primitives.
6. Integrate Stop/shutdown and archive/restore/purge participation; retain all unrelated active-work protections.
7. Regenerate affected contracts; root runs integrated deterministic/DB regression checks and scope-drift audit.
8. Freeze the complete diff; request read-only review from `/root/routine-reviewer`; root applies findings, reruns invalidated checks, records the checkpoint, commits and opens the phase 3 PR before phase 4.

## Validation and Scope Gates

Root owns focused Ruff, full backend ty, deterministic provider/context capture,
real PostgreSQL claim/admission/result/lifecycle tests and existing Scheduled,
Goal, Channel Work, FIFO, continuation, compaction and Stop/recovery regressions.
Use explicit events/barriers or authoritative committed state for ordering; do not
add fixed sleeps or enlarge test timeouts to conceal races. Capture broker wakes
only after transactions close, and prove lost wakes remain recoverable.

Prepare the deterministic E2E prerequisite seam as needed; product E1-E20 proof
and live prerequisite evidence remain phase 5. A lower-level fixture pass is not
product E2E success. No live credentials, notification destination or production
state is implicitly authorized.

Before review, confirm every changed material mechanism maps to the approved
Design and every required removal has evidence. Local helper names, typed state
shapes and fixture organization remain root-owned. A new lifecycle, configuration,
failure/recovery, permission, timing or source-of-truth mechanism returns to
technical design instead of becoming plan authority.

## Context Checkpoint

Phase 2 PR #2329 is open at `6f795908e` atop the corrected foundation
`ab7834c36`. The same reviewer closed both Phase 2 P2 findings. Root's integrated
suite passed 1570 tests; full backend ty/Ruff/format, forced TypeScript checks,
Session core tests (58) and generated Python client template tests (16) passed.
The post-rebase historical fixture/judgment/DB check passed 25 tests in 14.44s.

Initial revision 1 discovery identified the application JobRuntime; that proposed
judgment ownership was superseded by requester-directed ADR-D4 and must not be
connected. Judgment instead uses the existing internal inbox/action boundary in
`worker/run/executor.py`. `scheduled_task_states` remains infrastructure Scheduler
state; admitted product work uses the existing Toolkit State pattern. Normal
Session/Run/action Stop and recovery fences, ordinary context assembly and provider
effect boundaries remain the integration authority.

No phase 3 implementation is present at plan creation. No merge/deploy/live
provider action has been performed. Design delta: None.

The branch was fast-forwarded to the phase 2 enum-order correction `6f795908e`.
The complete dedicated migration suite passed 50 tests, including CI's exact
DDL comparison; focused judgment migration/persistence tests passed 2 tests.
Phase 1 CI is fully green and phase 2 CI is rerunning. The phase 3 plan remains
unchanged in scope, with no implementation edits at that checkpoint.

### Internal Inbox Replacement Checkpoint

- Revision 2 / ADR-D4 supersedes the unmerged independent judgment ownership
  implementation. Its pending snapshots, physical leases, claim/handover
  operations and dedicated contention tests were removed rather than retained as
  another execution path. No judgment JobRuntime handler or scanner is registered.
- `core/routine_execution.py` now retains source/delay continuity and the queued
  ordinary action identity only. Immutable admitted contexts and explicit
  admitted/started/completed/cancelled item state remain in existing Toolkit State.
- `repos/routine/scope.py` preserves the definition operations' existing exact
  scope authority and Agent-to-Session lock order.
- Added the internal persisted `RoutineJudgmentAction` contract. Public composer
  request decoding rejects it. Operation policy and Run-loop executor registration
  are not activated yet; they must be integrated together with canonical context
  preparation, provider execution and normal action cancellation/recovery.
- Added database-only `RoutineJudgmentInboxRepository`: tick/source coalescing,
  existing Mailbox admission/wake transitions, execution-time candidate capture,
  and atomic observation/selected-work/state/action settlement. No provider or
  broker I/O occurs inside these transactions. Duplicate settlement does not
  re-admit work; failure retains source input and last-action time.
- Selected work uses typed ordinary FIFO inputs. Promotion binds only current
  admitted occurrences to the consuming ordinary Run; it does not replace that
  Run. Initial presentation includes all selected contexts. Continuation orders
  incomplete work deterministically and presents the first full context.
- Stop state cleanup clears queued action identity and incomplete work. Repository
  tests reject an old settlement both while Stop is set and after its flag is
  cleared. Product Stop/lifecycle wiring remains incomplete.
- Root validation at this checkpoint: full backend ty and focused Ruff passed;
  the complete Routine core/repository, Mailbox/live-event, migration-observation
  and dual-lowerer suite passed 158 tests in 16.47s, with three dependency
  deprecation warnings. The earlier lowerer test failure was a local variable
  shadowing Pydantic during delayed annotation resolution; renaming it fixed both
  cases. Documentation catalog and whitespace validation passed.
- Next: activate the internal neutral operation through the existing registry
  and Run loop, reuse canonical context/provider preparation without ordinary
  usage or prompt mutations, and specialize generic action cancellation cleanup.
  Scheduler registration, tools/result/delivery, continuation hooks, lifecycle,
  generated clients and integrated phase verification remain required.
- No phase 3 reviewer request, commit or PR yet. The full integrated phase diff
  remains root-owned and in progress. Design delta: None.

### Ordinary Context Integration Seam

`poll_run_inputs` executes operation actions before the initial foreground
model-turn preparation and at later model boundaries. Its initial host Run may
still be pending. The existing `_prepare_fresh_main_model_turn` persists
foreground model-operation state, so invoking it merely to obtain judgment
settings would violate the isolated operation contract. The canonical
`resolve_invoke_input_with_profile` / resolved-profile path supplies existing
model selection, settings and credentials without that foreground admission.

`AgentEngineAdapter.run` owns ordinary Run preparation, prompt/usage snapshots and
model execution; judgment must not invoke that entrypoint as a shortcut.
`RoutineJudgmentInboxRepository.capture_transcript` now reads the ordinary
canonical head through `EventTranscriptRepository.list_for_model_input`, matching
the read basis used by compaction/model input without entering their mutation
paths. `build_tool_catalog` / `build_system_prompt` supply the reused normal
toolkit/prompt context assembly. Do not
substitute a text-only prompt, a stale foreground request, or an ordinary model
turn. Normal toolkit binding/preparation and current action owner cancellation
remain part of the integration audit.

### Canonical Hosted Call Checkpoint

- Added `engine/routine_judgment_context.py`: prepare the actual Session static
  and dynamic toolkit context, model/adapter compatibility evidence, native replay
  identity and request-local ModelFile content for the Phase 2 Structured call.
  Export no executable client/hosted tools. Ordinary turn hooks are not dispatched:
  judgment is an inbox operation, not a new ordinary model turn.
- Added `services/routine/judgment.py`: capture execution-time candidates; read the
  canonical current-head history; use the supplied ordinary selected profile and
  existing timeout policy; make one purpose-owned provider call; settle through
  the database-only inbox composition. It does not call `AgentEngineAdapter.run`
  or foreground model preparation, create a Run, replace prompt snapshots, append
  turn markers, or adopt another retry/ownership lifecycle.
- Expected provider/normalized request failures record failed observations with
  unknown usage when unavailable, retain source input and preserve last-action
  time. Invalid completed Structured output retains its observed usage and is
  not converted into no-action. Cancellation propagates to the normal owner.
- Added current-owner cancellation cleanup for the generic action identity.
  Ordinary owner recovery retains sources and can clear the old queued identity;
  repeating cleanup cannot clear a newer action.
- Root validation: full backend ty and focused Ruff passed. The expanded Routine
  core/repository/service, canonical context, provider-wire, dual-lowerer,
  Mailbox/live-event and migration-observation suite passed 206 tests in 17.93s,
  with three dependency deprecation warnings.
- Deterministic official-SDK transport fixtures verify action, no-action, invalid
  output, provider failure, deletion-to-empty-candidates and closed ordinary
  dispatch admission. The latter propagates cancellation without a provider call
  or source loss. Database scope
  instrumentation proves context/provider I/O occurs outside open transactions.
  History before the current canonical head is excluded; the two retained user
  messages remain in the real wire request. There are no live provider calls.
- This checkpoint preceded Run-loop activation. The next checkpoint records
  the internal neutral policy, ordinary context callback and domain cancellation
  integration. Scheduler admission remains unregistered during these checks.
  The callback must use the actual ordinary Session/Run inference snapshot when
  present; before its first ordinary turn, resolve the existing requested profile
  without committing a foreground model operation. Pass the selected profile to
  the existing timeout resolver and bind dispatch admission to the ordinary
  tool-admission barrier. No Routine-specific model or fallback selection is added.
- Phase 3 remains uncommitted, with no review request or PR. Design delta: None.

### Ordinary Run-Loop Dispatch Checkpoint

- `RoutineJudgmentAction` now participates in the closed operation union and
  capability registry. It is internal, has no public composer definition or
  Agent function tool, requires no ordinary inference preparation, and produces a
  neutral preparation effect with no user message.
- Both the initial inbox pass and subsequent model-boundary polling receive the
  same ordinary host resolver. Each action binds the profile currently selected
  by FIFO processing. The resolver reuses an existing exact ordinary inference
  snapshot when applicable, or resolves the ordinary requested profile without
  committing foreground model-operation state before the first model turn.
- Actual context assembly retains normal Toolkit preparation, canonical file
  authority, current host Run identity and ordinary dispatch admission. It adds no
  Routine model, fallback, transport owner, retry, turn marker or Run usage slot.
- The operation executor invokes `RoutineJudgmentService` and reports a neutral
  host effect. The dedicated observation is published only after commit. An empty
  candidate completion removes the internal live action without inventing a
  judgment observation or ordinary model inference. Pending judgment inputs are
  omitted from public chat pending/live message projections.
- Generalized the unchanged operation-result shape from the worktree service to
  `core/action_execution_data.py`. Existing worktree action behavior and result
  semantics are preserved without a legacy alias or second result protocol.
- Ordinary generation mismatch, closed admission and boundary cancellation now
  dispatch exact Routine cleanup through the closed operation registry. The
  worktree domain's live-action listing selects only its five owned types, so
  worktree recovery cannot emit an ordinary worktree terminal event for judgment.
- New executor tests process a no-action judgment through the actual initial Run
  loop and confirm its pending host is cancelled normally without foreground
  preparation or ordinary inference. The same test exercises purpose-owned
  profile/context preparation and ordinary dispatch admission. Registry tests
  verify neutral policy, exact host context, observation/removal callbacks and
  current-owner cleanup. A committed database test confirms worktree recovery
  preserves another operation domain.
- The real MailboxService/DB seam verifies the admitted judgment is detected as
  not requiring inference and promoted into a neutral generic action execution
  with no ordinary input event, user message or inference state.
- Root validation passed 480 tests in 51.03s, including actual worktree services
  and database operations, Worker execution/Stop, Routine domain/provider-wire,
  real Mailbox promotion, pending-message visibility and migration regressions.
  Full backend ty and focused Ruff passed; three dependency deprecation warnings
  remain. Evidence log: `/tmp/routine-phase3-dispatch-integrated.log`.
- Subsequent checkpoints record resumed/subsequent-boundary, source Scheduler,
  root tools, item completion/delivery and ordinary continuation work. No judgment
  JobRuntime handler or background judgment lifecycle is introduced.
- The stable complete Phase 3 diff has not been reached: no reviewer request,
  commit or Phase 3 PR exists. No merge, deployment or live provider call occurred.
  Design delta: None.

### Resumed Boundary and Source Scheduler Checkpoint

- Resumed host execution now has a deterministic test proving judgment reuses the
  exact frozen ordinary physical model candidate rather than resolving the
  Agent's configured first candidate again. It preserves the existing Session
  inference object and does not prepare an ordinary foreground operation.
- A subsequent-boundary test queues judgment after an initial ordinary poll and
  observes promotion, current-profile context preparation and judgment in that
  order. The existing Run remains running, with no user input, forced completion,
  context invalidation or replacement inference state.
- Registered `routine_source_dispatch` in the existing Scheduler at the fixed
  30-minute interval. It only collects sources, admits an ordinary judgment inbox
  action and sends a normal Session wake after commit. It never constructs a
  model request or invokes a judgment/Agent provider.
- `RoutineSourceRepository` uses a DB-enforced read-only dependency and a bounded
  due-root query over existing Routine definitions, Session ownership and check
  timestamps. It excludes inactive, stopped and non-root targets; several
  definitions still select one Session. Each admission rechecks exact live scope
  under the existing Session mutation fence.
- The source pass pages 64 roots at a time until exhausted or the existing
  Scheduler's two-minute deadline. Committed last-tick timestamps remove processed
  roots from the next due batch; no new cursor, lease, discovery worker, execution
  table or judgment retry state is added. Infrastructure failure uses the normal
  next-interval Scheduler policy only.
- Further eligible ticks retain Manual input while the same ordinary judgment
  action is queued. Duplicate/concurrent ticks create one source occurrence and
  one generic inbox action. Definition creation itself still admits no check.
- A broker error propagates after the action/wake transition commits. The durable
  ordinary Session recovery target and pending inbox remain authoritative; source
  dispatch does not implement another retry/recovery mechanism.
- Root validation passed 373 tests in 35.37s across all Scheduler tests, Routine
  repositories/services/core/provider-wire, existing Worker execution, new
  resumed/later boundaries, real Mailbox promotion and live-event/migration
  regressions. Full backend ty and focused Ruff passed. The unchanged worktree
  domain/Worker matrix previously passed 480 tests; these are different test sets,
  not additive totals. Three dependency deprecation warnings remain.
- New database tests cover multi-root paging, multi-Routine joint admission,
  exact 30-minute due boundaries, stopped/recent/empty exclusion, post-commit
  broker failure, deadline partial progress and concurrent committed writers with
  explicit barriers. These are deterministic fixtures, not live provider or
  product E1-E20 proof.
- Root tools, independent results/delivery and ordinary idle continuation are
  recorded in the following checkpoint. Lifecycle, release guidance, generated
  contracts and final phase validation/review/PR remain unfinished. No Phase 4
  work, merge or deployment has started.
  Design delta: None.

### Root Tools, Completion, Delivery and Continuation Checkpoint

- The separate `Routines` auto-bound root Toolkit exposes create, list, inspect,
  exact-content update, delete, admitted-context read and per-occurrence result
  recording. Every tool validates its captured Session/Run authority and ordinary
  execution owner. Subagent resolution omits this Toolkit. Tool descriptions
  explain exact edits, independent notification and honest failed investigations.
- The canonical completion transaction appends the bounded retained work record
  and closes only its admitted occurrence. Repeated identical settlement is
  idempotent; conflicting settlement is rejected. Deletion/edit cannot redirect
  an admitted objective or recreate deleted definitions/records.
- Notification uses committed completion as its sole one-attempt permission.
  Current Primary authority is captured at delivery time and rechecked before
  each existing binding effect. No Primary creates a typed Session chat
  notification Event; invalid Primary or failed delivery does not fall back.
  Results remain complete on failure, and cancellation may leave delivery
  unobserved. Repeated settlement does not replay an uncertain send.
- A dedicated typed notification Event preserves assistant semantic history in
  both supported lowerers without inventing provider-native artifacts or ordinary
  turn usage. The uncommitted generated Phase 3 migration includes its enum value.
  Source-generated public/client contract synchronization remains pending.
- The existing normal idle boundary admits one typed Routine continuation with
  the oldest incomplete full context and identity-only references for remaining
  items. Real inbox admission/promotion rebinds the original snapshots and start
  times to the next ordinary physical Run. Failed/stopped Runs do not force normal
  continuation. Compaction refreshes only its owned obligation section.
- Root validation passed 518 tests in 39.20s across Routine core/repositories/
  services/tools, Scheduled tools, hooks, resolution, Scheduler, Worker Run,
  idle continuation, Mailbox/live-event and migration tests. Full backend ty and
  focused Ruff passed. Three dependency deprecation warnings remain. Evidence:
  `/tmp/routine-tools-idle-integrated.log`. This is deterministic fixture evidence,
  not a production provider call or complete product E1-E20 proof.
- Explicit Stop composition joins the owner-fenced final Stop transaction:
  close admitted/started attempts, remove pending Routine execution inputs and
  preserve completed work, definitions and last-action time. Its real DB tests
  and existing Stop/finalizer regressions pass. Worker shutdown still follows
  ordinary recovery, not this explicit Stop path.
- After Stop integration and notification settlement-boundary refinement, the
  root reran the combined matrix: 555 tests passed in 41.14s, full backend ty and
  focused Ruff passed. A separate expanded Event/lowerer/message/context/Stop
  matrix passed 1,295 tests in 24.08s. These overlap and are not additive totals.
  Evidence: `/tmp/routine-tools-stop-integrated.log` and
  `/tmp/routine-stop-events.log`.
- The following checkpoint records archive/restore/purge and narrow started-work
  exemptions. Remaining work includes ordinary failed-run retry association,
  bundled release guidance, generated contracts, full
  integrated phase validation, stable-diff independent review, commit and PR.
  Inspection read APIs/UI belong to Phase 4 and are not activated here. No reviewer
  request, Phase 3 commit/PR, merge, deployment or live provider call occurred.
  Design delta: None.

### Archive, Preserved Owner Recovery and Purge Checkpoint

- Implemented M10/M11 participation through the current Session lifecycle
  registry and native archive/restore/purge database groups. The required
  `session.routine` participant depends on execution and Toolkit State
  participation, owns Routine definitions/records, and verifies its complete
  Toolkit namespace and pending inputs before final root deletion.
- Archive eligibility uses existing `agent_run_input_events`, not another Run
  classification or execution owner. An active Routine host must have only
  canonical Routine input and matching current started occurrences; unrelated or
  mixed ordinary inputs block archive. Valid pre-start input can be removed
  without preserving a provider call. A normal completed-Run idle boundary may
  retain only its actual remaining Routine obligations.
- Archive removes definitions/records, check/source authority, pending internal
  judgment and pre-start trigger state. Only allowed started snapshots and
  required internal continuation survive. Late completion does not recreate
  definitions/records. Restore does not recreate checking authority or silently
  resume future definitions.
- Preserved archived work retains the ordinary running/recovery target. Narrow
  claim, snapshot and recovery admission uses the archived canonical snapshots,
  actual Run or typed continuation, and existing owner generation. No separate
  Routine owner, heartbeat, scanner or retry is added. Completion and delivery
  remain inside the exact original root/Run authority.
- An archived completed Run with unfinished obligations admits only those
  Routine continuations. When every item is complete, the normal idle boundary
  is consumed with no continuation; Goal/other inputs cannot borrow the archive
  exception, and no idle owner is kept alive.
- Actual purge-service validation exposed the shared owner-fence ordering
  boundary: advancing generation before waiting would fence the very preserved
  work allowed to finish. Preparation now decides preservation before advancing
  execution ownership or sending Stop. It waits through both an active Run and a
  legitimate between-Run idle boundary using the existing generic purge retry.
  Once no preservable work remains, ordinary purge fencing and cleanup apply.
  Terminal failed/stopped hosts cannot settle their old attempts; explicit purge
  removes that residual state without synthesizing objective results.
- The actual service now dispatches Routine preparation, cleanup and verification
  and rechecks absence at finalization. Real database tests cover source-only and
  admitted cleanup, mixed-input rejection, archived completion, owner replacement,
  internal continuation, empty idle settlement, restore non-resurrection, purge
  waiting without fencing the current owner, and full root deletion.
- Latest root validation passed 627 tests in 50.94s, including Routine tools/
  repositories/services, lifecycle registry, ordinary Session snapshots/owner
  recovery, idle/Stop, Scheduler, Chat trees, common internal Memory lifecycle,
  purge, Agent/owner retirement and Worker Run regressions. Full backend ty and
  Ruff for all changed Python files passed. Three dependency deprecation warnings
  remain. Evidence: `/tmp/routine-lifecycle-integrated.log`. Earlier 576-test and
  focused 36-test runs are superseded where this matrix overlaps; totals are not
  additive.
- Next uncovered ordinary recovery integration: the existing explicit failed-run
  retry creates a new pending Run and copies original input associations/profile,
  but does not yet rebind incomplete Routine snapshots from the failed Run.
  Connect that existing transaction to exact incomplete-state rebinding, preserve
  original context/start time, and leave already completed occurrences untouched.
  Do not rejudge, recreate deleted definitions or introduce a Routine retry loop.
- Remaining Phase 3 work: that explicit retry association and tests, bundled
  release guidance, source-generated contracts, complete phase validation and
  authority/removal audit, stable-diff review from the assigned reviewer, commit
  and PR. Full product QA/read-only inspection remains Phase 4. No phase 3 PR,
  review request, merge, deployment or live provider call occurred.
  Design delta: None.

### Dependency CI Checkpoint

Phase 1 is fully green. Phase 2's backend, migration and E2E functionality passed,
but its existing Web duration gate failed on attempt 1 at unchanged SHA
`6f795908e`: 530.035981s versus base 427.577543s (+23.96%, 20% limit). The exact
Required (362) and Web (32) testcase multisets match across the two runs; observed
slowness is distributed across multiple Web surfaces. The cause remains
inconclusive, not an accepted product regression or a proven environmental fault.

Root preserved complete metadata/artifacts for baseline run `39132598555/1` and
candidate run `39134760932/1` before requesting a complete unchanged-SHA attempt 2.
The existing gate policy and test coverage are unchanged. Attempt 2 completed
successfully at the same SHA (run `39134760932`, attempt `2`). Its Web test-call
duration was 405s against the 427.6s baseline, within the unchanged gate. This
resolves the failed required check, not the unproven cause of attempt 1's slowness.
Candidate artifacts and the duration report are preserved separately from attempt
1. Phase 3 has not been submitted to CI yet.

### Final Integrated Validation and Review Checkpoint

- Explicit failed-run retry now composes incomplete started-occurrence rebinding
  with ordinary input/profile copying in one transaction. It preserves admitted
  context/start time, does not repeat completed work or notification, and rolls
  back fully when rebinding fails. The focused retry/chat/API suite passed 47
  tests.
- Added release-bundled Routine guidance through the root-only Toolkit's VFS skill
  projection. Skill packaging validation passed. Definition management, admitted
  context, independent result/delivery, continuation, Stop and archive boundaries
  are documented; no Scheduled Task or inspection UI contract is substituted.
- History reads typed Routine events and projects chat notifications as assistant
  content without ordinary usage. Internal judgment action state is retained in
  DB while public pending/live action snapshots, broadcasts, DTOs and composer
  schemas exclude it. Public OpenAPI has no RoutineJudgmentAction component.
- Regenerated public/admin OpenAPI and Python/TypeScript clients from source.
  Both Python client suites passed 16 tests. Forced TypeScript
  `turbo run typecheck lint format:check --force` completed 18 tasks with no cache
  reuse or failures.
- The first full backend run exposed two retention failures caused by committed
  fixture purge audit rows without Session FKs. Exact newly owned Session graph
  cleanup now includes its logical purge roots and their FK descendants.
  Production purge rules and test assertions were not weakened.
- Final root-owned backend validation: `ruff check .`, `ruff format --check .`
  and `ty check --error-on-warning` passed. `pytest -q --tb=short` passed
  13,214 tests, with 3 skips and 8 dependency/test-fixture warnings, in 321.89s.
  A subsequent focused Routine/repository/service/tool/Run/lifecycle/retention/
  fixture-cleanup run passed 139 tests with 3 warnings in 26.76s.
- Documentation catalog and diff whitespace validation passed. Source scans found
  no retired independent judgment lease/claim/heartbeat/discovery implementation
  or judgment JobRuntime registration. Scheduler performs source admission only;
  ordinary Run/FIFO owns judgment execution. No Phase 4 read API/UI is activated.
- The integrated implementation is ready for the single read-only review from
  `/root/routine-reviewer`. Commit, push and Phase 3 PR creation follow review
  resolution. No Phase 3 PR, merge, deployment, live provider call or production
  notification has occurred at this checkpoint. Design delta: None.

### Independent Review Corrections

- The assigned reviewer inspected the complete stable Phase 3 diff read-only
  and confirmed Design revision 2 / ADR-D2/D3/D4 alignment. Three grounded
  findings were returned; root implemented all corrections directly.
- P1: include known profile-resolution and Structured feature failures in the
  narrow judgment failure-settlement boundary. Failed observations preserve
  exact source input and action time, clear the queued action, and permit a fresh
  next-tick admission. Profile failure before model selection records unknown
  provider/model rather than inventing one. Cancellation, stale context,
  ownership/authorization errors and unrelated ValueError still propagate.
- P2: ordinary trigger/continuation content now contributes to the existing
  user-side context breakdown. Passive judgment content and usage remain
  excluded from normal usage, cost and turn markers.
- P2: bundled guidance now chooses Scheduled Task for mandatory per-occurrence
  output and Routine for conditional checking, including timed preferences.
  Approved hourly traffic-report versus anomaly-check examples and fixed
  30-minute tick/minimum-action limitations are included in projected guidance.
- Root regression evidence: initial correction focus passed 17 tests; expanded
  integrated Routine/context/VFS/lifecycle/retention tests passed 165 tests in
  26.69s; full backend passed 13,220 tests with 3 skips and 8 warnings in 318.85s.
  Whole-backend Ruff, format and ty passed. Skill packaging validation passed.
  Counts overlap and are not additive.
- The correction diff is ready for bounded confirmation from the same reviewer
  because judgment failure semantics and Requirements guidance are affected.
  No new product contract or material mechanism was added. Commit and Phase 3
  PR remain next; Phase 4 has not started. Design delta: None.
- Bounded same-reviewer confirmation subsequently closed all three findings with
  no remaining issue in the correction delta. The reviewer confirmed that the
  fixes remain within Design revision 2 and add no material mechanism. Root's
  integrated checks above remain the validation evidence; the reviewer did not
  rerun tests. The implementation is ready for hook commit, push and Phase 3 PR.
