---
title: "Session Routines Technical Decisions"
created: 2026-10-18
tags: [routine, agent, conversation, toolkit, frontend, architecture]
document_role: primary
document_type: adr
snapshot_id: routine-261018
---

# Session Routines Technical Decisions

- Snapshot: `routine-261018`
- Document reference: `routine-261018/ADR`
- Requirements: [routine-261018/REQ](../requirements/routine-261018-session-routines.md),
  confirmed by the requester on 2026-10-18 (KST).
- Mode: Collaborative. The requester owns unresolved material decisions.
- Research baseline: `f045c138934aedb935baa538af93afc4489762d8`.

## Context

The confirmed Requirements separate Session-wide tool-free action judgment from
ordinary Agent execution and independent per-Routine completion. Existing
Scheduled Task and External Channel mechanisms supply useful infrastructure, but
neither domain's terminal-result contract is the Routine completion contract.
This document records accepted material choices only after requester selection;
the register below is a discussion map, not authority to implement proposals.

## Current-System Evidence

- [Periodic execution](../spec/flow/periodic-execution.md) separates bounded
  Scheduler admission from Worker execution. Scheduled Task dispatch commits its
  cycle, typed Mailbox input, cursor, and recovery wake before broker I/O.
- `worker/session/runner.py` claims Session execution ownership, dispatches the
  normal execution path, handles stop and shutdown/handover, and finalizes a
  completed Run through `worker/session/idle_continuation.py`.
- `worker/session/idle_continuation.py` currently supports Goal, External Channel,
  and Scheduled Task continuation inputs. Routine continuation requires an
  explicit extension; it is not already available through an opaque metadata
  flag.
- [Scheduled Tasks](../spec/domain/scheduled-task.md) use a result contract that
  terminalizes the Run. Independently completing multiple Routines must not
  adopt that terminal side effect.
- `engine/events/engine_adapter.py` assembles normal Agent prompts, transcript
  lowering, tools, model selection, and execution authority. The current
  `engine/model_text.py` structured helper builds a system/user text request;
  it does not accept the canonical Session conversation as its input contract.
  `engine/events/pydantic_ai_lowering.py` and `responses_lowering.py` contain
  the existing canonical-history lowering paths.
- [External Channel delivery](../spec/flow/external-channel-delivery.md) owns
  Binding authorization, canonical Action admission, and one-attempt provider
  effects. Its Work lifecycle is separate from Routine completion. Routine
  notification must preserve existing delivery policy without hijacking a
  participant's active Channel Work.
- `rdb/models/external_channel.py` enforces one connected Binding per resource,
  not one Binding per Session. `repos/external_channel/mailbox_ingestion.py`
  and `access_operations.py` currently create a root Session before creating a
  new Binding. Static creation-path evidence does not prove existing data has
  no cardinality exceptions.
- [Conversation lifecycle](../spec/domain/conversation.md) rejects new work for
  archived Sessions and delegates permanent deletion to fenced subtree purge.
  `repos/scheduled_task_lifecycle_participant.py` removes pre-start Scheduled
  authority at archive and does not recreate it at restore. That feature-specific
  policy does not decide whether Routine definitions survive archive.
- Existing presentation surfaces include
  `typescript/packages/azents-session-core/src/toolActivityPresentation.ts` and
  `typescript/apps/azents-web/src/features/chat/knownToolPresentation.ts`.
  `testenv/azents/e2e/src/tests/required/public/test_scheduled_tasks.py` supplies
  precedent for deterministic time-driven admission and durable-history E2E
  observations, not an existing Routine test implementation.

All Python paths above are relative to `python/apps/azents/src/azents/`.
Research is static; no live provider, migration, data audit, or Routine execution
has been performed.

## Fixed and Derived Boundaries

- Routine definitions belong to a Session; Manual is the only initial source.
- Tick cadence and minimum action delay are distinct 30-minute defaults. A
  no-action decision does not advance the last-action reference.
- Judgment considers eligible Session candidates jointly, uses ordinary Session
  context, injects no callable tools, and returns Structured output.
- Execution uses the normal Session inbox and Agent path. Completion closes one
  admitted Routine occurrence rather than the entire normal Run or Channel Work.
- Incomplete admitted work continues only at the approved normal-completion
  boundary. User Stop remains a cancellation boundary, not an automatic retry.
- Updates compare exact prior content with separate intended changes. They do
  not require definition version numbers or a version history.
- An admitted occurrence retains its objective/context after a definition edit.
  Definition deletion does not cancel admitted work and late completion must
  not recreate retained records for the deleted definition.
- Work records retain the latest 100 per Routine. Judgment-call history follows
  ordinary conversation-history retention and Session cleanup without a separate
  Routine-specific count limit, as confirmed in `routine-261018/REQ-16`.
- Notification follows the current Primary at delivery, or Session chat with
  no Primary. It adds no Routine-specific retry, outbox, fallback, or authority.
- Read-only inspection, low-emphasis judgment history, and semantic Routine tool
  presentation are required. Exact component layout remains a local design detail.
- Existing Session ownership, archive admission fences, and permanent-purge
  authority remain applicable. `routine-261018/REQ-18` confirms Scheduled-style
  archive removal, preserved started work, no definition recreation on restore,
  and permanent-purge cleanup.

## Material Decision Register

These are candidate material decision lanes. Reassess later lanes after earlier
choices: if approved authority determines an outcome, record it as derived rather
than asking a redundant question. Pending entries provide no implementation
authority. Accepted entries reference their `routine-261018/ADR-DN` below.

| Topic | State | Consequence to resolve | Requirements |
| --- | --- | --- | --- |
| Judgment execution ownership and concurrency | Accepted: ADR-D1 | Run read-only judgment independently of the ordinary Run; conversation advancement does not invalidate its result | REQ-4, REQ-6, REQ-7, REQ-8, REQ-11 |
| Durable Routine and admitted-work authority | Accepted: ADR-D2 | Follow Scheduled Task execution lifecycle and reuse Session Toolkit State for active execution; retain the approved Routine-specific completion contract | REQ-1, REQ-8 through REQ-13 |
| Full-context Structured operation integration | Derived scope; feasibility review pending | REQ-7 and ADR-D1 require canonical Session context, tool-free Structured output, and independent judgment. Reuse existing capability and native-call boundaries; equivalent helper layout is agent-owned. Return any newly discovered material mechanism for decision | REQ-7, REQ-11, REQ-16, ADR-D1 |
| Judgment history persistence and projection | Accepted: ADR-D3 | Dedicated Session observation events own judgment results and call-specific usage; ordinary Run turn/context projections remain unchanged | REQ-7, REQ-13, REQ-15, REQ-16 |
| Primary Channel authority and migration | Derived scope; deployment preflight required | Session owns zero or one current Primary. Preserve bindings; backfill an unambiguous connected binding, and stop ambiguous migration rather than silently select or disconnect. Exact equivalent field placement is agent-owned; real-data audit is not yet performed | REQ-14, existing External Channel authorization and lifecycle boundaries |

All unresolved material lanes are requester-owned. None has been delegated.
Function names, equivalent field arrangements, helper/module layout, and fixture
names are agent-owned details only when they create no additional behavioral,
persistence, lifecycle, security, or operational contract.

## Product Clarifications

These are not technical decisions. Confirm the affected Requirements before
finalizing a mechanism that depends on either answer.

- **Judgment-history retention — resolved, 2026-10-18 (KST):** The requester
  confirmed ordinary conversation-history retention and Session cleanup with no
  additional count limit. Recorded in `routine-261018/REQ-16`; the separate
  per-Routine 100-work-record limit remains unchanged.
- **Archive and restore — resolved, 2026-10-18 (KST):** The requester confirmed
  Scheduled-style removal of definitions, retained work records, and pre-start
  work on archive; completion of preserved started work; no definition
  recreation on restore; and purge waiting and residual cleanup. Recorded in
  `routine-261018/REQ-18`.

## Accepted Decisions

### D1. Judge independently of ordinary Agent execution without conversation-freshness invalidation

- Reference: `routine-261018/ADR-D1`
- Accepted by: requester, 2026-10-18 (KST).
- Requirements: `routine-261018/REQ-4`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-11`.

**Decision**

Run tool-free Routine judgment as an independently owned read-only model
operation that may overlap an ordinary Agent Run in the same Session. It must
not wait for that Run to finish. Judgment uses the Session context read when its
request is assembled. New conversation messages or ordinary Run progress during
the call do not invalidate the decision.

Do not introduce a judgment-age expiry, conversation-revision comparison, or
automatic rejudgment because conversation context advanced. The requester
explicitly selected overlapping judgment and rejected treating the brief context
lag of a model call as a reason to discard its decision.

Selected work is admitted to the ordinary Session inbox and normal execution
path. Overlapping judgment does not grant a second ordinary execution owner or
promise immediate execution of the admitted work.

Existing admission conditions still apply when committing selected work:
Session and authorization remain valid, a deleted Routine is not newly selected,
an incomplete occurrence is not selected a second time, and the approved
Session action-delay contract remains enforced. Execution-owner fences prevent
superseded workers from committing. These are eligibility and authority checks,
not an assessment of whether the model's semantic judgment has become old.
Exact durable ownership, claim, and recovery mechanisms remain in the following
decision lanes.

**Alternatives**

- Serialize judgment behind the ordinary Session Run. This reuses the current
  execution ordering but delays checking for the duration of long-running work.
  Rejected because checking must proceed while ordinary work is active.
- Run judgment independently, invalidating decisions after conversation changes
  or an additional freshness interval. Rejected: ordinary context progression
  during the call is not a reason to repeat or discard judgment.

**Consequences**

- Judgment needs an ownership and cancellation boundary independent of the
  ordinary Run. Scheduler remains a bounded admission role, not a model executor.
- Both ordinary execution and judgment must assemble canonical Session context
  without adding judgment tools or weakening existing model capability checks.
- Tests must show that a blocked ordinary Run does not block judgment and that
  a newly arrived message does not discard or repeat a valid in-flight judgment.
- Concurrent deletion, duplicate admission, archive, and lost authority must
  remain distinguishable from harmless conversation advancement.

This accepted decision is not complete Design approval or implementation
authorization.

### D2. Follow the Scheduled Task execution lifecycle and active-state storage

- Reference: `routine-261018/ADR-D2`
- Accepted by: requester, 2026-10-18 (KST).
- Requirements: `routine-261018/REQ-1`, `REQ-8` through `REQ-13`.

**Decision**

Align admitted Routine execution with the existing Scheduled Task execution
model: normal Session inbox admission, Session-scoped Toolkit State for active
execution, ordinary AgentRun processing, the existing continuation boundary, and
existing stop and recovery policy. Do not introduce a Routine-only autonomous
work lifecycle as the rationale for a separate active-execution store.

Per-Routine completion tracking distinguishes obligations within that execution
model. It does not create another independently runnable job or grant permission
to restart stopped work. Worker shutdown and ownership handover retain their
ordinary recovery semantics rather than becoming a new Routine retry mode.

Reuse the Scheduled active-state pattern, not its Task-specific terminal side
effects. A Routine result records that Routine's result and continuity hint,
removes its incomplete obligation, and optionally notifies under the confirmed
contract. It must not immediately terminalize the normal Run or a participant's
Channel Work. Normal completion with incomplete obligations uses the existing
continuation machinery, extended for Routine inputs and the required context.

Keep Routine definitions and the retained work-record product separate from
active Toolkit State. Exact schema and equivalent local state organization remain
Design details unless they introduce another material contract. No definition
version history or new version-number interface is authorized.

**Rationale and rejected alternative**

The earlier storage proposal conflated per-item completion with a separately
authorized execution lifecycle. The requester rejected that distinction and
directed alignment with Scheduled Tasks. The proposal for a separate
Routine-domain active-execution store on that rationale is withdrawn, not
accepted.

Existing Scheduled continuation evaluates a completed AgentRun boundary and
enqueues further Session input. A subsequent physical AgentRun may process that
input. This existing implementation fact is not a Routine-specific independent
lifecycle, and this decision does not change general AgentRun identity or
completion semantics.

**Consequences**

- Extend and reuse Scheduled-style active-state persistence, ownership checks,
  inbox handoff, and continuation rather than introducing another job runner.
- Verify individual completion, incomplete-work continuation, user Stop,
  shutdown/handover, definition edits, and late completion under that model.
- Preserve already confirmed Routine-specific behavior where it differs from
  Scheduled Tasks; this decision does not import mandatory output, schedule
  controls, Run-terminalizing result submission, or automatic definition removal
  on Session archive.
- Routine archive/restore definition behavior remains the explicit product
  clarification above. Aligning execution lifecycle does not silently answer it.

### D3. Record judgment as a dedicated Session observation with call-specific usage

- Reference: `routine-261018/ADR-D3`
- Accepted by: requester, 2026-10-18 (KST).
- Requirements: `routine-261018/REQ-7`, `REQ-13`, `REQ-15`, `REQ-16`.

**Decision**

Use a dedicated typed Session event as the canonical judgment-history record.
Record the considered Routine identities, Structured result or failure, and
available call-specific model and normalized usage information. Reuse existing
Session history, live projection, retention, and purge infrastructure rather than
creating a separate judgment-history store and synchronizing a second timeline.

The event is an observation, not a fabricated user/assistant message, ordinary
turn-completion marker, or AgentRun. The UI renders the low-emphasis collapsed
Routine judgment indication from this event. Ordinary Routine tool activity
remains a separate operation.

Judgment shares the Session conversation basis but has a different actual model
input: no callable tools, plus candidate context and judgment instructions.
Attribute its actual usage to that judgment call. Do not let it replace ordinary
Run turn usage, the current execution-context gauge, or the ordinary prompt and
context-breakdown snapshot. Do not emit a normal turn marker or reuse the normal
output-admission side effects for a judgment result.

As with existing metadata observations, passive judgment recording does not
advance ordinary Session conversation-activity recency. History presence alone
does not turn the observation into a semantic user/assistant message in future
model input. Keep canonical-history lowering and token estimation consistent with
this observation role.

No new total-cost accounting policy is introduced. Available normalized usage
and cost provenance may remain inspectable on the judgment event without being
misrepresented as usage of an ordinary Agent turn.

**Evidence**

- `rdb/models/event.py` and `repos/agent_execution/data.py::EventCreate`
  support Session-scoped events without a required Run ID.
- `engine/events/types.py::TurnMarkerPayload` requires a Run ID and describes
  ordinary turn usage; it is not a generic helper-call usage envelope.
- `repos/agent_execution/__init__.py::advance_session_projections` advances
  activity only for enumerated substantive event kinds, not every observation.
- `services/chat/context.py::_latest_usage` selects ordinary turn markers.
- `engine/events/filters.py::_compaction_input_tokens` uses the latest ordinary
  turn marker and model-visible following input to estimate context.
- `repos/engine_output_operation.py::admit_model_output` appends ordinary turn usage and
  replaces or clears the Session system-prompt snapshot. Judgment must not
  acquire those side effects through incidental code reuse.
- `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts`
  projects `turn_marker` into `turn_complete` and selects its latest usage;
  `components/TokenUsageIndicator.tsx` uses that value for context percentage.
  A dedicated judgment event must not enter that path.

Python paths above are relative to `python/apps/azents/src/azents/`; the component
path is relative to the named Web chat feature.

**Alternatives**

- A separate judgment-history store with an additional chat projection: viable,
  but introduces another canonical history owner and retention/live-query
  integration without a requirement that needs them. Not selected.
- An ordinary turn marker or assistant message carrying judgment output: not
  compatible with the approved observation and usage-separation contract.

**Consequences and verification**

- Add explicit typed event, history/live/API, and frontend decoding support.
  Update canonical provider lowerers and token estimates coherently.
- Interleave a normal turn, a judgment with different prompt-token usage, and a
  later normal turn in both live and reloaded history tests. Judgment details
  show their own usage while the normal gauge and context inspector retain the
  correct ordinary execution provenance.
- Verify that judgment recording neither emits normal Run completion nor
  overwrites the normal system-prompt snapshot or conversation recency.
