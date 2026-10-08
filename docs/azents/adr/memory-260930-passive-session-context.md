---
title: "Passive Session Context Technical Decisions"
created: 2026-09-30
tags: [memory, conversation, architecture, security, engine]
document_role: primary
document_type: adr
snapshot_id: memory-260930
---

# Passive Session Context Technical Decisions

- Snapshot: `memory-260930`
- Document reference: `memory-260930/ADR`
- Mode: Collaborative.
- Decision owner: requester.
- Accepted material technical decisions: `memory-260930/ADR-D1`.
- Implementation and complete Design approval: not granted.

The requester confirmed [memory-260930/REQ](../requirements/memory-260930-passive-session-context.md) on 2026-09-30 KST. This ADR records accepted and unresolved technical decisions and the evidence supporting their discussion; a proposal is not accepted authority. Accepted entries are recorded before proceeding to their dependent mechanisms.

## Fixed Outcomes

These are briefings, not alternatives to reopen:

- Minimum six-hour source Session inactivity and no ongoing Run before extraction; asynchronous eligibility is not a completion deadline (`REQ-3`).
- Distinct Active and source-dependent Passive semantics (`REQ-1`, `REQ-4`, `REQ-5`).
- Current Agent, Workspace, Team, and associated-User boundaries; subagents cannot widen root authority (`REQ-2`).
- Source changes, archive, purge, and access loss exclude unusable Passive context; restore follows ordinary preparation (`REQ-6`).
- Snapshots at Session start and after compaction, with on-demand current lookup rather than automatic refresh every ordinary turn (`REQ-7`, `REQ-8`).
- Existing settings inspection and Memory enablement, without a second Passive control or per-answer attribution surface (`REQ-1`, `REQ-9`).
- Missing or failed context must not block ordinary conversation or publish known stale content (`REQ-10`).
- The existing project convention keeps Redis optional and non-authoritative. A fresh empty Redis instance cannot require restoration of old keys to recover correct behavior.

## Current System Evidence

Baseline inspected: `ea5b080db768ba6735d91f4419e9ef08723f0c9d`.

- [Memory spec](../spec/domain/memory.md), `engine/tools/memory.py`, and `rdb/models/memory.py` describe explicit Active entries and lexical lookup. The inspected source has no automatic Passive summary/consolidation implementation.
- `engine/tools/builtin.py`, especially `MemoryReadToolkit.get_dynamic_prompt` and `collect_memory_prompt`, collects the Active index dynamically. The requested boundary snapshot lifecycle needs an explicit replacement boundary; simply adding another dynamic prompt would not satisfy `REQ-7`.
- `repos/agent_execution/__init__.py` maintains `last_activity_at` monotonically for conversation and tool/action activity. `rdb/models/agent_session.py` holds product mode, associated User, status, Run state, and context-head state. These are reuse candidates, not yet a complete inactivity or content-revision contract.
- `repos/session_history/repository.py` constrains active root discovery by Agent, Workspace, and associated User and selects searchable semantic messages. Extraction must preserve these access semantics without treating unrestricted transcript/tool bodies as summary input.
- [Context compaction spec](../spec/flow/context-compaction.md) and `engine/context/compaction.py` concern current-Session continuity, not independent cross-Session evidence.
- `scheduler/service.py` claims code-owned tasks using durable Scheduler state. `run_once` awaits each `_execute_claimed`; `_execute_claimed` submits through JobRuntime and then awaits the handle. A long summary call inside that task can delay other tasks in that scheduler instance.
- `scheduler/registry.py` already supports bounded maintenance handlers with interval, deadline, and retry policies. A code-owned memory maintenance task would be distinct from user-created Scheduled Tasks.
- `job_runtime/local.py` supervises process-local tasks with bounded execution concurrency, deadlines, and cancellation. Its execution-key coalescing is process-local; it is not cross-process idempotency or durable restart recovery.
- `job_runtime/deps.py` currently selects LocalJobRuntime. Selecting the Temporal backend raises an unavailable-backend error; it is not a currently reusable execution backend.
- `job_runtime/registry.py` is the closed registration boundary for background handlers. Adding a handler is possible, but its authority, persistent ownership, workload bounds, and recovery still require this snapshot's decisions.

Code paths above are relative to `python/apps/azents/src/azents/`.

## Material Decision Map

Each lane is requester-owned. D1 is accepted; D2 is the current discussion, and D3-D6 remain pending. Split or refine an unresolved lane if further research exposes a distinct consequential choice; the map itself is not authority for a mechanism.

| Lane | State | Consequence to decide | Viable direction families | Related requirements |
| --- | --- | --- | --- | --- |
| D1 | Accepted | How eligible sources are discovered, extraction is dispatched, and normal discovery is scheduled | Five-minute bounded scanning that triggers target-Agent background jobs without awaiting summary completion | REQ-3, REQ-6, REQ-10 |
| D2 | Current | How Session-owned Passive projections persist and prove source freshness | Dedicated source revision with atomic publication versus canonical-evidence fingerprint with lifecycle fencing | REQ-2, REQ-4, REQ-5, REQ-6 |
| D3 | Pending | When integration/selection runs and how input/output are bounded | Background-prepared scope integration versus authorized on-demand integration from source summaries, with different selection costs | REQ-4, REQ-5, REQ-7, REQ-8 |
| D4 | Pending | Which model operation, credential path, and usage boundary own memory computation | Extend an existing eligible lightweight route versus an explicit memory-maintenance operation contract | REQ-3, REQ-4, REQ-10 |
| D5 | Pending | How boundary snapshots survive subsequent Runs and how current lookup is exposed | Durable context-generation snapshot versus reconstruction keyed to a stable context generation; extend current read tools versus dedicated Passive reads | REQ-1, REQ-2, REQ-7, REQ-8, REQ-9 |
| D6 | Pending | Failure retry, capacity controls, operational enablement, and rollout/recovery obligations | Bounded periodic reconciliation versus attempt-specific retry/admission controls; existing controls versus additional operational controls where justified | REQ-1, REQ-3, REQ-6, REQ-10 |

### Product question kept separate

The initial eligible historical window is not fixed by Requirements beyond excluding an all-old-Sessions sweep triggered by enablement. Before a rollout mechanism broadens the visible source population, obtain the product-scope choice and update Requirements. This does not block the decision-independent D1 comparison.

### Agent-owned details

Equivalent identifiers, module layout, helper boundaries, fixture naming, and local structures that introduce no new behavior, authority, state, API contract, or runtime mode belong to the implementation agent. Numerical operational controls are not automatically classified as local if they change an exposed configuration contract or promised recovery behavior.

## D1 — Eligible Source Discovery and Extraction Dispatch

**State:** Accepted at 2026-09-29T21:00:36.148000+00:00 as `memory-260930/ADR-D1`: Option A with a five-minute normal scan interval and target-Agent background-job dispatch. No other lane is accepted by this choice.

**Question:** Should eligibility be reconstructed through periodic bounded discovery, or should every relevant activity maintain durable due work for later dispatch, and what is the normal discovery interval?

### Option A — Periodic bounded discovery and separate background extraction

A code-owned Scheduler task periodically discovers a bounded number of eligible changed sources in the admitted history window and triggers a background job for each admitted target Agent through a separately registered JobRuntime handler. The scan does not wait for summary-model completion. The Agent background job processes eligible Session-specific summaries, rechecking source authority and inactivity before computation and publication. Agent-level scheduling does not merge private and Team source scopes or make summaries independent of their source Sessions.

Consequences and obligations:

- Eligibility can be reconstructed from persisted source/progress state; correctness is not tied to a process-local six-hour timer.
- Ordinary activity writers need not maintain a dedicated scheduling entry for every update. Source freshness/invalidation still needs D2 work.
- Detection is delayed by polling and admitted capacity beyond the fixed six-hour minimum. Requirements do not promise an exact six-hour completion.
- Candidate queries need an indexed, bounded history/progress strategy; a repeated unbounded transcript or tenant-wide scan is not acceptable.
- Separate dispatch prevents the Scheduler from awaiting the summary model. It does not automatically provide resource isolation: JobRuntime capacity remains shared and needs D6 bounds.
- Process restart, duplicate discovery, multiple processes, and expired attempts require durable ownership/fencing or safe reconciliation. LocalJobRuntime coalescing alone is insufficient. D2 and D6 define the storage and recovery contract before implementation.

### Option B — Activity-maintained durable due work

Relevant source activity transactionally updates a durable due-work projection to its new eligibility time. A bounded due-work dispatcher finds expired entries and executes Session-specific extraction through background handlers, rechecking current authority and inactivity before computation and publication.

Consequences and obligations:

- Due lookup can avoid repeatedly searching the full admitted source population, and scheduling intent is explicit.
- Every qualifying activity, source mutation, restore, enablement transition, and applicable lifecycle path must maintain or reconcile the projection correctly.
- Activity admission acquires additional persistence responsibilities, indexes, and concurrency boundaries. Missing writers cannot silently lose summaries.
- A rebuild/reconciliation contract is still needed; a queue entry or elapsed timer is not authority to read a changed or denied source.
- Durable due work does not bypass the same six-hour threshold, model latency, capacity, idempotency, or restart requirements.

### Accepted rationale

The requester selected **Option A**, explicitly framing the scan as triggering target-Agent background tasks. The existing code-owned Scheduler, source activity projection, and closed JobRuntime handler registry provide useful integration points with less scheduling responsibility added to the many conversation writers. The implementation must keep discovery separate from slow extraction, bound dispatched work, and persist/reconstruct progress safely. The rationale is repository-grounded engineering judgment, not evidence that cost, quality, or scale has already been validated. Activity-maintained due work was considered but not selected.

### Accepted normal discovery cadence

Use a **five-minute code-owned discovery interval** with Option A. This interval belongs to D1 rather than being deferred to the general operations lane.

- The six-hour inactivity threshold determines source eligibility. The five-minute interval determines when eligible candidates are searched for; it is not a six-hour batch interval or a recurring summary of unchanged sources.
- Preserve the existing Scheduler's completion-based interval semantics: after one successful bounded discovery/dispatch round finishes, its next due time is that finish time plus five minutes. This does not mean fixed wall-clock boundaries or parallel overlapping discovery rounds.
- A healthy short discovery round with no scheduling or capacity backlog normally adds up to approximately one interval of detection delay after eligibility, plus discovery duration and the existing Scheduler polling delay. Other Scheduler tasks, overload, restart, failures, and extraction/model work can add more delay. No hard five-minute discovery or summary-completion guarantee is created.
- This cadence schedules the short discovery/dispatch round, not the completion of the separate summary-model attempt. Dispatch remains bounded and does not await the extraction model.
- Existing Session auto-archive, archived-Session purge, and file-lifecycle cleanup task definitions use five-minute intervals in `scheduler/registry.py`. This supports integration consistency, not proof of optimal memory cost or throughput.
- A one-minute interval reduces healthy detection latency but can schedule roughly five times as many discovery rounds when round duration is negligible. A fifteen-minute interval reduces query frequency but increases the interval-driven delay. Five minutes is the recommended initial engineering trade-off against the already fixed six-hour wait, not a measured optimum or a copied Codex scheduler setting.
- Changing the normal interval requires a new recorded technical decision; this choice introduces no new user-facing Passive control. Failure retry/backoff and resource limits remain explicit D6 work.

### Not decided by D1

- Specific table or claim-token design, source content version, aggregate storage, or index definitions.
- Changes to the Scheduler's existing loop polling, per-Agent fairness, concurrency limits, timeout, failure backoff constants, or new admin settings.
- Initial historical window or broad backfill authorization.
- Model identity, candidate fallback policy, credential handling, or usage accounting.
- Overview budget, integration timing, snapshot persistence, or tool/API names.

### Verification obligations

- No extraction before the six-hour boundary or while a Run is ongoing; new activity postpones eligibility.
- Source mutation or permission loss between discovery, claim, model call, and publication cannot expose stale or denied output.
- Restart and duplicate dispatch cannot classify lost work as successful; recovery requires no retained Redis keys.
- Long model calls do not force the discovery task to wait or block ordinary conversation.
- Successful discovery rounds preserve the selected completion-based interval without refreshing unchanged source summaries or relaxing the six-hour eligibility gate.
- Capacity saturation remains bounded and cannot expand the caller's admitted source population.

## Accepted Decision Log

### memory-260930/ADR-D1 — Accepted at 2026-09-29T21:00:36.148000+00:00

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-3`, `REQ-6`, and `REQ-10`, with the unchanged scope and lifecycle constraints in `REQ-1` and `REQ-2`.
- **Choice:** Option A; a short bounded Scheduler scan triggers background tasks for the target Agents through JobRuntime.
- **Cadence:** after a successful scan/dispatch round finishes, the next normal scan is due five minutes later. Actual admission may be delayed by the existing Scheduler loop, capacity, failures, and recovery; this is not a hard wall-clock execution or completion guarantee.
- **Execution boundary:** the scan does not await the summary LLM. Eligible Session summaries are processed inside the target Agent's background task, not as user-created Scheduled Tasks or by waking an ordinary foreground conversation.
- **Preserved conditions:** minimum six-hour source inactivity, no ongoing Run, current Memory enablement and source authorization, and source-specific freshness checks.
- **Rejected option:** maintaining scheduling due-work entries on every relevant activity solely to determine normal extraction eligibility.
- **Deferred:** persistent claim/recovery structure, per-Agent coalescing and fairness, capacity and retry constants, models, integration timing, snapshots, APIs, and initial historical window. This choice does not grant implementation or complete Design approval.

The full Design remains deferred until the material decision map is resolved.

## D2 — Session-Owned Passive Persistence and Source Freshness

**State:** Proposed; awaiting the requester's choice. D1 does not authorize either persistence mechanism.

**Question:** Should Session-owned Passive projections use a dedicated source revision or a canonical-evidence fingerprint to prove that their source has not changed?

### Evidence and required boundary

- `rdb/models/memory.py` stores independently managed Active records keyed by Agent, scope, and name. It has no source Session reference or Passive lifecycle discriminator.
- `rdb/models/event.py` stores source events with a mutable `reverted` flag. `repos/message/__init__.py` can mark a range reverted and recompute the last user-input timestamp without appending a new semantic message.
- `repos/agent_session/__init__.py` archives/restores Session trees and clears archive metadata on restore. Current active status or identical conversation bytes alone cannot establish that an old summary passed through the required restore preparation.
- `last_activity_at` is useful for inactivity, but is not a content-version contract. Generic `updated_at` also reflects unrelated Session updates. Neither is sufficient alone as summary freshness proof.
- The requirements already require source-dependent summaries, current authorization, exclusion of stale results, restore preparation, and independent Active lifetime. These outcomes are fixed; the change-detection and persistence mechanisms remain the decision.

### Proposed common persistence contract

Both options propose dedicated PostgreSQL Passive projection records owned by their source Sessions, separate from existing Active Memory rows.

- Keep one current source-summary projection per admitted source Session, including its source identity, processed source stamp, evidence-aware summary items, and a result that distinguishes usable summary, no useful summary, and unsuccessful/unprepared work.
- The source Session and its original events remain authoritative evidence; a projection is not an independent instruction or new shared Active Memory.
- Read boundaries join/recheck current source Agent, Workspace, root Team/User ownership, lifecycle, and Memory enablement. Copied scope labels alone cannot authorize use.
- Store enough source dependencies for later integrations to reject or reevaluate invalid contributors. Whether integrated overviews are separately persisted, when they are computed, and how they are selected remains D3/D5 work.
- Do not expose Passive rows to Active upsert/edit/delete semantics. Existing Active rows and tools remain independently managed.
- Permanent source deletion makes its dedicated projection unreusable; archive denies use immediately without waiting for physical deletion.
- Projection names, exact columns, indexes, and typed item layout remain Design details within the accepted contract. Background attempt leases, retries, and capacity are not decided by these summary-result states.

This common contract is itself proposed as part of D2, not silently derived authority.

### Option A — Dedicated source revision and conditional publication

Maintain a monotonically advancing source revision in PostgreSQL for each admitted source. Advance it transactionally with changes that affect the summary's evidence or lifecycle: relevant conversation/outcome additions, reverted evidence, and archive/restore invalidation. Ordinary heartbeat, navigation, job bookkeeping, and summary publication do not advance that evidence revision solely because they occurred.

An extraction attempt captures revision N and its source boundary before calling the model. It publishes only through a database operation that rechecks revision N and current source eligibility/authority atomically with storing the result. If revision differs, the result cannot become current. Reads accept a stored summary only when its processed revision matches the current valid source revision.

Consequences:

- Eligibility and ordinary read freshness checks can compare a small stamp without rebuilding or hashing every conversation.
- Mutations acquire a new atomic revision-maintenance responsibility. All relevant append, revert, archive, restore, and applicable evidence-update paths must be covered; a missed path can violate freshness.
- Existing rows need an initialization/migration boundary, while the permitted history window remains a separate product/rollout choice.
- Archive/restore invalidates an old revision even when restored conversation text is identical.
- The revision is not an execution lease, duplicate-attempt guard, permission grant, or replacement for the six-hour inactivity check.

### Option B — Canonical-evidence fingerprint and lifecycle fencing

Derive a deterministic fingerprint from the canonical evidence boundary and content used to establish the source projection. Capture it before extraction and recompute/check it for conditional publication and current reads. Include a reliable lifecycle fence so archive/restore cannot make an old projection usable merely because the text is identical.

Consequences:

- Evidence changes can be detected without introducing a dedicated content-counter update on every content writer, provided the canonical projection covers all relevant mutations.
- Freshness requires additional evidence reads/hash computation, or another maintained fingerprint projection; a cached digest alone is not proof of current source state.
- A last event ID, timestamp, or hash of only an arbitrary latest chunk is not enough to detect all reverted/changed evidence.
- Identical bytes after restore still require separate lifecycle fencing and preparation; content hashing does not replace source authorization.
- Canonicalization, evidence boundary coverage, large-history cost, and atomic publication races require explicit Design and tests.

### Recommendation

Recommend **Option A with the dedicated Passive projection contract**, pending requester approval. It gives the accepted five-minute scanner and current lookup a compact persisted freshness boundary and makes stale publication easy to reject. The trade-off is deliberate coverage of source-mutation transactions. This records evidence invalidation, not the activity-maintained scheduling due work rejected in D1.

### Not accepted by this proposal

- No D2 mechanism, new table, revision field, or publication contract is accepted yet.
- Agent-job claims/coalescing, attempt fencing, retry/backoff and capacity remain unresolved; two attempts on the same source revision are not deduplicated by the revision alone.
- Integrated-overview persistence, selected context budgets, model routing, input rendering, tool/API shapes, and context-generation snapshots are not selected.
- The earlier observed Scheduler stale-round-time/deadline risk is not fixed by D1 or D2. Its operational treatment remains explicit feasibility and D6 work, not an implicit general Scheduler rewrite.

### Verification obligations for the eventual choice

- New evidence or reverted evidence invalidates the old processed stamp; unrelated bookkeeping does not repeatedly dirty summaries.
- A source mutation during model computation cannot publish a stale result, including races at the final database operation.
- Archive denies use immediately; restoring identical content does not bypass ordinary preparation.
- Team/User permission boundaries survive an Agent-wide background job and later summary/integration reads.
- No useful summary is distinguished from failed/unprepared work without repeated extraction of an unchanged successfully processed source.
- Source deletion cannot erase independent Active records or leave usable orphan Passive content.

## Current Framing After Requirements Reconfirmation

The requester reconfirmed the relaxed `memory-260930/REQ` on **2026-09-30 at
06:35:33 KST**. This section is the current framing for subsequent design work.
Earlier freshness-related Fixed Outcomes, discussion-map entries, and D2
alternatives record the original Requirements baseline; they are not current
authority. The accepted D1 entry remains unchanged as decision history.

### Requirements-derived clarification of D1

The selected discovery and dispatch architecture is unchanged: a bounded scan
triggers target-Agent background jobs, the scan does not await summary-model
completion, and successful discovery rounds retain the completion-based
five-minute interval.

The revised Requirements determine these dependent boundaries:

- The six-hour inactivity and no-ongoing-Run conditions apply when beginning
  extraction. Later content changes may coexist with publication of historical
  context (`REQ-3`, `REQ-6`).
- Extraction and publication still check current source access, active status,
  scope, and Memory enablement. Archive, purge, and permission loss deny new use
  (`REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`).
- A retained authorized summary remains usable after content changes and during
  failed or pending refreshes. Restore may permit use of the retained summary
  without mandatory re-extraction (`REQ-6`, `REQ-10`).
- Summary source references and preparation time support historical
  interpretation and optional inspection (`REQ-4`, `REQ-5`, `REQ-8`).

This is a Requirements-derived clarification, not a newly accepted technical
choice or a change to D1's scheduling architecture. Earlier content-mutation
invalidation and exact-freshness verification obligations no longer apply.
Authorization checks remain independent of content freshness.

### D2 — Freshness-proof proposal withdrawn

**State:** Closed without acceptance. The dedicated source-revision and
canonical-fingerprint alternatives were never selected. The relaxed Requirements
remove the exact-freshness outcome that made that comparison necessary.

Source-dependent historical summaries, independent Active lifetime, current
access checks, and retention of available context during failed refresh are fixed
outcomes rather than new questions. Equivalent record layout and local update
structures belong to Design and implementation. A persistence choice that
changes durability, recovery, lifetime, or source-removal behavior remains
material and must be disclosed in D5/D6 rather than silently classified as a
table-layout detail. No new Passive table, source revision, fingerprint, model,
or attempt-fencing mechanism is accepted by closing this proposal.

### Current material decision map

All remaining material choices are requester-owned.

| Lane | State | Current consequence to decide | Related requirements |
| --- | --- | --- | --- |
| D1 | Accepted | Five-minute bounded discovery and target-Agent background extraction | REQ-3, REQ-6, REQ-10 |
| D2 | Closed, unaccepted | Exact-freshness comparison removed by confirmed Requirements | REQ-4, REQ-5, REQ-6, REQ-8, REQ-10 |
| D3 | Current, proposed | Persist background-integrated overviews or assemble permitted Session summaries at read boundaries | REQ-4, REQ-5, REQ-7, REQ-8 |
| D4 | Pending | Model operation, credential ownership, and usage accounting for background summary work | REQ-3, REQ-4, REQ-10 |
| D5 | Pending | Snapshot persistence across Runs and read-tool/settings contracts | REQ-1, REQ-2, REQ-7, REQ-8, REQ-9 |
| D6 | Pending | Summary/progress durability, bounded retries and capacity, restart recovery, and rollout | REQ-1, REQ-3, REQ-6, REQ-10 |

The initial admitted history window remains a separate product-scope question.
It is not decided by the relaxed Requirements or by the following D3 proposal.

### D3 — Cross-Session Context Assembly

**State:** Proposed; awaiting the requester. Neither option is accepted.

**Question:** Should background work prepare and retain an integrated overview,
or should reads select and assemble the available Session summaries directly?

Both options use D1's background preparation of source-specific summaries.
Both keep Active separate, use bounded context, check current access at new read
boundaries, and treat summaries as historical hints rather than latest facts.

#### Option A — Background-integrated overviews

After preparing Session summaries, background work also performs a bounded
cross-Session model operation and persists an integrated overview with its
contributing Session references. Shared Team context and personal context retain
their authorization boundaries; personal information cannot enter a shared
Team overview.

- Duplicate context and visible conflicts can be condensed before consumer
  reads, although summary quality remains best effort.
- This adds model work, persisted aggregate state, and reconciliation after
  source-summary updates. It can reduce repeated assembly at consumer reads.
- A new read cannot reuse integrated content whose contributors are now denied.
  Whole-overview exclusion is allowed when removing a contributor cannot be
  done safely; no exhaustive claim-level dependency graph is implied.
- Missing or failed integration contributes no new overview and does not block
  conversation. A retained overview may remain usable only when its contributing
  sources are still permitted.

#### Option B — Read-boundary assembly of Session summaries

Persist source-specific summaries without a separate model-generated aggregate.
At Session start, post-compaction reconstruction, or an explicit lookup, select a
bounded set of currently permitted summaries and format them with Session-level
source references. The ordinary conversation model interprets that supplied
historical context; assembly adds no separate integration-model call.

- This avoids a second aggregate persistence/reconciliation lifecycle and an
  additional integration-model operation.
- Reads select from source summaries with current authorization checks, so
  unavailable contributors can be omitted before context assembly.
- Cross-Session deduplication and conflict interpretation are less deeply
  prepared; bounded selection may omit otherwise useful history.
- Selection at Session start uses broadly useful context, not an assumed future
  request. Post-compaction selection can use the known conversation topics.
- Assembly follows context boundaries and explicit lookup rather than
  automatically refreshing ordinary turns.

#### Recommendation and remaining boundaries

Recommend **Option B**, pending the requester, for the confirmed loose-memory
direction. It keeps source-linked summaries useful while avoiding another
model-generated aggregate and its removal/reconciliation obligations. This is
an architecture trade-off, not a measured quality, latency, or cost result.

This proposal does not choose extraction input windows, full versus incremental
refresh, model routing, database layout, ranking algorithms or numeric budgets,
snapshot durability, tool/API names, retry constants, or the initial history
window. Equivalent bounded selection details may be agent-owned; any new
material mechanism or user-visible scope still requires the applicable authority.

## Accepted Decision Log — Read-Boundary Assembly

### memory-260930/ADR-D3 — Accepted on 2026-09-30 at 06:47:16 KST

- **Owner:** requester.
- **Authority:** the reconfirmed `memory-260930/REQ-4`, `REQ-5`, `REQ-7`,
  and `REQ-8`, with access and lifecycle boundaries in `REQ-1`, `REQ-2`,
  and `REQ-6`.
- **Choice:** Option B. Background work prepares source-specific Session
  summaries. Session start, post-compaction reconstruction, and explicit lookup
  select and format a bounded set of currently permitted summaries.
- **Model boundary:** assembly has no separate integration-model call. The
  ordinary conversation model interprets the selected historical context.
- **Persistence boundary:** no separately persisted model-generated
  cross-Session aggregate is introduced by this choice. Source-summary and
  context-snapshot storage contracts remain for Design and the remaining
  material lanes.
- **Rationale:** the requester explicitly selected B. It fits loose historical
  memory and avoids an additional aggregate generation, persistence, and
  source-removal lifecycle. Reduced duplication and complete conflict
  reconciliation are not guaranteed.
- **Preserved conditions:** source references, bounded context, current
  authorization and Memory enablement, Active/Passive separation, no automatic
  ordinary-turn refresh, and permission to retain stale historical summaries.
- **Rejected option:** a second background model operation that prepares and
  persists integrated overviews.
- **Deferred:** ranking and numeric budgets, extraction input windows and
  refresh method, summary-model routing and credentials, snapshot persistence,
  tool/API contracts, retry/recovery, and initial history admission.
- **Approval boundary:** this choice accepts D3 only; it does not approve the
  complete Design or authorize implementation.

### Decision-map transition after D3 acceptance

Accepted material decisions are now `memory-260930/ADR-D1` and
`memory-260930/ADR-D3`. D2 remains withdrawn without acceptance. D4 is the next
current lane; D5 and D6 and the separate initial-history product question remain
pending. Earlier proposed-state labels for D3 record its pre-acceptance history.

## D4 — Model Route for Background Session Summaries

**State:** Proposed; awaiting the requester. D1 and D3 do not choose the summary
model route or authorize a new user-facing model control.

**Question:** Should source-summary jobs use the Agent's existing Lightweight
label or its existing Main label?

### Current evidence and reusable boundaries

- `spec/domain/agent.md` and `core/agent.py` define Agent-owned selectable
  candidate chains with both `main_model_label` and `lightweight_model_label`.
  The labels can point to different chains or the same physical model; choosing
  the semantic route still determines which future Agent setting governs
  summary work.
- `repos/session_title/__init__.py::load_generation_snapshot` selects and
  freezes the Lightweight chain for a separate background title operation.
  This provides a preparation pattern, not a reusable Passive-summary service.
- `core/model_operation.py::ModelOperationKind` currently contains only
  foreground, compaction, and title. Summary work needs its own truthful
  operation attribution rather than pretending to be a foreground Run or title.
- `services/model_candidate_selection.py` treats non-foreground operations as
  background callers: they consult candidate health and skip candidates requiring
  a foreground probe. They do not consume a Session's foreground reservation.
- `engine/run/resolve.py::resolve_model_candidate_runtime` loads the selected
  integration, checks Workspace ownership and enablement, validates settings,
  and refreshes supported OAuth credentials before building provider arguments.
- `services/session_title.py` dispatches through shared provider-specific
  Responses helpers and the model-stream watchdog. Its title prompt, small
  output contract, and title-generation ownership checks are title-specific and
  cannot simply be reused as the memory operation contract.
- `engine/events/openai_responses.py::call_openai_responses_text` normalizes the
  response internally but returns only assistant text. The inspected title
  service does not persist a memory-specific usage ledger. Reusing its text
  helper alone is not evidence that background memory tokens/cost will appear
  in ordinary conversation turn markers.

Code paths above are relative to `python/apps/azents/src/azents/` except Specs.

### Common proposed execution boundary

For either model route, use the selected Agent-owned chain and its configured
Workspace integration through the existing credential, provider-call, watchdog,
and background candidate-selection infrastructure. Keep the operation text-only,
without enabling conversation tools or waking a foreground Run.

Operational attribution distinguishes background memory work from foreground
conversation and identifies the Agent, source Session, chosen label, and physical
route. Provider-reported usage may be captured as background operation metadata
when available; no exact-cost guarantee, new billing ledger, or usage UI is
introduced by this proposal. A durable usage-accounting contract, if later
required, must be disclosed separately.

Model preparation does not grant source access. Source scope, active status, and
Memory enablement remain independently checked. A failed model operation leaves
the previous permitted summary available under the relaxed Requirements; retry
limits, recovery, and capacity remain D6.

### Option A — Existing Lightweight label

- Summary work follows the Agent's existing auxiliary-model choice, as title
  generation and compaction already do.
- No separate memory-model setting or new provider credential is needed.
- Quality, context capacity, and actual provider cost depend on the configured
  candidates; the word Lightweight is not a guarantee of low price or adequate
  summary quality.
- Exhausting that selected chain leaves the refresh unsuccessful rather than
  silently crossing to the Main chain.

### Option B — Existing Main label

- Summary work follows the Agent's default main-model choice, while still
  executing as an independent background operation.
- No separate memory-model setting or new provider credential is needed.
- This may align summary quality with the Agent's default conversation model,
  but the actual cost/capacity trade-off is configuration-dependent.
- This route is the Agent Main default, not an arbitrary source Session's last
  prompt-selected model or a foreground-reservation owner.

### Recommendation and approval boundary

Recommend **Option A**, pending the requester. It makes passive summarization
another auxiliary workload governed by the already existing Lightweight choice,
with no extra memory setting. This is an ownership/configuration recommendation,
not a measured claim about model quality or cost.

Neither route, a new operation kind, or the common proposed execution boundary is
accepted yet. Provider compatibility and adequate input budgets must be validated
for the eventual summary renderer. Concrete models, extraction windows, refresh
method, token budgets, attempt persistence, retry constants, and initial admitted
history remain undecided. No implementation is authorized.

## Accepted Decision Log — Background Summary Model Route

### memory-260930/ADR-D4 — Accepted at 2026-09-29T22:00:57.829000+00:00

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-3`, `REQ-4`, and `REQ-10`, with
  access and enablement boundaries in `REQ-1`, `REQ-2`, and `REQ-6`.
- **Choice:** Option A. Source-summary jobs use the Agent's existing
  Lightweight semantic label and configured candidate chain.
- **Credential boundary:** reuse the selected Workspace-owned integration
  through existing credential validation and supported OAuth refresh; no new
  credential source or memory-model setting is introduced.
- **Execution boundary:** a separate, truthfully attributed background memory
  operation uses the existing provider-call, watchdog, and background candidate
  infrastructure. It does not enable conversation tools, wake a foreground Run,
  or consume a foreground probe/reservation.
- **Failure boundary:** the selected Lightweight chain may use its configured
  candidates under the existing background rules; exhausting it does not
  silently switch to Main. A failed refresh leaves the previous authorized
  summary usable.
- **Usage boundary:** distinguish memory work from conversation work. Capture
  provider-reported usage metadata when available without promising exact costs
  or adding a billing ledger or usage UI. Text-helper reuse alone is not usage
  accounting.
- **Rationale:** the requester confirmed the recommended auxiliary-model
  ownership. Actual price, capacity, and quality depend on Agent configuration
  and remain subjects of validation rather than promises.
- **Rejected option:** independently using the Agent Main default for summary
  work.
- **Deferred:** concrete models, extraction windows, refresh method, token
  budgets, operation-state persistence, retries/capacity, and initial history
  admission. This decision does not select a new usage-accounting store.
- **Approval boundary:** D4 is accepted; implementation and complete Design
  approval remain ungranted.

### Decision-map transition after D4 acceptance

Accepted material decisions are `memory-260930/ADR-D1`,
`memory-260930/ADR-D3`, and `memory-260930/ADR-D4`. D2 remains withdrawn.
D5 is current; D6 and the separate initial-history product question are pending.
Earlier proposed-state labels for D4 record its pre-acceptance history.

## D5 — Snapshot Continuity and On-Demand Read Contract

**State:** Current. Snapshot timing and reuse are fixed by Requirements; the
on-demand read-interface alternatives below remain proposed.

### Current evidence

- `spec/domain/memory.md` and `engine/tools/builtin.py` describe a dynamic Active
  index prompt. `MemoryReadToolkit.get_dynamic_prompt` currently calls
  `collect_memory_prompt` to query available Active summaries each turn.
  That implementation is not the requested boundary-only memory selection.
- `spec/domain/toolkit.md`, `rdb/models/toolkit_state.py`, and
  `repos/toolkit_state/store.py` provide durable, typed, Session-bound state with
  whole-state replacement and existing optimistic concurrency.
- `spec/flow/context-compaction.md` defines the successful compaction boundary:
  it atomically appends marker/summary events and advances the Session's durable
  model-input head. It resets only the Tool Search working set. Other Toolkit
  State is not automatically discarded.
- `engine/tools/memory.py` currently searches and reads independently saved
  Active rows by their existing scope/name identities.
- `engine/tools/session_history.py` provides separate authorized discovery,
  transcript paging, and selected tool-result reads. Those tools access original
  history, not a prepared Passive-summary store.

Code paths above are relative to `python/apps/azents/src/azents/` except Specs.

### Fixed and derived snapshot framing

`REQ-7` and accepted D3 already determine selection at Session start and after
successful compaction, not on each ordinary subsequent turn. Preserving that
boundary selection across subsequent Runs requires retained Session-owned
context state, not repeatedly dereferencing changing source summaries.

The existing durable Toolkit State is a feasible reuse boundary for bounded
snapshot content, its source Session references, and the context boundary to
which it belongs. Equivalent record layout and namespace details are
agent-owned; no new user setting, independent archive, source-revision counter,
or immutable source-version graph follows from this framing.

- Retained snapshot content is historical and may lag behind source summaries.
  An explicit lookup reads currently available stored memories without replacing
  the injected snapshot.
- New model-context use still checks current scope, source status, access, and
  Memory enablement. Filtering a denied contributor is not a content-freshness
  refresh and never grants copied Passive text an independent lifetime.
- An empty selection remains a valid boundary result. Suitable memory arriving
  later does not itself create ordinary-turn automatic reselection.
- Successful compaction permits a new selection; failed or skipped compaction
  does not create that boundary.
- The snapshot remains bounded. Source-summary refresh can replace available
  historical context without forcing previously selected content to update.

This is a Requirements-derived implementation framing, not a reopened product
question or approval of a new persistence/recovery policy. Missing/corrupt state
and operational recovery belong to D6 and feasibility validation; they must not
silently introduce an unapproved ordinary-turn refresh mode.

### On-demand lookup question

Should one memory lookup discover both saved Active and prepared Passive context,
or should Passive summary lookup be a distinct model-facing read flow?

Both alternatives stay inside the one Memory capability and enablement control.
They recheck current root scope and source access, permit stale historical
summaries, and preserve original-history inspection as an optional separate
capability. Passive has no independent save/edit/delete operation.

#### Option A — Unified Active/Passive memory discovery

Provide a common memory lookup that can return bounded, clearly distinguished
Active entries and Passive Session summaries for the same request. Follow-up
reads use the appropriate entry identity: saved Active scope/name versus
source-linked historical context. A source Session is not invented as an
editable Active name.

- The Agent need not choose the memory kind before discovering relevant context.
- Result kind, source clues, and historical preparation time prevent a Passive
  result from being rendered as an independently saved instruction.
- The read contract needs heterogeneous results and explicit identity handling;
  exact tool names, argument layout, and ranking are Design work.
- Existing Active save/update/delete meaning and original-history access remain.

#### Option B — Separate Passive summary discovery/read

Keep the Active read family dedicated to saved entries and add a separate
source-summary lookup flow under the existing Memory capability.

- Existing Active read identities and result shapes remain separate.
- Passive reads can use Session-centric identities directly.
- The Agent must choose or consult two read flows when it is unclear whether a
  useful detail is saved Active knowledge or historical Passive context.
- Additional Passive lookup remains distinct from original transcript paging;
  it does not turn an original-history tool into summary evidence.

### Recommendation and remaining boundaries

Recommend **Option A**, pending the requester, for one discoverable memory
capability with clear Active/Passive labels. This selects a read-interface
family, not automatic promotion, source verification on every use, or per-answer
attribution UI.

No D5 read-interface option has been accepted. Settings inventory behavior is
already fixed by `REQ-9`; equivalent routing/layout details are agent-owned.
Summary/progress durability, failed-state recovery, bounded retry/capacity, and
rollout remain D6. Initial admitted history remains a separate product question.
Implementation and complete Design approval remain ungranted.

## Accepted Decision Log — Unified Memory Discovery

### memory-260930/ADR-D5 — Accepted at 2026-09-29T22:14:12.476000+00:00

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-8`, with kind separation in `REQ-1`,
  source dependencies in `REQ-4` and `REQ-5`, snapshot boundaries in `REQ-7`,
  and privacy/lifecycle requirements in `REQ-2` and `REQ-6`.
- **Choice:** Option A. One on-demand discovery flow can find independently
  saved entries and source-dependent historical Session summaries for the same
  request.
- **Result boundary:** distinguish the kinds and use kind-appropriate identities
  and source clues. A historical Session summary is not an editable saved entry
  or a substitute for original history.
- **Preserved behavior:** saved-entry write/update/delete semantics,
  source-dependent summary lifetime, optional original-history inspection,
  permitted stale context, one Memory enablement control, and boundary-only
  automatic snapshot selection.
- **Naming condition:** the requester explicitly rejected Active/Passive as
  final names. They remain historical draft shorthand in this ADR, not accepted
  product/model-facing labels. The source-dependent kind must evoke earlier
  conversations and work; canonical replacement terms are not selected.
- **Rationale:** the requester selected common discovery while requesting
  names that describe the meaning of the memories rather than their production
  mechanism.
- **Rejected option:** a separate historical-summary discovery flow requiring
  the Agent to choose the memory kind before lookup.
- **Deferred:** final terminology, exact tool names and argument/result schemas,
  ranking, operational recovery, and initial historical admission.
- **Approval boundary:** this accepts the D5 discovery choice, not a proposed
  name, complete Design, or implementation.

### Current decision state after D5 acceptance

Accepted technical decisions are `memory-260930/ADR-D1`,
`memory-260930/ADR-D3`, `memory-260930/ADR-D4`, and
`memory-260930/ADR-D5`. D2 remains withdrawn. Terminology is the current
requester-owned product question; D6 and initial historical admission remain
pending. Selected terminology will be applied in Requirements before dependent
ADR/Design terminology is reconciled, preserving accepted decision history.

## Confirmed Product Terminology

The requester confirmed **Saved Memory / Historical Memory** at
2026-09-29T22:39:32.398000+00:00. Requirements were updated first.

- **Saved Memory** names independently managed saved knowledge.
- **Historical Memory** names source-dependent context from earlier Session
  conversations and work.
- Earlier accepted decisions and proposals used Active/Passive as draft terms.
  Those historical records are preserved; the current terms above govern new
  Design and product/model-facing terminology.
- This is a confirmed naming change, not a new source of authority, permission,
  retention behavior, model route, or automatic promotion.
- The snapshot basename and typed references remain stable. Existing code and
  Living Specs remain current-implementation evidence until implementation
  changes them through the approved delivery workflow.

Terminology is resolved. D1, D3, D4, and D5 remain accepted, D2 withdrawn, and
D6 is the current technical lane. Initial historical admission remains a
requester-owned product-scope question. No implementation is authorized.

## D6 — Historical Memory Progress, Recovery, and Work Admission

**State:** Proposed; awaiting the requester. Neither execution-coordination
option below is accepted.

**Question:** Should persisted summary/progress records and periodic
reconciliation be sufficient, accepting occasional duplicate computation, or
should memory work also own a durable distributed attempt/lease ledger?

### Current evidence and common obligations

- `spec/flow/periodic-execution.md` and `scheduler/service.py` distinguish
  persisted Scheduler task state from handler execution. The Scheduler's scan
  claim is not ownership of all separately dispatched Agent summary jobs.
- `job_runtime/local.py` coalesces an active execution key in a process-local
  task map. Its semaphore and absolute deadline bound execution, including
  waiting for admission; it does not persist or resume an unfinished model call
  across process restart.
- `job_runtime/deps.py` currently supplies LocalJobRuntime. Temporal is a
  recognized but unavailable backend, not an existing durable workflow service
  to switch on for this feature.
- Scheduler retry policies already include next-interval and bounded
  exponential-delay calculation. Separate summary-job failures are not
  automatically represented by successful completion of a discovery scan.
- `spec/domain/toolkit.md` supplies durable Session-bound side state for context
  snapshots. Its persistence does not make the separate model job durable.
- The previously observed Scheduler round-start time reuse remains a timing
  feasibility concern for claims/deadlines after slow preceding tasks. The
  Design must verify actual-time admission and recovery; this proposal does
  not silently authorize a general Scheduler rewrite.

Code paths above are relative to `python/apps/azents/src/azents/` except Specs.

Both options propose:

- Persist the latest completed source-specific Historical Memory result and
  enough progress to distinguish successful preparation, including an explicit
  no-useful-context result, from unsuccessful work. Scheduling progress describes
  what was processed; it is not a source-freshness proof or a read-usability gate.
- Keep a previously available result during failed or pending refresh. A
  successful new result replaces the available source result; independent Saved
  Memory is untouched.
- Use persisted retry timing and failure progress to delay repeated failed work
  without keeping a permanently stuck running state. Recovery rechecks ordinary
  eligibility, current authorization, and enablement.
- Bound scan size, dispatched Agents, Session work per Agent batch, memory
  admission, and attempt duration. Memory admission must leave shared Runtime
  capacity for discovery and other jobs; the general Runtime semaphore alone is
  not a complete memory-work budget.
- Defer work when capacity is unavailable instead of queueing an unbounded
  population. Deferred eligible sources remain discoverable by later scans.
- Retain stored memory when Memory is disabled and pause preparation/use under
  the existing control. Archive and access loss deny new use; source purge
  prevents reuse. No additional memory toggle or independent historical-entry
  deletion surface is introduced.
- Treat missing or unreadable context snapshots as absent memory rather than
  reconstructing a fresh snapshot on an ordinary turn. Conversation and explicit
  current lookup remain available; new automatic selection follows the next
  approved boundary.
- Require neither retained Redis keys nor a new execution backend for recovery.
  Concrete record layout and non-public numerical limits are Design work.

### Option A — Minimal persisted progress with periodic reconciliation

Store source results and processing/retry progress in PostgreSQL and reuse
D1's bounded five-minute discovery to find eligible unfinished work. Use
existing process-local execution-key coalescing and bounded memory admission
for target-Agent background jobs. There is no separate durable per-attempt
queue or distributed memory-job ownership ledger.

- A restart abandons unfinished in-memory computation. Its source remains
  eligible for rediscovery because dispatch is not recorded as successful
  preparation.
- Recovery reruns work; it does not continue the old provider call. Successful
  progress and result publication are recorded together so an interrupted
  attempt cannot falsely complete a source.
- Separate processes, restart races, or uncertain provider completion may
  cause duplicate computation and cost. Last-result publication can replace a
  more recently prepared summary with older historical context; freshness is
  not guaranteed, and current source-access checks remain mandatory.
- Updates must remain source-scoped replacements, not additive promotion or
  other non-repeatable user-visible side effects.
- This keeps coordination state small, but offers weaker cross-process
  suppression and attempt observability. No exactly-once execution or global
  memory concurrency guarantee is promised.

### Option B — Durable distributed attempt ownership

In addition to the same source results, persist admitted memory attempts with
Agent ownership, an expiring lease, and publication ownership checks. The
scanner can reconcile expired attempts and avoid dispatching work already
owned by another process.

- This gives stronger cross-process duplicate suppression and explicit attempt
  recovery/inspection.
- Lease expiry, renewal, late completion, owner replacement, and cleanup create
  additional state and verification obligations.
- These are execution-ownership checks, not source-content revisions. Stale
  historical summaries remain allowed under the confirmed Requirements.
- Provider calls may still be repeated after an uncertain interruption; no
  exactly-once billing or provider execution is promised.
- It still runs through the existing LocalJobRuntime and does not introduce a
  Temporal or other workflow-service dependency.

### Recommendation and remaining boundaries

Recommend **Option A**, pending the requester, for the confirmed loose-memory
direction. Persist completed context and minimal retry progress, recover through
the already accepted scan, and tolerate occasional recomputation rather than
creating a distributed attempt subsystem.

The additional computation/cost and weaker distributed suppression are explicit
trade-offs, not measured production bounds. Retry constants and admission limits
must be validated against the shared Runtime and representative sources.
The initial admitted history window remains a separate product-scope question.
Neither option expands that window, approves a full old-Session sweep, or
authorizes implementation.

## Accepted Decision Log — Minimal Progress and Periodic Recovery

### memory-260930/ADR-D6 — Accepted at 2026-09-29T22:54:47.458000+00:00

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-3`, `REQ-6`, and `REQ-10`, with
  source/privacy boundaries in `REQ-1` and `REQ-2`, snapshot behavior in
  `REQ-7`, and accepted `memory-260930/ADR-D1`, `ADR-D3`, `ADR-D4`,
  and `ADR-D5`.
- **Choice:** Option A. Persist source-specific Historical Memory results and
  minimal processing/retry progress in PostgreSQL; recover unfinished work
  through the existing bounded periodic scan and LocalJobRuntime.
- **Result boundary:** successful result and processing progress publish
  together. Dispatch is not successful preparation. Explicit successful
  no-useful-context results remain distinguishable from failed/unprepared work.
  Failure preserves the previous permitted result and does not modify Saved
  Memory.
- **Recovery boundary:** process restart abandons unfinished provider
  computation; later scans rediscover eligible unfinished sources. There is no
  provider-call continuation or separate durable attempt/ownership ledger.
- **Duplicate/staleness trade-off:** existing process-local execution-key
  coalescing suppresses local duplicates, but cross-process/restart duplicate
  computation and cost are accepted. A late completed attempt may replace a
  newer summary with older historical context; exact freshness is not a gate.
- **Resource boundary:** bound discovery, Agent dispatch, per-Agent Session
  batches, memory admission and attempt duration, reserving shared capacity for
  discovery and other jobs. Defer rather than accumulate unbounded work.
- **Retry boundary:** retain failure/retry timing so unsuccessful work is
  delayed without a permanently stuck running marker. Retry constants and
  local admission limits are Design details requiring validation.
- **Snapshot failure boundary:** missing/unreadable snapshot state contributes
  no memory rather than triggering ordinary-turn reselection. Explicit lookup
  remains available; new automatic selection uses an approved context boundary.
- **Preserved controls:** ordinary inactivity/Run eligibility, current
  authorization and Memory enablement, archive/purge semantics, independent
  Saved Memory lifetime, and recovery without retained Redis keys or a new
  backend.
- **Rejected option:** a separate durable distributed memory-attempt ledger with
  leases, renewal, and publication-ownership fencing.
- **Feasibility obligation:** verify shared Runtime admission and Scheduler
  claim/deadline timing. Existing round-time reuse is not automatically fixed
  by selecting this option.
- **Deferred:** initial admitted history, equivalent record/schema details,
  numeric budgets and retry/admission limits, complete implementation Design
  and verification.
- **Approval boundary:** D6 is accepted. No complete Design or implementation
  approval is granted.

### Current decision state after D6 acceptance

Accepted technical decisions are `memory-260930/ADR-D1`,
`memory-260930/ADR-D3`, `memory-260930/ADR-D4`,
`memory-260930/ADR-D5`, and `memory-260930/ADR-D6`; D2 is withdrawn.
Saved Memory / Historical Memory terminology is confirmed. The initial admitted
history population is the remaining current product-scope question and must be
confirmed in Requirements before dependent rollout/Design mechanisms are chosen.

## Core Memory Content Review Before Design

The requester identified an unresolved core product lane: which useful context
is retained from a Session, the actual summary format and generation prompt,
how selected summaries are presented together, and the resulting model input.
These need connected examples and requester review before the complete Design.
The initial history-admission question follows this content review.

The accepted D1, D3, D4, D5, and D6 decisions retain their recorded boundaries.
D3 authorizes source-summary selection and formatting without a separate
integration-model call; it does not accept a particular summary format,
generation prompt, selection presentation, or model-facing interpretation
guidance. Illustrative content and prompts are proposals, not accepted decisions
or approved production behavior.

Review starts with what the summary retains, omits, qualifies, and contributes
to a later conversation. Confirmed changes to user-visible outcomes belong in
Requirements first, followed by any necessary technical decisions and Design.
No complete Design or implementation is authorized.

## Source-Summary Content Direction Confirmed

On 2026-09-30 at 10:20:25 KST, the requester confirmed the source-summary content
and density direction now recorded in `memory-260930/REQ-4`: bounded,
self-contained historical context that preserves consequential decision reasons,
corrections, evidence, and unfinished work. Significant earlier or superseded
context and task-limited requests retain their relevance and scope.

This is a confirmed product requirement, not acceptance of a new technical
mechanism. The accepted D1, D3, D4, D5, and D6 boundaries remain unchanged.
Generation-prompt wording and output presentation are the next review lane;
selection presentation, model guidance, final injection, numerical budgets,
initial historical admission, and complete Design remain unresolved.
Referencing Codex does not adopt its separate consolidation Agent or authorize
automatic changes to independently managed Saved Memory.

## Accepted Decision Log — Source Input Representation

### memory-260930/ADR-D7 — Accepted on 2026-10-01 at 08:45:32 KST

- **Owner:** requester.
- **Authority:** the confirmed content direction in `memory-260930/REQ-4`,
  with source/privacy boundaries in `REQ-1`, `REQ-2`, and `REQ-6`.
- **Choice:** align Historical Memory source-transcript representation with
  the existing Compaction event-to-text format instead of introducing a
  separate per-event JSON transcript representation.
- **Shared representation:** preserve chronological dialogue and distinguish
  user, Agent, and tool activity through the existing readable event labels
  and applicable semantic rendering.
- **Purpose boundary:** Historical Memory retains its source-history
  generation purpose. Compaction's execution-checkpoint instructions, output
  sections, model-input head movement, event emission, and hooks are not adopted
  by this format choice.
- **Privacy boundary:** Historical Memory applies its required exclusions,
  including hidden instructions, reasoning, secret values, and unauthorized
  source content. The current Compaction renderer has reasoning branches and
  therefore cannot be reused unchanged as a safe historical-input projection.
- **Rationale:** the requester accepted the common format. Reusing the
  existing event representation avoids maintaining a second transcript
  encoding while keeping purpose-specific instructions and filtering.
- **Rejected alternative:** the separately proposed event-level JSON encoding.
- **Deferred:** source input range, checkpoint use, long-source selection,
  extraction windows, refresh method, numerical budgets, complete generation
  prompt and output envelope, cross-Session presentation, and final injection.
- **Approval boundary:** this accepts the input representation only, not the
  whole prompt, either proposed input-selection policy, complete Design, or
  implementation.

## Accepted Decision Log — Codex-Style Source Input Selection

### memory-260930/ADR-D8 — Accepted on 2026-10-01 at 17:29:29 KST

- **Owner:** requester.
- **Authority:** the bounded, best-effort source-history outcome in
  `memory-260930/REQ-4` and the Lightweight model route in ADR-D4.
- **Choice:** use the inspected Codex V2 source-input selection pattern for one
  admitted Session. Build a filtered candidate set from the source history
  available to the extraction, allocate 70 percent of the extraction model's
  effective context window to source evidence, select newest evidence first
  within ordered evidence tiers, restore the selected evidence to source
  chronology, mark omitted intervals, and perform one extraction-model call.
- **Evidence tiers:** human-authored conversation evidence precedes visible
  Agent conversation evidence; other-Agent/context evidence follows where
  applicable; ordinary tool evidence is lowest. Exact mapping to Azents event
  variants is Design work and must preserve the separate conversational-tool
  decision below.
- **Bounded evidence:** individual rows and tool text are bounded. Transport
  fragmentation of one prepared request does not create per-chunk model
  summarization or a multi-pass memory workflow.
- **Trade-off:** old source evidence can be omitted when the Session exceeds
  the input budget. Later consolidation cannot recover raw evidence omitted
  from this source extraction. This is an accepted best-effort quality and
  cost boundary rather than a lossless-history promise.
- **Rejected option:** a chronological multi-pass workflow that ensures every
  eligible event is supplied to at least one extraction-model call.
- **Preserved boundaries:** source authorization, filtering, lifecycle,
  six-hour eligibility, stale-summary permission, and no separate D3
  integration-model call remain unchanged.
- **Deferred:** concrete event-tier mapping, per-row and tool-text constants,
  source read snapshot mechanics, complete generation prompt/output envelope,
  refresh mechanics, and quality validation.
- **Approval boundary:** this accepts source selection and call shape, not the
  complete Design or implementation.

## Accepted Decision Log — Declarative Conversational Tool Projection

### memory-260930/ADR-D9 — Accepted on 2026-10-01 at 17:29:45 KST

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-4` requires user and Agent decisions,
  corrections, evidence, and unfinished work to remain distinguishable. ADR-D7
  establishes the shared readable event representation, and ADR-D8 establishes
  evidence tiers.
- **Choice:** maintain a central declarative registry of client tools whose
  durable calls contain participant-visible conversation. Registered call
  fields are projected as conversation evidence before ADR-D8 tier selection;
  unregistered tools remain ordinary tool evidence.
- **Registration contract:** one registry entry identifies the durable final
  tool name and declaratively identifies participant-visible text fields and
  any conditions or structured work-state fields needed for projection. A new
  tool with the same role is supported by adding one registry entry rather
  than another Historical Memory renderer branch.
- **Current application:** `channel_action.message` is Agent-authored
  participant-visible conversation. Its mode and structured title/task update
  can provide scoped work-state evidence, while `ignore` produces no
  conversational message. The linked Tool result represents delivery outcome,
  not the missing reply body.
- **Selection ownership:** the registry and deterministic projector decide
  representation, eligibility, call/result linkage, and budget class. The
  extraction model decides which supplied conversational or tool evidence is
  meaningful enough to retain in the summary.
- **Durability boundary:** the registry retains historical durable tool names
  needed to interpret stored calls. Missing, malformed, or incompatible
  registered arguments fall back to bounded ordinary tool evidence rather than
  failing the complete extraction or inventing conversation.
- **Rejected option:** hard-code `channel_action` inside Historical Memory
  rendering.
- **Deferred:** registry type and file placement, exact declarative path/schema
  structure, applicable existing renderers, delivery-status phrasing, test
  fixtures, and whether other current tools satisfy the conversational role.
- **Approval boundary:** this accepts the extensible projection contract, not
  a new tool, a tool-schema change, complete Design, or implementation.

## Accepted Decision Log — Source Summary Output Contract

### memory-260930/ADR-D10 — Accepted on 2026-10-01 at 19:24:40 KST

- **Owner:** requester.
- **Authority:** the source-summary content outcome in
  `memory-260930/REQ-4`, with source clues and inspection behavior in `REQ-8`.
- **Choice:** the extraction model returns one strict JSON object containing
  only a `summary` string. The string is the bounded Markdown Historical
  Memory account. An empty string represents successful extraction with no
  useful historical context.
- **Service-owned metadata:** source Session identity and title, the captured
  source boundary, preparation time, scope, and authorization/lifecycle data
  are persisted by the service rather than generated inside the model's
  summary output.
- **Rationale:** Codex V2's rollout summary content contract is retained while
  its filesystem-oriented `rollout_slug` has no authoritative role in Azents.
  Letting the model recreate source identity would duplicate canonical Session
  data and permit invented or unstable identifiers.
- **Rejected option:** Codex V2's `rollout_summary` plus `rollout_slug` envelope.
- **Preserved conditions:** strict schema decoding, empty-success distinction,
  source-linked storage, ADR-D8's one-call selection, and ADR-D9's conversation
  projection remain required.
- **Deferred:** final field/type implementation, concrete size guard, complete
  prompt wording, cross-Session selection and presentation, and final model
  context.
- **Approval boundary:** this accepts the extraction output envelope, not the
  complete generation prompt, Design, or implementation.

## Accepted Decision Log — Deterministic Memory Snapshot Assembly

### memory-260930/ADR-D11 — Accepted on 2026-10-01 at 19:30:26 KST

- **Owner:** requester.
- **Authority:** `memory-260930/REQ-5`, `REQ-7`, and `REQ-8`, with the
  no-integration-model boundary in ADR-D3 and source output in ADR-D10.
- **Choice:** assemble the automatic Memory snapshot deterministically from
  permitted Saved Memory index entries and whole source-specific Historical
  Memory summary blocks. Do not generate cross-Session overview prose.
- **New-Session selection:** when no current conversation topic exists, rank
  Historical Memory candidates by source last activity, then preparation time,
  then source Session ID for a stable tie-break.
- **Known-topic selection:** after compaction and for explicit lookup, rank by
  lexical relevance of the current topic or lookup query against source title
  and summary, then use the same recency and stable tie-break order.
- **Packing and presentation:** select only complete source-summary blocks
  within the Historical Memory budget. Present selected sources from older to
  newer source activity so explicit later corrections can be interpreted in
  chronology. Repeated statements are not promoted to independent
  corroboration.
- **Model guidance:** distinguish independently managed Saved Memory from
  source-linked Historical Memory; treat Historical Memory as potentially
  incomplete, stale, or wrong historical data rather than new instructions,
  current authority, or proof. Current instructions and verified evidence take
  precedence. Inspect a permitted source when exact wording, chronology,
  evidence, or uncertainty can materially change the answer; otherwise avoid
  speculative history reads. Historical Memory does not automatically mutate
  Saved Memory.
- **Source presentation:** each Historical block carries service-owned Session
  identity, scope, title, source activity boundary, and preparation time, and
  is enclosed in an explicit historical-data boundary.
- **Rejected mechanisms:** a separate overview-model call, generated integrated
  overview prose, embeddings, an importance model, a usage-feedback ranking
  loop, or an inferred ongoing-work classifier.
- **Risk:** recency-only new-Session selection may omit older but broadly useful
  history, and whole-block packing may select fewer sources. User and Team
  scopes compete under the same ranking while retaining visible scope labels;
  validation must check material starvation.
- **Deferred:** numerical budgets, exact lexical scoring/tokenization, handling
  of legacy oversized summaries, snapshot persistence layout, and complete
  implementation Design and verification.
- **Approval boundary:** this accepts selection, presentation, and model-use
  guidance, not initial old-Session admission, numerical limits, complete
  Design, or implementation.

## Accepted Decision Log — Pluggable VFS Read Backends

### memory-260930/ADR-D12 — Accepted on 2026-10-01 at 19:46:51 KST

- **Owner:** requester.
- **Authority:** on-demand available-memory and source-inspection outcomes in
  `memory-260930/REQ-8`, the existing VFS/read-tool capability, and D5's unified
  discovery direction.
- **Choice:** replace the proposed family of dedicated Memory/history read
  tools with a general VFS read interface whose registered mount backends
  implement storage-efficient read operations. Generic file read tools route
  canonical `azents://` locations to the owning backend.
- **Backend boundary:** VFS is a namespace and read router rather than one
  mandatory embedded immutable body projection. The current Skills mount can
  continue to use an immutable AgentRun projection, while a Memory mount may
  query PostgreSQL and render authorized virtual text lazily.
- **Authority boundary:** the router supplies server-derived execution/root
  identity. Each backend independently enforces its current domain authority.
  A live Memory backend rechecks Memory enablement, Agent, Workspace,
  Team/associated-User scope, and source lifecycle for every operation.
- **Efficiency boundary:** backend operations return common bounded results
  but may use indexed queries, immutable in-memory entries, or another
  backend-native strategy. The router does not silently materialize or scan an
  entire backend when an operation is unsupported.
- **Write boundary:** this decision is read-only. Runtime `write`, `edit`,
  `delete`, patch, and shell path behavior remains separate. Saved Memory
  mutations retain their explicit tools; Historical Memory has no direct
  mutation surface.
- **Rationale:** all Memory and history records are text projections, while
  dedicated list/search/read/history tools duplicate generic file discovery
  and reading. Backend-native VFS operations reduce the model-facing tool
  surface without forcing a dynamic or unbounded Memory corpus into the
  current 8 MiB immutable Run projection.
- **Rejected options:** retain the eight-tool Memory/history read family, or
  publish all Memory files as bodies inside the existing immutable Skills-style
  projection.
- **Deferred:** exact backend protocol and capability set, URI directory/glob
  grammar, Memory tree layout, generic tool description changes, result bounds,
  removed-tool list, and implementation Design/validation.
- **Approval boundary:** this accepts the pluggable VFS read architecture, not
  a particular tree, every read capability, complete Design, or implementation.

## Accepted Decision Log — Common VFS Read Capabilities

### memory-260930/ADR-D13 — Accepted on 2026-10-01 at 19:55:11 KST

- **Owner:** requester.
- **Authority:** the pluggable VFS architecture in ADR-D12 and the existing
  generic `read`, `grep`, and `glob` model-facing capabilities.
- **Choice:** VFS read backends may implement three common model-facing
  capabilities: bounded text read, bounded regex grep, and bounded glob
  discovery. Exact file transfer is an optional backend capability and is not
  required for the Memory mount.
- **Common contract:** generic tools retain backend-independent result
  semantics, limits, truncation reporting, deterministic ordering, and
  operation deadlines. A backend may impose stricter limits but cannot exceed
  the common maximums.
- **Routing boundary:** absolute Runtime paths continue through FileStorage;
  canonical `azents://` exact files, directory roots, and glob patterns route
  through the registered mount backend. Exact URI, directory URI, and glob
  pattern validation are separate.
- **Capability boundary:** unsupported operations fail explicitly. Neither the
  router nor generic tool handler materializes a complete backend as a fallback.
- **Exposure boundary:** VFS-backed read/grep/glob must remain available when
  their authorized backends are available, even when Runtime filesystem or
  process capabilities are unavailable. Runtime-path branches remain
  capability-gated.
- **Write boundary:** generic VFS write/edit/delete/patch support remains out of
  scope. The Memory mount is read-only; its Saved Memory mutations retain
  explicit domain tools.
- **Rationale:** glob provides efficient virtual path discovery without
  requiring generated index files for every directory, while read and grep
  cover exact detail and content discovery. Optional transfer preserves the
  existing Skills/import path without imposing binary materialization on
  Memory.
- **Deferred:** concrete protocol/type names, tool ownership refactor, Memory
  tree, regex/glob implementation strategies, limits, removed tools, and
  complete Design/verification.
- **Approval boundary:** this accepts the capability set and exposure boundary,
  not the complete VFS or Historical Memory Design or implementation.

## Accepted Decision Log — Live Memory VFS Tree

### memory-260930/ADR-D14 — Accepted on 2026-10-01 at 20:00:49 KST

- **Owner:** requester.
- **Authority:** the pluggable/capability VFS decisions in ADR-D12 and ADR-D13,
  unified discovery in ADR-D5, source inspection in `memory-260930/REQ-8`,
  settings/source lifecycle in `REQ-6` and `REQ-9`, and the conversational-tool
  projection in ADR-D9.
- **Choice:** expose Saved Memory, prepared Historical Memory, and authorized
  original Session evidence through a live read-only `azents://memory` mount.
  Use canonical database IDs in paths, one root README, glob discovery, backend
  grep, and exact text reads. Do not generate per-directory index files.
- **Tree boundary:** separate Saved paths by `agent`/`user`, Historical summary
  paths by source `team`/`user`, and original source paths by source scope,
  Session ID, event ID, and selected tool-result event ID.
- **Source rendering:** original visible conversation is represented as
  semantic event files with provenance, adjacent-event paths, and an optional
  exact tool-result path. ADR-D9-registered tool-mediated conversation is
  rendered as conversation with tool and delivery provenance, without
  rewriting durable events.
- **Sensitive evidence:** broad grep excludes arbitrary tool-result bodies.
  A currently authorized exact tool-result path provides bounded text reads;
  attachments, native artifacts, hidden metadata, and bytes remain excluded.
- **Snapshot boundary:** automatic Memory context remains a Session-owned
  boundary snapshot and includes exact VFS paths for selected entries. Explicit
  VFS operations are live and do not refresh or rewrite that injected snapshot.
- **Tool-removal boundary:** after replacement verification, remove
  `list_memories`, `get_memory`, `search_memories`, `search_sessions`,
  `read_session_history`, and `read_session_tool_result` without compatibility
  aliases. Retain `save_memory` and `delete_memory` for Saved Memory mutation.
- **Lifecycle boundary:** Memory VFS paths are virtual, not independent stored
  copies. Current disablement, access loss, archive, restore, and purge are
  reflected by the next operation.
- **Rejected options:** retain dedicated Memory/history read tools, use
  arbitrary names/titles as URI segments, generate directory index files as a
  required discovery mechanism, or include tool-result bodies in broad grep.
- **Deferred:** exact Markdown/frontmatter wording, URI/result constants,
  adjacent-event query implementation, generic tool refactor, and complete
  Design/verification.
- **Approval boundary:** this accepts the tree and replacement behavior, not
  the complete Design or implementation.

## Accepted Decision Log — Rolling First Admission

### memory-260930/ADR-D15 — Accepted on 2026-10-01 at 19:36:21 KST

- **Owner:** requester.
- **Authority:** the requester-confirmed rolling window in
  `memory-260930/REQ-3`, scheduling in ADR-D1, and recovery in ADR-D6.
- **Choice:** first admit an unprepared source only when its latest activity is
  at least six hours and no more than ten days old, with no ongoing Run and all
  current scope/access/enablement conditions satisfied.
- **Progress boundary:** the ten-day maximum applies only before first
  admission. Persisted admitted preparation and retry progress remains
  recoverable after the source ages past ten days.
- **Result boundary:** prepared Historical Memory remains stored and eligible
  for permitted snapshot selection, live VFS lookup, and settings inspection
  after ten days. Source lifecycle and access, not age, govern usability.
- **Reactivation boundary:** Memory-disabled time creates no admission.
  Re-enablement considers the then-current rolling ten-day window and does not
  create an unlimited backfill. New source activity establishes a new latest
  activity time and can make an older unprepared source eligible after six
  hours.
- **Rationale:** this matches the inspected Codex default age/idle admission
  shape, bounds launch and re-enable cost, and applies one rule without a
  separate per-Agent feature-activation epoch.
- **Rejected options:** future-only preparation, all active/archive-horizon
  backfill, and a one-time activation window followed by indefinitely eligible
  unadmitted sources.
- **Deferred:** exact scan and dispatch counts, indexes, progress schema,
  retry constants, observability, rollout flags, and complete Design.
- **Approval boundary:** this accepts admission scope and age semantics, not
  complete Design or implementation.
