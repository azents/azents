---
title: "Agent Scheduled Tasks Requirements"
created: 2026-08-16
updated: 2026-08-16
tags: [scheduled-task, agent, session, external-channel, skill, slack, discord]
document_role: primary
document_type: requirements
snapshot_id: scheduled-260816
---

# Agent Scheduled Tasks Requirements

- Snapshot: `scheduled-260816`
- Document reference: `scheduled-260816/REQ`

## Problem

Users cannot currently ask an Agent to continue goal-oriented work at an exact future time or on a recurring schedule. This gap applies both to Azents Sessions and to connected External Channel conversations through which users already invoke Agents, observe progress, and receive results.

## Primary Actor

A human participant interacting with an Agent in an existing conversation.

## Primary Scenario

A participant asks an Agent in an existing conversation to perform goal-oriented work at an exact future time or on a recurring schedule. The Agent registers the Scheduled Task for the current Session and optionally selects one connected External Channel conversation, defaulting to the source conversation when the request originated from one. When the schedule becomes due, the Agent works autonomously in the same Session across as many Agent runs as necessary until it explicitly submits a finished or failed result. The result is rendered in the Session and, for a channel-bound task, published with provider-native progress and terminal presentation in the selected conversation.

## Supporting Scenarios

- A user asks an Agent in an ordinary Azents Session to add, list, delete, or replace a Session-only Scheduled Task.
- A participant manages a shared parent-channel Scheduled Task from a connected Slack or Discord channel conversation.
- A participant manages a topic-specific Scheduled Task from an exact connected Slack or Discord thread.
- A Slack or Discord participant starts from the existing message shortcut or Message Command and completes the existing Agent-selection, access, and conversation-location flow before asking the selected Agent to add a task.
- A user creates, inspects, edits, or deletes the same Scheduled Task product object through a dedicated UI.
- Through the dedicated UI, a user creates or selects a dedicated persistent Session when no existing conversation context should be reused.

## Goals

- Let an Agent add, list, and delete precise one-time and recurring scheduled work from conversation.
- Make Scheduled Task tools and creation guidance available to Agents without separate Toolkit setup or configuration.
- Let users directly create and manage the same Scheduled Task product object through a dedicated UI.
- Preserve the selected Session's accumulated context across recurring work cycles.
- Keep each scheduled work cycle active across Agent runs until the Agent explicitly submits a terminal result.
- Make Slack and Discord first-class Scheduled Task registration, progress, and result surfaces.
- Preserve provider-native parent-channel and exact-thread expectations.
- Provide predictable behavior for invalid schedules, missed schedules, overlapping work, failure, deletion during active work, Session archive, and Binding disconnect.
- Remove Task-owned data when a Task or terminal work cycle no longer needs to exist.

## Non-Goals

- Letting Scheduled Task tools create a separate persistent AgentSession or select another Session.
- Creating a new AgentSession for every recurring occurrence.
- Broadcasting one Scheduled Task to arbitrary multiple External Channel Bindings.
- Treating thread-to-parent terminal surfacing as a second selectable Binding or destination.
- Changing existing Slack or Discord Agent selection, access approval, conversation setup, response-mode admission, or Binding lifecycle policy.
- Pausing or resuming a Scheduled Task.
- Cancelling the current work cycle while preserving its Scheduled Task.
- Providing Agent management tools for get, update, pause, resume, rerun, or cancel operations.
- Retaining a deleted Task as a soft-deleted record or tombstone.
- Retaining terminal work-cycle history in the Scheduled Task product.
- Retaining a one-time Task after its work cycle finishes or fails.
- Rerunning a terminal one-time Task without registering a new Task.
- Introducing Task-level or work-cycle-level unread state in addition to Session read state.
- Guaranteeing provider delivery through a new durable delivery queue, replay loop, or compensation process.
- Automatically undoing provider side effects after Task deletion, Session archive,
  Binding disconnect, or work-cycle failure.
- Automatically restoring a Task after its Session or Binding is restored or reconnected.

## Requirements

### REQ-1. Scheduled Task definition

A Scheduled Task must contain the user-defined work and one canonical execution target needed to run it predictably.

**Acceptance criteria**

- Each Task has one immutable 32-character lowercase UUID7 hexadecimal identifier.
- Each Task has a short editable `title` used in management and provider registration presentation.
- Each Task has one editable plain-text `objective` describing the goal, completion conditions, and expected result.
- A Task has no separate completion-criteria field.
- System-owned trigger, continuation, and terminal-action instructions are not stored in the objective.
- Each Task targets exactly one AgentSession.
- A Task is either Session-only or coupled to exactly one active External Channel Binding owned by the same Session and Agent.
- Agent creation expresses the optional channel target through a nullable `channel_id`.
- A non-null `channel_id` is the same opaque channel handle accepted by `channel_action.binding` and is passed unchanged.
- Provider, channel, and thread identities are resolved from the Binding rather than duplicated as independent Task destinations.
- Originating and dedicated Sessions use the same persisted target behavior; their distinction belongs to the creation flow.
- A Task has no revision or user-visible version token.

### REQ-2. Agent management tools

An Agent must manage Scheduled Tasks through a minimal, exact, fail-closed tool surface bound to its current Session.

**Acceptance criteria**

- The Agent management tools are exactly `add_scheduled_task`, `list_scheduled_tasks`, and `delete_scheduled_task`.
- The Scheduled Task tool surface and its creation Skill are available through an automatically connected built-in capability and require no user-managed Toolkit configuration.
- All three tools are automatically scoped to the Agent's current Session.
- The Agent does not supply a Session identifier.
- Only `add_scheduled_task` accepts `channel_id`.
- `add_scheduled_task` accepts the title, objective, canonical schedule, and required nullable `channel_id`.
- A null `channel_id` creates a Session-only Task.
- A non-null `channel_id` must be the same opaque channel handle that the Agent would pass to `channel_action.binding`; the Agent passes it unchanged.
- The service resolves a non-null `channel_id` to one active Binding owned by the current Session and Agent and rejects an unavailable, disconnected, unauthorized, or wrong-Session channel.
- `list_scheduled_tasks` accepts no input and returns every persisted Task owned by the current Session with its complete definition and current execution state.
- `delete_scheduled_task` accepts only the exact Task identifier and deletes only a Task owned by the current Session.
- A malformed, stale, deleted, inaccessible, or wrong-Session identifier causes no mutation.
- The product never falls back to a title, slug, prefix, fuzzy match, or another Task when identifier lookup fails.
- After a failed lookup, the Agent can list the current Session's Tasks before retrying.
- When a user asks the Agent to modify a Task, the Agent lists the current Tasks, deletes the existing Task, and adds a replacement with a new identifier.
- Scheduled Task tools cannot create another persistent AgentSession or select a different Session.

### REQ-3. Dedicated UI management

Users must be able to create and directly manage the same Scheduled Task product objects through a dedicated UI.

**Acceptance criteria**

- The UI can create, inspect, edit, and permanently delete a persisted Task.
- The UI can create or select a dedicated persistent Session for a new Task.
- The UI permits only Sessions and optional Bindings the current user is authorized to access.
- Edits affect only future work that has not started.
- The UI does not expose Pause, Resume, Cancel-current-cycle, or Rerun actions.
- The UI does not maintain a second conversational transcript or terminal work-cycle history.

### REQ-4. Canonical schedule forms and validation

A Scheduled Task must use one exact schedule form appropriate to whether it runs once or repeatedly.

**Acceptance criteria**

- A one-time Task uses one RFC 3339 `at` timestamp.
- The timestamp must include `Z` or an explicit UTC offset; a timezone-less timestamp is rejected.
- A new one-time Task whose `at` is earlier than its registration time is rejected.
- A recurring Task uses one standard five-field, minute-granularity cron expression and one IANA timezone identifier.
- Seconds and year fields are rejected.
- A one-time schedule accepts only `at`; a recurring schedule accepts only its cron expression and timezone.
- Invalid schedule field combinations are rejected at runtime.
- Agent intelligence and UI assistance may translate natural-language requests into the canonical forms without creating additional canonical schedule types.
- The past-time registration rule does not prevent recovery of a previously valid one-time Task that became overdue while scheduling service was unavailable.

### REQ-5. Session context and authority

Scheduled execution must preserve the selected Session's context and authority without creating an alternative execution identity.

**Acceptance criteria**

- An Agent-created Task always uses the Agent's current originating Session.
- A channel-bound Agent-created Task uses a selected active Binding that belongs to the current Session and Agent.
- A dedicated Session can be created or selected only through the dedicated UI.
- Recurring work cycles reuse the same selected Session rather than creating a new Session per occurrence.
- Execution uses the target Session's current Agent, Workspace, tools, root tree, and ownership authority.
- Scheduled execution cannot elevate permissions beyond the target Session and optional Binding.
- Creator and provider-principal identities are provenance rather than separate creator-only access-control boundaries.
- Users authorized to use and manage a shared target Session can jointly manage its Tasks.

### REQ-6. Scheduled work-cycle trigger and continuation

A due schedule must activate one goal-oriented work cycle that remains active until the Agent explicitly submits a terminal result.

**Acceptance criteria**

- Completing one Agent run does not implicitly complete the work cycle.
- The continuation mechanism can start further Agent runs while the work cycle remains active.
- Every initial and continuation Agent run receives one self-contained Scheduled Task runtime message.
- The runtime message includes the title, objective, complete canonical schedule, and the current cycle's canonical `scheduled_for` instant.
- A recurring runtime message includes the five-field cron expression and IANA timezone so the Agent understands its recurrence frequency and timezone.
- A one-time runtime message includes the canonical `at` timestamp.
- The runtime message does not include Task, work-cycle, Session, or Binding identifiers, prior terminal results, or internal scheduler state.
- The runtime message tells the Agent that ending one Agent run does not end the cycle and that it must work autonomously until terminal.
- A work cycle does not wait for new user input.
- After reasonable autonomous attempts, work that cannot proceed without missing user information, a user choice, authority, or another unavailable prerequisite terminates as failed.
- A failed result explains the blocking reason and what must be provided or changed before another Task is registered.
- Scheduled-cycle-specific behavioral guidance is shown only while a Scheduled Task work cycle is active rather than duplicated into always-visible tool descriptions.

### REQ-7. Terminal result action

An active Scheduled Task work cycle must expose one concise execution-only action that explicitly commits its terminal outcome.

**Acceptance criteria**

- The action is named `submit_scheduled_task_result`.
- The action is bound to the current active work cycle and accepts no Task, work-cycle, Session, or Binding identifier.
- Its input contains `status`, which accepts only `finished` or `failed`, and a required non-empty `result`.
- `finished` means the objective was achieved.
- `failed` means the objective could not be achieved after reasonable autonomous attempts.
- The action commits the terminal status and result and ends the continuation lifecycle.
- The action's always-visible tool description remains concise; active-cycle runtime guidance owns the detailed completion, blocked-work, and channel-publication instructions.

### REQ-8. Session result presentation and data retention

Every terminal result must become part of the target Session while Task-owned terminal history is not retained.

**Acceptance criteria**

- Work-cycle progress and the terminal result are rendered in the target Session.
- The user can continue the conversation from the rendered result.
- Existing Session read and unread behavior identifies newly available results.
- The Scheduled Task product retains no terminal work-cycle history.
- After terminal result processing, the completed work-cycle state is removed.
- A one-time Task is permanently deleted after either a finished or failed result.
- A recurring Task remains registered after its current cycle state is removed.
- The Session and any successfully published provider messages remain independently owned records and are not retroactively deleted with the Task.

### REQ-9. Existing External Channel prerequisites and scope

A channel-bound Scheduled Task must use one conversation already authorized and established by the existing External Channel flow.

**Acceptance criteria**

- Single App, Multi App, Agent selection, restricted-access approval, and Channel-or-Threads setup retain their current behavior.
- No channel-bound Task is created before the existing flow establishes its Session and active Binding.
- Existing Slack and Discord message shortcuts or Message Commands can provide the source conversation from which the user asks the Agent to add a Task.
- When a creation request originates from an External Channel conversation, the Agent uses that source conversation's opaque channel handle by default.
- When the user explicitly requests another connected conversation, that requested conversation overrides the source default without changing the current Session.
- When a creation request does not target an External Channel conversation, the Agent supplies a null `channel_id`.
- The Agent does not silently substitute the source conversation, another conversation, or a Session-only target when an explicitly requested conversation is unavailable.
- Existing `mention_only` and `all_messages` rules determine how later human management requests reach the Agent; scheduled execution itself requires no provider mention.
- A parent-channel Task remains coupled to its parent-channel Binding.
- An exact-thread Task remains coupled to its exact-thread Binding.
- Slack Channel location uses the parent conversation, while Slack Threads location uses the exact bound root or thread conversation.
- A Discord parent channel and each Discord Thread remain independent conversations and Bindings.
- A Task never broadcasts automatically to every Binding connected to its Session.

### REQ-10. Channel-bound registration presentation

Creating a channel-bound Scheduled Task must immediately present the registered Task in its exact provider conversation with direct management controls.

**Acceptance criteria**

- Successful Task persistence causes one immediate provider-native rich registration-message attempt in the bound parent channel or exact thread.
- The message identifies the Task and its canonical schedule.
- The message exposes Edit and Delete controls.
- Edit and Delete reload the current Task and revalidate the current actor, Session, Binding, and authorization before mutation.
- The controls do not use or expose a revision token.
- A stale control for a deleted or inaccessible Task causes no mutation and reports that the Task is unavailable.
- The registration message is separate from the Activity Tracker created when a work cycle starts.
- Provider failure does not roll back the persisted Task and does not create durable delivery or replay work.

### REQ-11. Provider-native Activity Tracker and progress

Each channel-bound Scheduled Task work cycle must own an independent provider-native Activity Tracker and progress lifecycle.

**Acceptance criteria**

- The bound parent channel or exact thread receives one immediate Activity Tracker attempt when the work cycle starts.
- A Scheduled Task Tracker does not replace or share canonical state with ordinary Channel Work or another Scheduled Task Tracker on the same Binding.
- Slack uses its current Block Kit progress presentation conventions.
- Discord uses its current compact Embed progress presentation conventions.
- The Agent can publish interim messages, files, title changes, and ordered Plan updates through the existing channel progress action while the cycle remains active.
- During a Scheduled Task cycle, channel progress actions cannot terminalize or silently finish the Scheduled Task work cycle.
- The active-cycle runtime message tells the Agent to use channel actions only for interim progress and to use `submit_scheduled_task_result` for the terminal result.
- Initial Tracker delivery failure does not deactivate the work cycle and does not create durable replay work.
- A terminal result makes one immediate publication attempt through the existing authorized provider boundary.
- The terminal action reports the immediate ordered provider outcomes to the Agent.
- After terminal publication effects are attempted, the product makes one immediate best-effort Tracker deletion attempt regardless of whether terminal publication was delivered, failed, or unknown.
- Tracker cleanup failure does not reopen the terminal work cycle and does not create durable retry or replay work.
- A Session-only Task renders progress and its terminal result only in the Session UI.

### REQ-12. Exact-thread terminal surfacing

Every exact-thread Scheduled Task terminal result must also be visible in its provider parent channel without changing the Task's one-Binding ownership.

**Acceptance criteria**

- Activity Tracker and interim progress remain only in the exact thread.
- Every finished or failed terminal result remains in the exact thread and is additionally surfaced to the parent channel.
- Slack uses native thread `reply_broadcast` behavior for each terminal message part.
- Discord first creates each terminal message part in the exact Thread and then uses native message forwarding for each part.
- When provider limits split a result into multiple ordered parts, every part is surfaced in the same order.
- Split parts are neither omitted nor replaced by a separately generated summary.
- A parent-channel Task does not create an additional duplicate parent-channel publication.
- Parent-channel surfacing is derived from the exact-thread Binding rather than another configurable destination.

### REQ-13. Missed and overlapping occurrences

The product must recover missed schedules and serialize overlapping occurrences without replaying an unbounded backlog.

**Acceptance criteria**

- A previously valid one-time Task missed during scheduler unavailability becomes eligible for one execution after recovery.
- Multiple missed cron occurrences coalesce into one immediate work cycle after recovery.
- After the coalesced cycle, the recurring Task follows its next future cron occurrence.
- A Task has at most one active work cycle.
- Cron occurrences that become due while that Task's cycle is active coalesce into at most one pending occurrence.
- After the active cycle terminalizes, the pending occurrence starts once and the Task then follows its next future cron occurrence.
- Pending occurrence state is not retained as terminal history.

### REQ-14. Failure and deletion lifecycle

Scheduled Task failure and deletion must stop Task-owned future work while keeping an already-started work cycle independent from deletion of its Task definition.

**Acceptance criteria**

- Every persisted Task is active; the product has no paused, completed, failed, cancelled, or deleted Task record.
- Infrastructure failure before Agent work begins may be retried while preserving one logical occurrence.
- After Agent work has begun, a failed terminal result does not automatically rerun that occurrence.
- A failed one-time Task is deleted after its result is committed; another attempt requires a newly registered Task with a new identifier and schedule.
- A failed recurring cycle does not deactivate its Task; the next eligible cron occurrence remains available.
- Permanently deleting a Task removes its definition, future eligibility, coalesced pending occurrence, and any admitted occurrence whose AgentRun has not begun execution.
- Once an occurrence's AgentRun has begun execution, that work cycle is independent from later deletion of the Task definition.
- Deleting the Task does not request AgentRun interruption, stop the started work cycle's continuations, disable its terminal action, or suppress its result.
- A started work cycle continues to either a finished or failed terminal result using its admitted definition snapshot.
- Deleting a recurring Task while a work cycle is running prevents every later occurrence; completion of the already-started cycle does not recreate the Task.
- The product exposes no separate action that interrupts the current work cycle while preserving its Task.
- A deleted Task is absent from Agent tools, the dedicated UI, and future scheduling.
- A deleted Task leaves no soft-deleted record or tombstone.
- Results already rendered in the Session or published to a provider are not retroactively deleted.

### REQ-15. Owning lifecycle boundaries

A Scheduled Task must be removed when the Session or strongly coupled Binding that owns its execution is removed.

**Acceptance criteria**

- Archiving the target Session removes its Scheduled Tasks, future and pending occurrences, and every admitted occurrence whose AgentRun has not begun execution.
- Session archive does not request interruption of an already-started AgentRun or stop its Scheduled Task work-cycle continuations.
- A work cycle started before Session archive retains its current work state, continues from its admitted snapshot, and can submit its finished or failed result to the archived Session.
- While such a cycle remains active, the archived Session accepts only the internal Scheduled Task continuations required to terminalize that already-started cycle; archive does not reopen ordinary user or new Task execution.
- Restoring the Session does not restore its removed Tasks.
- Explicitly disconnecting a Task's Binding removes the Task, future and pending occurrences, and every admitted occurrence whose AgentRun has not begun execution.
- Binding disconnect does not request interruption of an already-started AgentRun, remove its current work state, stop its continuations, disable its terminal action, or suppress its Session result.
- A cycle started before Binding disconnect continues from its admitted snapshot, but subsequent provider publication through the disconnected Binding is unavailable and never falls back to another Binding or Session-only publication behavior.
- A removed channel-bound Task is not moved to another Binding or converted to a Session-only Task.
- Reconnecting the provider conversation does not restore the removed Task.
- Connection disconnect, route removal, or provider App uninstall removes Tasks whose Bindings are terminalized by the existing lifecycle transition.
- Transient provider or transport degradation is not a Binding disconnect and does not remove the Task.

### REQ-16. Management and current execution visibility

Users must be able to inspect persisted Tasks and navigate to their canonical Session without creating a second result history.

**Acceptance criteria**

- The dedicated UI shows every authorized persisted Task's title, objective, schedule, target Session, optional bound provider conversation, derived current execution state, and future eligibility.
- The UI distinguishes parent-channel and exact-thread targets.
- The UI shows current work-cycle progress when a Task is active.
- The UI provides navigation from a persisted Task or current work cycle to the target Session.
- The UI does not show terminal work-cycle history.
- Terminal results remain available through the target Session and any successfully published provider conversation.
- Existing provider-to-Session navigation and conversation settings remain available.
- The Session remains the canonical conversational result surface.

### REQ-17. Agent creation guidance

The Agent must use built-in Scheduled Task guidance to translate user requests into actionable Tasks without unnecessary questioning or provider-specific branching.

**Acceptance criteria**

- The Scheduled Task creation Skill is distributed with the automatically connected Scheduled Task capability.
- The Skill applies to explicit creation requests, explanation requests, and List, Delete, or replacement management requests.
- The Skill always uses the current AgentSession and never asks for or selects another persistent Session.
- For an External Channel creation request, the Skill defaults `channel_id` to the exact opaque handle associated with the requesting message.
- The Skill uses the same unchanged opaque value for `add_scheduled_task.channel_id` that it would use for `channel_action.binding`.
- For an ordinary Session creation request, the Skill supplies a null `channel_id`.
- An explicit request for another connected conversation overrides the source-channel default when the model-visible context maps the request reliably to exactly one available handle.
- When multiple channel conversations are present, the Skill identifies the origin of the specific scheduling request rather than choosing the first or most recently active handle.
- The Skill asks one focused clarification or reports the target as unavailable when an explicitly requested channel cannot be identified reliably.
- The Skill never falls back to another channel or a Session-only Task after channel validation fails.
- For duration-relative timing such as one hour from now, the Skill derives the future instant without asking for the user's timezone.
- For calendar-time or recurring requests, the Skill uses an explicitly stated timezone first, otherwise uses a timezone reliably inferred from user or conversation context, and asks only when the timezone remains unknown.
- The Skill produces a timezone-bearing RFC 3339 timestamp for one-time work or a standard five-field cron expression with an IANA timezone for recurring work.
- The Skill determines whether the objective contains enough context to identify the work, completion conditions, and expected result.
- The Skill asks only for missing information that would materially change execution or make the objective impossible to complete.
- The Skill derives a concise title in the user's language when the user does not provide one.
- The Skill calls `add_scheduled_task` only after the target, objective, title, and canonical schedule are sufficiently defined and reports the actual tool outcome.
- Explanation-only requests do not create a Task.
- The Skill uses provider-neutral External Channel, channel handle, and conversation-scope concepts; provider-specific presentation remains owned by the existing External Channel implementation.

### REQ-18. Compaction continuity for active work

Active Scheduled Task work must remain explicit in compacted Session context so the
Agent can continue the same work cycle without losing its objective or terminal
responsibility.

**Acceptance criteria**

- When Session context is compacted while one or more started nonterminal work cycles
  exist, the resulting compaction summary includes every current Scheduled Task work
  cycle.
- The compacted work snapshot includes the title, objective, complete canonical
  schedule, current cycle's `scheduled_for` instant, and current provider-neutral
  progress when present.
- The compacted work snapshot reminds the Agent that the work cycle remains active
  until it submits a finished or failed result through the terminal action.
- An admitted occurrence whose first Agent run has not started is not included as
  active work.
- A terminalized work cycle is not included.
- Every started work cycle remains eligible for compaction continuity after its Task
  definition is deleted or its owning Session or Binding lifecycle changes.
- The compacted snapshot exposes no Task, work-cycle, Session, Binding, provider
  identity, lease, credential, internal scheduler state, or prior terminal result.
- Compaction reads current work without creating, changing, reactivating, or
  terminalizing a work cycle.

## Fixed Constraints

- Current Living Specs and current source code describe existing behavior only; historical Scheduled Task documents do not define this snapshot's product intent.
- Existing Slack and Discord Agent selection, access, Channel-or-Threads setup, response-mode admission, provider formatting, and Binding lifecycle remain authoritative for their current behavior.
- Existing Session ownership, authorization, AgentRun, continuation, Mailbox, and Workspace boundaries remain authoritative unless this snapshot explicitly changes an observable outcome.
- Scheduled Task tools and creation guidance are available through one automatically connected built-in capability with no user-managed Toolkit configuration.
- Normal External Channel Agent output is not automatically relayed; channel-bound Scheduled Task progress and terminal publication use the authorized provider publication boundary explicitly described above.
- Slack exact-thread terminal publication uses native `reply_broadcast`; Discord exact-thread terminal publication uses native message forwarding.
- Provider presentation follows the existing immediate-outcome model and introduces no durable delivery queue or automatic replay contract.
- Sender, provider principal, and creator identities are provenance; execution authority comes from the target Session and optional current Binding.
- Session archive is the user-facing Session deletion boundary.

## Open Assumptions

- Discord provider permissions remain authoritative when a Scheduled Task publication needs to unarchive an archived Thread; a locked or unauthorized Thread reports the existing immediate provider outcome.
- Operational limits such as maximum Tasks per Session, objective length, title length, and minimum cron frequency may be introduced only when repository feasibility or abuse controls require them; they must not change the confirmed product scenarios or lifecycle.

## Confirmation

REQ-1 through REQ-17 were confirmed by the requester on 2026-08-16 before ADR and
Design work began. REQ-18 was confirmed by the requester on 2026-08-16 through an
explicit implementation-scope addition while the unimplemented design was being
shipped.
