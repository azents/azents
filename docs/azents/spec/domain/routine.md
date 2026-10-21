---
title: "Session Routine Domain Spec"
created: 2026-10-19
tags: [routine, agent, conversation, toolkit, scheduler, frontend]
spec_type: domain
domain: routine
code_paths:
  - python/apps/azents/src/azents/core/routine*.py
  - python/apps/azents/src/azents/core/model_operation.py
  - python/apps/azents/src/azents/rdb/models/routine*.py
  - python/apps/azents/src/azents/repos/routine/**
  - python/apps/azents/src/azents/repos/session_primary_channel.py
  - python/apps/azents/src/azents/services/routine/**
  - python/apps/azents/src/azents/scheduler/routine_source_dispatch.py
  - python/apps/azents/src/azents/engine/routine_judgment*.py
  - python/apps/azents/src/azents/engine/tools/routine*.py
  - python/apps/azents/src/azents/worker/run/routine_judgment*.py
  - python/apps/azents/src/azents/worker/run/executor.py
  - python/apps/azents/src/azents/api/public/chat/v1/routine_api_test.py
  - typescript/apps/azents-web/src/features/session-routines/**
  - typescript/apps/azents-web/src/features/chat/routineTool*
  - typescript/apps/azents-web/src/features/chat/components/Routine*
  - typescript/apps/azents-web/src/trpc/routers/routine.ts
  - typescript/packages/azents-session-core/src/routinePresentation*
  - testenv/azents/e2e/src/tests/required/public/test_routine*.py
  - testenv/azents/e2e/src/tests/web/public/test_routines.py
api_routes:
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/routines
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/routines/{slug}
last_verified_at: 2026-10-21
spec_version: 3
---

# Session Routine Domain Spec

A Routine is an ongoing objective owned by one concrete Session. Eligible source
checks ask the Session's selected model whether work is useful. A positive choice
enters the ordinary Run/tool loop; completing one Routine occurrence records its
own result without completing the Run or another Routine's work. Routines are
neither time-specific Scheduled Tasks nor a Session Goal.

## Definition and Management

The durable definition stores ID, exact Workspace/Agent/Session ownership, stable
slug, title, objective, supported sources and timestamps. A Session has at most 20
definitions. Accepted title/objective text is preserved exactly and must be
nonblank. The only supported source is `manual`: regular checking at eligible
source ticks, not a user-facing run button. An empty source list supplies no
candidate input. Creation does not immediately run judgment.

New definitions derive their stable tool-facing slug from the title: Unicode NFKC
normalization and case folding preserve letters and numbers, separator runs become
hyphens, and the result is limited to 64 characters (`routine` when no letters or
numbers remain). No UUID or collision suffix is appended. Creation rejects an
existing slug in the same Session without overwriting it; different Sessions may
use the same slug. The ordinary Session mutation fence serializes concurrent
creation. Title edits retain the slug. Existing stored identifiers and admitted
contexts remain unchanged.

The automatically connected root Toolkit exposes `create_routine`,
`list_routines`, `inspect_routine`, `update_routine`, `delete_routine`,
`read_routine_context` and `record_routine_result`. Management uses the executing
Session's authority, not a model-supplied owner. Update compares the complete
provided prior content with current persisted content before applying separate
changes; a mismatch fails and requires reading current state. Omitted fields are
preserved. Delete removes the definition, future eligibility and retained work
records. It does not revoke the immutable context of already admitted work.

## Source Admission and FIFO Judgment

The existing Scheduler runs a source-only dispatcher. It coalesces source evidence
and enqueues one internal `routine_judgment` inbox action per eligible Session.
There is no judgment worker, independent Run owner, domain lease or retry timer.
The ordinary Session owner and FIFO/Run boundary execute the action; earlier
ordinary work finishes its current boundary before judgment. Recovery and Stop
use the existing execution-generation fences.

Settled judgment advances the Session checking checkpoint to completion time;
the next regular opportunity follows the Agent's `routine_check_interval_minutes`
(new-Agent default 180 minutes), independently of selected-work completion.
The separate Agent `routine_min_action_delay_minutes` uses the existing
last-action reference and defaults to 30 minutes.
Agent administrators edit both in profile settings through the existing save
flow. Strict whole-minute values satisfy `30 <= minimum delay <= tick <= 1440`.
Supplying minimum delay automatically raises tick when needed, using the supplied
tick or the current stored tick. Reducing delay never reduces tick. Tick-only
inversions, invalid create pairs, null, fractional, boolean and out-of-range
values are rejected. Other omitted values are preserved. Source collection also advances the checkpoint while a judgment is
queued. Selection respects the later of the checking and minimum-action-delay
boundaries. No-action and failed judgment advance the checking checkpoint but
do not advance the last-action reference. The shared Scheduler uses the earliest
eligible Session time, capped at the regular 30-minute discovery interval.
Due selection and fenced admission read the same current Agent values. Changes
apply at the next scheduled scan, which may take up to the discovery interval
plus normal scheduling latency, and do not cancel queued or running judgments.
Capture and final settlement re-read the current minimum delay at their existing
action-admission gates. Tick is not a second execution gate for already captured
judgment. Existing Agents transfer old tick to minimum delay with a 30-minute
floor, then set new tick to at least 180 minutes. Neither setting guarantees
investigations or notifications at that frequency.
An early scan schedules the remaining delay instead of another full interval;
normal scheduler polling and FIFO work may add latency. Source evidence remains
durable and ongoing incomplete occurrences are excluded from selection.
Captured candidates and source evidence are stable for one judgment. New user
input during the call remains available and does not invalidate or repeat an
otherwise valid decision; later source evidence is retained separately.

Judgment uses canonical Session history, the selected model/profile and supported
Structured response output, with no executable tools.
The Session-selected semantic label is resolved against current Agent options
and current local capability evidence for every new judgment, including judgments
hosted by an existing Run. A previously resolved foreground model snapshot is not
the Judge's model authority. No separate Judge model snapshot or configuration is
persisted. Current metadata changes and same-label model replacements therefore
apply without reselecting or resaving a model.

Within one judgment, a call-local candidate chain uses the shared model-operation
selector and background health policy. Active cooldown and recovery/probe-pending
candidates are skipped without claiming a foreground probe. Quota/billing failure
updates shared health and advances through that chain; other classified provider
failures use the shared bounded retry budget and backoff on the same candidate.
Malformed output, capability/preparation failures and chain exhaustion settle as
failed judgment rather than inventing another fallback category. Cancellation
propagates without settlement. No foreground or compaction operation slot, Session
inference snapshot or ordinary Run retry state is replaced by Judge progression.
Owner fencing is rechecked before physical dispatch and candidate-health updates.

Judge input includes an explicit timezone-aware current time normalized to UTC,
alongside each candidate's objective, source evidence, last recorded execution
start time, latest result and next-check hint. The instruction first evaluates
when another check is called for: an unelapsed requested interval means no action
unless the objective or new input warrants an earlier check. `act` selects whether
to start investigation, not whether to notify the user. A due check does not
require an already-known finding; notification is decided after work. These are
model instructions, not a deterministic per-Routine scheduling gate.

Each considered ID may
occur once and must belong to the captured set. Missing, foreign or duplicate
identities, invalid/incomplete native output and unavailable saved capability
produce failure evidence, never synthetic no-action success. A failed check waits
for a later source tick. Client credentials and endpoint defaults are transport
configuration, not semantic Structured request controls.

## Independent Work and Completion

Selected work captures original objective, source events, latest prior work and
an admitted execution identity. Later definition edits cannot rewrite that
objective. The initial input carries full selected contexts. Ordinary tools,
including Runtime tools, execute in the normal Run. Continuation selects the
oldest incomplete occurrence, supplies its full context and references remaining
identities; `read_routine_context` reads only admitted identities in the authorized
Session.

Compaction preserves all started, unfinished Routine occurrences in the exact
Session, including work associated with earlier Runs. Each entry contains its
immutable objective, source/prior context and occurrence identity in deterministic
order. Registered future definitions, unstarted admissions and terminal work are
not added. This read-only snapshot does not rebind a host Run or grant context,
completion or idle-continuation authority for another Run's work.

`record_routine_result` requires the admitted, started, current-owner identity.
Its input is flat: `slug`, `execution_id`, `objective_outcome` (`finished` or
`failed`), nonblank `result` and `next_hint`, independent `notify`, nullable
`message`, and nullable `files`. The tool does not accept a nested `work` object.
A notifying result requires a nonblank message and may attach up to 20 files
using absolute Runtime paths or authorized `exchange://` references. Silent
results require both message and files to be null. Completion atomically
closes only that item and retains its canonical record. Repeating completion
returns the existing stored work without another notification. The newest 100
records per definition are retained. Judgment continuity uses latest work only.
Late completion after deletion may finish admitted work but cannot recreate a
definition or retained records.

## Notification and Primary Channel

Primary is a nullable channel Binding reference on the originating Session. It
is distinct from the Agent's Team Primary Session. Channel-created Sessions set
the originating Binding as Primary in the owning transaction. Web-only Sessions
have none. A Primary must belong to the same Session, Agent and Workspace.
Disconnect, termination and owner cleanup remove obsolete delivery authority
without imposing one Binding per Session.

At completion, notification resolves the current authorized Primary. No Primary
means delivery to the originating Session chat. An existing but unavailable,
replaced or failed Primary does not fall back to another Session/channel. Delivery
is a post-commit, one-attempt effect with separate observation; uncertain or failed
publication is not an automatic retry queue. Objective outcome, record success
and delivery status remain distinct. Files are prepared with existing Runtime
transfer/Exchange authority before completion, outside database transactions.
Runtime sources are first published as verified Exchange objects for both
destinations; external uploads consume those authorized immutable sources rather
than holding a Runtime transfer open through provider completion.
Preparation failure leaves work incomplete. File-bearing delivery is pinned to
the observed Primary (including its absence) and rejects a destination change.
Channel notifications use existing outbound file manifests; Session chat
notifications retain Exchange attachments in their durable notification event.
Repeated completion does not prepare or send files again.
Backfill preserves all existing Bindings:
zero eligible connections means no Primary, one unambiguous connection selects it,
and multiple or inconsistent connections block migration for explicit resolution.

## Stop, Archive, Restore and Purge

Explicit Stop closes pending Routine attempts and incomplete work while retaining
definitions and completed results. Ordinary owner recovery reuses existing owner
generation and fences stale callers. Explicit Run retry binds only eligible
incomplete occurrences and preserves the saved model/profile.

Archive removes definitions, retained records, source state and pre-start work.
Only already-started Routine-only work may finish on the archived Session;
unrelated active work blocks archive. Completion must not recreate removed data.
Restore does not recreate definitions, records or source authority. Judgment
history follows ordinary Session event retention. Permanent purge waits for
preserved started work, rechecks owned namespace absence, and then removes the
Session. Team Primary Session archive protection remains unchanged.

## Read-only Inspection and Activity

Both public routes above are GET-only, active-Session-scoped and member-authorized.
List returns definitions from the exact requested Session; detail returns current
definition, latest occurrence and up to 100 retained records. Missing/archived,
foreign or unauthorized targets are unavailable (404), without root, Team Primary
or other-Session fallback. Inspection does not mutate, pause, trigger or configure
Routines and does not expose internal execution-owner identity.

The supporting `?page=routines` panel keeps Chat mounted and provides inventory,
objective/source/occurrence details and collapsed work records. Its compact list
shows titles and objective previews; narrow layouts use a back-icon/title header
and preserve list scroll and focus on return. Pull-to-refresh works from the
scroll top, with a keyboard-accessible refresh icon as an alternative. There are
no management controls. Transcript judgment uses the shared activity-row
disclosure, initially collapsed, with a read-only checked/unchecked/unknown
candidate checklist and compact per-call metadata. It is separate from normal
tool activity, with durable/reloaded considered candidates,
decisions, status, model and per-call usage. Invalid/missing evidence is diagnostic
or unavailable. Routine tool details separate requested inputs from actual
completed output: failed/rejected/cancelled/interrupted calls cannot imply a
successful mutation, and duplicate completion displays canonical stored work.
Routine tool recognition follows the built-in event contract: these auto-bound
calls have no attached Toolkit source snapshot. A source-less reserved Routine
name selects its dedicated card and activity category; an attached foreign or
invalid source does not acquire built-in Routine presentation by reusing a name.

Judgment events and usage do not enter ordinary model input, `ChatMessage.usage`,
ordinary turn usage, normal system-prompt snapshots, Context breakdown, compaction
baseline, normal activity or autoarchive clocks. Admitted work inputs and ordinary
tools retain their normal inference, usage and activity semantics.

## Verification and Authority

The required and Web product journeys above use real tools, Public API, Scheduler,
Worker and Docker Runtime. Internal concurrency, Stop/recovery, migration,
retention, provider and presentation matrices live in the linked repositories,
services, lowerer/engine and component tests. Testenv controls dispatch through the
actual source service and expose only admission/evidence, not manufactured work.

Development authority: [routine-261018/REQ](../../requirements/routine-261018-session-routines.md),
[ADR-D2/D3/D4](../../adr/routine-261018-session-routines.md), and
[Design revision 2](../../design/routine-261018-session-routines.md). M3 remains
retired; judgment uses the ordinary inbox/Run mechanism.

Agent cadence authority: [cadence-261019/REQ](../../requirements/cadence-261019-agent-routine-check-interval.md),
[ADR-D1](../../adr/cadence-261019-agent-routine-check-interval.md), and
[Design revision 1](../../design/cadence-261019-agent-routine-check-interval.md).
