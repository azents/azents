---
title: "Session Routines Requirements"
created: 2026-10-18
implemented: 2026-10-19
tags: [routine, agent, conversation, toolkit, frontend]
document_role: primary
document_type: requirements
snapshot_id: routine-261018
---

# Session Routines Requirements

- Snapshot: `routine-261018`
- Document reference: `routine-261018/REQ`
- Current-system research baseline: `f045c138934aedb935baa538af93afc4489762d8`.

## Problem

Users must repeatedly ask an Agent to check a subject even after expressing an
ongoing interest. A fixed-output scheduled assignment is not always appropriate:
the Agent may need to decide whether to investigate now and whether the result is
worth interrupting the user. Users also need to inspect what happened when no
notification was necessary, without filling the conversation with background
status reports.

## Primary Context

### Primary Actor

A user who delegates an ongoing check to an Agent in an existing Session.

### Primary Scenario

The user asks the Agent to watch Hacker News for announcement or release-date
rumors and official news about a particular new product. The Agent registers a
Routine with an objective for one execution. At eligible checking opportunities,
the Agent considers the current conversation, candidate input, and the Routine's
latest work record before deciding whether to act. An execution checks for new
information, records its result and next-check guidance, and notifies the user
only when warranted. The user can inspect the Routine and its retained records
without editing them through the UI.

## Supporting Scenarios or Effects

- Periodic traffic investigation that only reports anomalies is a Routine;
  periodic traffic reports that must be produced every time are Scheduled Tasks.
- Several Routines in one Session are considered together rather than letting
  one source's activity monopolize checking opportunities.
- Users can change or delete Routines through the Agent, with explicit effects
  on already-admitted executions.
- Both channel-connected and Web-only Sessions have a defined default result
  destination.

## Goals

- Separate checking eligibility, action selection, execution, and notification.
- Preserve the normal Session context and execution experience.
- Retain concise per-Routine continuity even when no notification is sent.
- Make definitions, work records, and decision calls inspectable with low noise.
- Keep initial source support small while leaving room for future source types.

## Non-Goals

- Email, webhook, or script Event Source implementations in this snapshot.
- Jev integration, configuration, or compatibility validation.
- A dedicated single-Session personal-assistant product.
- Arbitrary notification destinations or a new delivery retry/fallback policy.
- Creating, editing, deleting, pausing, or manually executing Routines through UI.
- A new permissions system, broader authority inferred from delegation, or a
  restriction on ordinary Agent messages/tools beyond their existing contracts.
- Exact scheduled execution guarantees for Routine timing preferences.
- Routine definition versioning or a general-purpose history/versioning system.

## Requirements

### REQ-1. Session-owned Routines and bounded management

A Routine is a continuing item to look after, not an instruction to complete its
entire long-term purpose in one execution.

**Acceptance criteria**

- Every Routine belongs to one Session and has an identifiable title, slug-shaped
  identifier, and objective describing one execution.
- A Session has at most 20 Routine definitions.
- Agent tools support creation, listing, inspection, modification, deletion,
  retrieval of execution context, and completion with work recording.
- The UI is read-only for Routine management.
- Agent tools operate within the existing authorized Session boundary; Routine
  registration does not grant new external-action permissions.

### REQ-2. Routine and Scheduled Task selection

Choose between Routine and Scheduled Task by the requested output obligation,
not merely the presence of a time or interval.

**Acceptance criteria**

- A request for an output at each specified time/interval is a Scheduled Task.
- A request to check at a time/interval and let the model decide whether there
  is an output worth delivering is a Routine.
- "Produce a traffic-analysis report every hour" and "Check traffic every hour
  and tell me if anything is unusual" are taught as Scheduled and Routine
  examples respectively.
- One-off investigation requests are not automatically registered as Routines.
- Routine registration guidance is concise, with useful examples rather than
  the entire feature discussion or a list of unavailable features.
- The product example includes where to look and what new-product news matters;
  it does not establish mandatory fields for every possible user expression.

### REQ-3. Event Sources and proactive checking

A Routine can contain several Event Sources. Sources provide candidate input,
while the model still decides whether action is needed.

**Acceptance criteria**

- Manual is the initial supported source and counts as having an event at every
  eligible Trigger. It requires no manual click.
- Manual does not force action and supports continuing investigations without
  external incoming events.
- Event-driven and Task-driven judgment both fit the Routine concept; neither
  is restricted to only event arrival or only ticks.
- Sources used by Session Routines are associated with that Session.
- Future source extensibility does not expose unimplemented source types as
  currently usable operations.

### REQ-4. Minimum delay and Trigger semantics

The default minimum delay between action decisions is 30 minutes, with a
separate 30-minute tick cadence.

**Acceptance criteria**

- Tick and event arrival initiate an eligibility check. A Trigger means that
  the minimum-delay condition has passed and a checking cycle is admitted.
- When an event arrives at least 30 minutes after the last action decision,
  checking need not wait for the next tick.
- Before that threshold, checking is deferred to the next tick. An early tick
  defers it again rather than adding an exact-threshold timer.
- The reference is the Session's last action decision, not execution completion.
- A no-action decision does not advance that reference.
- A Session without a previous action decision passes the delay check, but
  creating a Routine alone is not an immediate-execution request.
- These rules do not promise non-overlapping work or a 30-minute gap between
  all judgment-model calls.

### REQ-5. Periodic Routine intent

Periodic checking preferences are expressed in the objective and evaluated with
previous work, rather than converted to mandatory-output schedules.

**Acceptance criteria**

- An objective can instruct checking after an hour has elapsed since prior work.
- Tick-time judgment considers that instruction and previous work timing.
- A Routine interval shorter than the tick cadence is unsupported.
- Specifying an interval does not promise exact-time execution or force a
  notification on every execution.

### REQ-6. Session-wide candidate collection

An eligible Trigger considers the Session's entire Routine set, not only the
Routine associated with the source that prompted the check.

**Acceptance criteria**

- Each Session Routine's sources are checked for new events.
- Routines with one or more events are collected for joint model judgment;
  empty-source candidates are excluded. Manual supplies a candidate as defined
  in REQ-3.
- No judgment-model call is necessary when there are no eligible candidates.
- An active, incomplete execution is not selected a second time; its additional
  input is preserved for a later check while other Routines remain eligible.

### REQ-7. Tool-free, context-aware action judgment

Judgment uses the same Session context and conversation history as the ordinary
Agent loop, but cannot perform work through tools.

**Acceptance criteria**

- No callable tools are injected into the judgment operation.
- Checking follows ordinary Session work ordering and its existing cancellation
  and recovery behavior. A busy Session need not run a second concurrent
  execution owner merely to perform judgment.
- Judgment does not require a separate background execution lifecycle. A
  no-action judgment does not require an ordinary assistant-model turn solely
  to announce that outcome.
- The final input supplies candidate Routine context, events, latest work
  records, and the action/no-action decision request.
- Decisions use Structured output rather than free-form text markers.
- Multiple candidate Routines are judged together and actionable Routines can
  be selected without making every candidate execute.
- Replacing the judgment role with another kind of decision model remains a
  future possibility; no Jev-specific support is required now.

### REQ-8. One-execution objectives and ordinary Agent execution

Actionable Routines proceed through the existing Session inbox and normal Agent
execution flow.

**Acceptance criteria**

- Execution input includes the selected Routines' titles, objectives, events,
  and previous work records with an instruction to execute them.
- The objective is stored on the Routine and passed through; the judgment model
  does not generate a new objective for every admission.
- The execution obligation is to perform this occurrence's objective and submit
  its work record, not to finish an indefinite long-term purpose.
- Ordinary tools and execution/stop policies continue to apply.

### REQ-9. Completion and independently chosen notification

Each selected Routine completes by submitting a result and continuity guidance,
regardless of whether it should notify the user.

**Acceptance criteria**

- Completion identifies the Routine by its slug-shaped identifier and submits
  result text, next-action judgment hint text, a notification Boolean, and an
  optional user message in the same presentation format as Channel Action.
- Notification true requires the user message; notification false forbids it.
- The result and hint are recorded even with notification false.
- Prompts request approximately one short, self-contained sentence for each
  text: reading another file or calling a tool must not be necessary to
  understand the recorded context.
- Brevity and self-containment are prompt guidance, not a new character-count
  cap, sentence parser, or reference validator.
- Prompt guidance favors notification only when the user needs to know; routine
  "checked, nothing new" reports are not the intended output.
- Successful recording, successful objective achievement, and successful message
  delivery are distinguishable outcomes.

### REQ-10. Continue only incomplete admitted work

Normal Run completion does not abandon admitted Routines that have no completion
record yet.

**Acceptance criteria**

- A normally completed Run with incomplete admitted Routines continues.
- The first incomplete Routine receives full execution context; the remaining
  incomplete Routines are represented by identifiers only.
- The first item is selected by oldest last execution.
- Agent tools can retrieve another admitted Routine's execution context.
- This does not restrict one Run to only one Routine or change the initial
  admission to identifier-only input.
- Completed Routines are not reintroduced merely to keep the Run continuing.

### REQ-11. Failure and stop behavior

Judgment failures, failed investigations, and user cancellation remain distinct.

**Acceptance criteria**

- A failed judgment request or invalid Structured output is not a no-action
  decision. Input is retained, last action time is unchanged, and failure is
  recorded for another judgment at the next tick rather than immediate looping.
- An execution unable to achieve its objective can submit an honest failure
  result and future hint to terminate this attempt. It is not represented as
  successful investigation and no longer causes incomplete-work continuation.
- User Stop follows the existing policy for other work, ends incomplete current
  attempts as stopped/cancelled, and does not force automatic continuation just
  because a Routine was incomplete.
- Stop does not delete the Routine definition; later normal checking remains
  possible. A stopped attempt cannot permanently block future selection.

### REQ-12. Safe updates and existing executions

Modifying one part of a Routine must not discard unrelated existing content.

**Acceptance criteria**

- Modification requires the existing Routine content exactly as read and the
  intended update as separate inputs.
- Missing or mismatched existing content rejects the update without mutation;
  the Agent must inspect the current content before retrying.
- The change preserves unrelated content. This is an enforced update contract,
  not only a Skill reminder to read first.
- Changed objectives apply to later executions; already-admitted executions
  finish using their original objective/context.
- This does not require a version-number interface or Routine version history.

### REQ-13. Deletion and bounded work records

Users can inspect retained per-execution work records without indefinite growth.

**Acceptance criteria**

- Each Routine retains its most recent 100 work records; older records are removed.
- The next judgment receives the latest work record, not every retained record.
- Deleting a Routine prevents future selection and removes its work records.
- Already-admitted execution may still finish and notify under the existing
  rules. Deletion is not an immediate execution cancellation.
- A late completion for a deleted definition does not recreate permanently
  retained Routine work records.
- These limits do not change ordinary conversation/tool-log retention.

### REQ-14. Session default destination

Each Session has zero or one Primary Channel used for Routine notification.

**Acceptance criteria**

- Notification uses the current Primary at delivery time, or the Session chat
  when none exists.
- Sessions created by Slack/Discord channel invocation designate the originating
  conversation binding as Primary by default.
- Existing channel connections are preserved and assigned Primary semantics
  where compatible with the zero-or-one invariant.
- Routine notification does not accept an arbitrary explicit destination.
- Delivery failure follows the same existing policy as other channel tools;
  no Routine-specific outbox, retry guarantee, or alternative destination is added.

### REQ-15. Read-only Routine inspection

Users can understand registered work and execution records through the Session UI.

**Acceptance criteria**

- Users can inspect the Session's Routine list and a selected Routine's objective,
  current source information, last execution, and retained work records.
- Work results, next-check hints, notification choices, and available notification
  content/outcomes remain distinguishable.
- Empty, loading, unavailable/error, and not-yet-executed states are not confused.
- Mobile inspection supports readable wrapped content and reachable navigation.
- There are no UI mutation or manual-execution controls in this scope.

### REQ-16. Low-emphasis judgment-call history

Session-level judgment calls are inspectable without dominating the conversation.

**Acceptance criteria**

- Calls retain the considered Routines, Structured decision result or failure,
  and available model/usage information as Session judgment history, separate
  from per-Routine execution records.
- The default UI is a very low-emphasis collapsed indication labeled "Routine"
  (Korean localization: "루틴"). Details are initially collapsed.
- The user can expand details to inspect judgment without a large default card
  or a conversational status report.
- No additional free-form decision explanation or private reasoning generation
  is required.
- The 100-record per-Routine limit is not silently applied to this separate
  Session-level history.
- Judgment-call history follows the same retention and Session cleanup policy as
  ordinary conversation history, without an additional Routine-specific count
  limit.
- Judgment-call usage is attributed to that call and remains inspectable in its
  details. Its input differs from ordinary execution because it omits callable
  tools and adds candidate context and judgment instructions.
- Judgment usage does not replace ordinary Run turn usage, the current
  execution-context usage indicator, or the ordinary execution-context
  breakdown. This scope does not introduce a different overall cost-accounting
  policy.

### REQ-17. Routine tool grouping and semantic frontend presentation

Routine tools have a coherent group and readable activity presentation.

**Acceptance criteria**

- Tools are grouped as "Routines" (Korean localization: "루틴"), separate from
  Scheduled Tasks, with a Routine category in existing activity grouping.
- Known calls render action plus Routine title or available slug rather than
  raw function names/JSON as the primary summary.
- Create, list, inspect/context-read, update, delete, and record-result actions
  have localized in-progress, completed, failed, and cancelled presentation.
- Expanded update details distinguish old content, requested change, and actual
  outcome; rejected updates never look successful.
- Expanded completion details distinguish work result, hint, notification choice,
  and available message/delivery outcome. Notification false has no message body.
- Judgment-call indications and actual Routine tool calls are not represented
  as the same operation. Existing activity grouping behavior remains applicable.

### REQ-18. Session archive, restore, and permanent cleanup

Routine archive and restore behavior follows Scheduled Tasks rather than adding
a pause-and-resume product mode.

**Acceptance criteria**

- Archiving a Session removes its Routine definitions, associated retained work
  records, and admitted work that has not started.
- Already-started execution may finish through the same lifecycle exception
  boundary used for Scheduled Tasks. Archive does not admit new Routine
  selections or unrelated new work.
- Late completion does not recreate retained records for removed definitions.
- Restoring the Session does not recreate removed Routine definitions or
  automatically resume them.
- Permanent Session purge waits for preserved started work to finish, removes
  residual Routine state, and verifies that none remains.
- Judgment-call history follows the ordinary conversation-history retention
  and cleanup policy from REQ-16.

## Fixed Constraints

- Product scope and outcomes above are requester-confirmed intent for this
  repository snapshot, including the explicitly bounded gaps below.
- The default tick and minimum action delay are both 30 minutes, but have distinct
  meanings. Shared Session delay must not give only one Routine checking access.
- Respect existing Session ownership, authorization, tool execution, transport,
  cancellation, and lifecycle boundaries. This snapshot grants no new authority
  to disclose across Sessions or invoke external writes.
- Existing Slack/Discord presentation primitives and ordinary Session behavior
  remain applicable. Routine notification does not impose a new exclusive
  publication path or suppress unrelated Agent messages/tools.
- Skill guidance is concise and uses supported behavior. It does not enumerate
  future unimplemented sources as instructions for current use.
- Exact API/DB/schema/claim/queue mechanisms are technical design decisions,
  not established by this Requirements document.

## Open Assumptions and Bounded Gaps

- Existing connected bindings are expected to originate from channel-created
  Sessions, but current schema does not enforce one binding per Session. Migration
  must inspect actual exceptions rather than choose a destination silently.
- Initial no-history ordering and equal-timestamp tie-breaks must preserve the
  oldest-execution intent without inventing user-facing priority controls.
- Supported model paths must be checked for full-context tool-free Structured
  output; this document does not promise capability that providers lack.
- The exact read-only layout is a design proposal. Core inspection, low-emphasis
  judgment history, and localizations are required; component placement and copy
  can be refined without changing these outcomes.

## Confirmation

The requester confirmed this complete repository Requirements translation on
2026-10-18 (KST), including the explicitly bounded gaps above, before ADR decisions
began. This confirms the technical-design input; it does not approve
implementation or claim verified implementation.

The requester additionally confirmed on 2026-10-18 (KST) that judgment-call
history follows ordinary conversation-history retention and Session cleanup,
without a separate count limit. The per-Routine 100-work-record limit is
unchanged.

The requester additionally confirmed on 2026-10-18 (KST) that Session archive
removes Routine definitions, their retained records, and pre-start work;
already-started work may finish under Scheduled-style lifecycle rules; restore
does not recreate definitions; and permanent purge waits for preserved work and
cleans residual state. Recorded in REQ-18.

The requester additionally confirmed on 2026-10-18 (KST) that judgment-call usage
belongs to the judgment call and must not update ordinary Run turn usage or the
current execution-context display because the call inputs differ. Recorded in
REQ-16; no new overall cost-accounting policy was requested.

The requester revised the judgment ownership direction on 2026-10-18 (KST):
checking follows ordinary Session work ordering and execution lifecycle rather
than independent background execution. The requester directly authorized the
corresponding design update and continued implementation without an additional
approval request. Recorded in REQ-7; tool-free Structured output and call-specific
usage isolation remain unchanged.
