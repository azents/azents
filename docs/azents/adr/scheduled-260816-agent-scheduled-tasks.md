---
title: "Agent Scheduled Tasks"
created: 2026-08-16
tags: [scheduled-task, agent, session, scheduler, toolkit, external-channel, architecture]
document_role: primary
document_type: adr
snapshot_id: scheduled-260816
---

# Agent Scheduled Tasks

- Snapshot: `scheduled-260816`
- Document reference: `scheduled-260816/ADR`
- Requirements: [Agent Scheduled Tasks Requirements](../requirements/scheduled-260816-agent-scheduled-tasks.md) (`scheduled-260816/REQ`)
- Decision mode: Collaborative
- Decision owner: requester

## Decision Map

- [x] `scheduled-260816/ADR-D1` — Extend the existing Scheduler role to claim user-defined Task occurrences from PostgreSQL.
- [x] `scheduled-260816/ADR-D2` — Admit due occurrences through a typed wake-session Mailbox item in existing FIFO order.
- [x] `scheduled-260816/ADR-D3` — Keep active Scheduled Task work cycles in Session-scoped Toolkit State and continue them through the idle lifecycle.
- [x] `scheduled-260816/ADR-D4` — Keep Task and owning-lifecycle deletion independent from an already-started work cycle and AgentRun.
- [x] `scheduled-260816/ADR-D5` — Commit the canonical Session result before one-attempt provider effects.
- [x] `scheduled-260816/ADR-D6` — Keep Scheduled Task provider progress state distinct from Channel Work.
- [x] `scheduled-260816/ADR-D7` — Package tools and the creation Skill in one automatically connected ScheduledToolkit.

## Context

The current periodic Scheduler owns code-registered maintenance work. Its registry and `scheduled_task_states` rows cannot represent user-defined schedules, Session targets, natural-language objectives, External Channel targets, or product lifecycle operations. The current Job Runtime is local and bounded; Temporal is a reserved but unimplemented backend.

Agent execution already has durable Session Mailbox admission, payload-free wake signals, owner-generation fencing, AgentRun recovery, idle continuation hooks, and Session-scoped Toolkit State with optimistic concurrency. External Channel delivery already resolves opaque channel handles to authorized Bindings and owns provider-native delivery and presentation primitives.

The confirmed Requirements add user-defined one-time and recurring Tasks without introducing another Session identity, Task history, pause state, revision token, or durable provider-delivery retry system. The design must therefore introduce one durable user-schedule authority while preserving existing Session execution, External Channel authority, and lifecycle boundaries.

## Decisions

### scheduled-260816/ADR-D1: Durable scheduling and due-claim authority

**Affected requirements:** `scheduled-260816/REQ-1`, `REQ-4`, `REQ-13`, `REQ-14`, `REQ-15`

Persist each user-defined Scheduled Task and its current scheduling cursor in a new
PostgreSQL product table. This table is the durable authority for definition,
next eligibility, claim fencing, missed-occurrence coalescing, one active cycle,
and at most one pending occurrence.

Extend the existing dedicated Scheduler role with one code-registered dispatcher
definition. Each dispatcher pass claims bounded due product rows through expiring
database leases and performs only the durable occurrence-admission handoff. The
dispatcher does not execute the Agent objective or wait for the complete work
cycle. Agent execution remains owned by the existing AgentWorker and Session
lifecycle.

The existing `scheduled_task_states` table remains exclusively the current-state
store for code-registered system maintenance tasks. User Task definitions and
per-Task scheduling state do not enter that table or the code-owned task-definition
registry.

The exact column grouping, indexes, batch size, lease duration, and polling
interval are Design details as long as PostgreSQL remains the single scheduling
authority and every claim preserves the confirmed missed and overlapping
occurrence behavior.

**Rejected alternatives:**

- A separate Scheduled Task dispatcher deployment was rejected because it would
  duplicate polling, lease, retry, health, and operational surfaces without a
  distinct product authority.
- Temporal or another external durable scheduler was rejected because the current
  Temporal backend is unimplemented and an external per-Task schedule would create
  a second lifecycle authority beside PostgreSQL.
- Process-local timers or Job Runtime handles were rejected because they cannot
  recover durable user schedules after process loss.

### scheduled-260816/ADR-D2: Due-occurrence Session admission, ordering, and recovery

**Affected requirements:** `scheduled-260816/REQ-5`, `REQ-6`, `REQ-13`, `REQ-14`

Admit each newly claimed occurrence through one dedicated typed
`scheduled_task_trigger` Mailbox item with `wake_session` scheduling. Use the
existing Session FIFO without priority insertion or preemption.

The dispatcher commits the following durable handoff atomically:

- snapshot the Task title, objective, canonical schedule, and `scheduled_for`
  instant into the new active work-cycle Toolkit State;
- insert one idempotent trigger Mailbox item for that work cycle;
- advance the Task scheduling cursor and record the active-cycle fence; and
- preserve the confirmed one-pending-occurrence coalescing state.

Only after commit does the dispatcher send the ordinary payload-free Session wake
signal. If the signal is lost, the pending Mailbox item remains the recoverable
source of truth. If the Session already has a Run or earlier Mailbox input, the
Scheduled Task waits behind that work in existing FIFO order. The due instant is
eligibility time, not authority to reorder or interrupt preceding Session work.

The atomic commit is the recovery ownership handoff. Before it, the Scheduler may
reclaim or retry the occurrence under its database lease. After it, the Scheduler
does not create another trigger for that cycle; Mailbox, Session owner-generation,
AgentRun recovery, and idle continuation own execution recovery.

**Rejected alternatives:**

- Priority Mailbox admission was rejected because it would reorder Scheduled Task
  input ahead of earlier human or system input and introduce a second Session
  scheduling policy.
- Direct AgentRun creation by the Scheduler was rejected because it bypasses
  durable Mailbox admission, FIFO ordering, owner-generation fencing, and existing
  recovery.
- `queue_only` admission was rejected because a due Task must wake an idle Session
  without waiting for unrelated later input.

### scheduled-260816/ADR-D3: Store active work cycles in Session-scoped Toolkit State

**Affected requirements:** `scheduled-260816/REQ-6`, `REQ-7`, `REQ-8`, `REQ-13`, `REQ-14`, `REQ-15`

Store the current Scheduled Task work cycle as domain-specific Session-scoped Toolkit State owned by the Scheduled Toolkit. Use a distinct Scheduled Task namespace and state identity rather than generalizing or reusing Channel Work state.

The work-cycle state contains only current execution and continuation data needed until the cycle terminalizes. It is schema-versioned and updated through optimistic concurrency. It is not Task history and its internal storage version is not exposed as a Task revision.

The Scheduled Toolkit participates in the existing Session idle-hook lifecycle while the work cycle remains active. Each continuation creates a fresh AgentRun through the normal Session continuation boundary. The cycle ends only through `submit_scheduled_task_result`. An owning lifecycle may remove an admitted cycle before its first AgentRun begins, but it does not stop or remove a started cycle.

**Rejected alternatives:**

- A new AgentSession per occurrence was rejected because recurring work must preserve the selected Session context.
- Channel Work state was rejected as canonical Scheduled Task state because the two domains have independent ownership, lifecycle, terminal actions, and provider presentation.
- A transcript-only marker was rejected because the current active cycle requires fenced mutable continuation state rather than replay-derived state.

### scheduled-260816/ADR-D4: Keep deletion independent from started work

**Affected requirements:** `scheduled-260816/REQ-6`, `REQ-14`, `REQ-15`

Task deletion, Session archive, Binding termination, and an already-started work
cycle are independent lifecycle events. The start boundary is the beginning of the
occurrence's AgentRun execution.

Before that boundary, Task or owning-lifecycle deletion removes the Task definition,
due or pending scheduling state, trigger Mailbox input, and work-cycle state. After
that boundary, deletion removes the Task definition and every future or coalesced
occurrence but does not request AgentRun stop, disable continuation, remove the
active work-cycle state, or suppress terminal result processing.

The started work cycle continues from its admitted immutable snapshot of title,
objective, schedule, `scheduled_for`, Session, and optional Binding. Its terminal
path must tolerate the Task row already being absent. A deleted recurring Task is
not recreated after the independent work cycle terminalizes.

Session archive retains its archived product state while allowing only internal
continuations for cycles that started before archive. Binding termination revokes
provider publication authority and may clean up the existing Tracker, but it does
not stop the Run or cycle. The terminal result still commits to the target Session;
provider effects through a disconnected Binding are unavailable and never retarget.

**Rejected alternatives:**

- Stopping the active AgentRun on Task deletion, Session archive, or Binding
  termination was rejected because deletion does not cancel work that has already
  started.
- Abandoning the work cycle after its current Run was rejected because it could
  discard the terminal result while retaining external side effects.
- Retaining a deleted Task row until the work cycle ends was rejected because it
  would violate hard-delete semantics and make Task deletion depend on execution
  completion.

### scheduled-260816/ADR-D5: Terminal result and provider-effect boundary

**Affected requirements:** `scheduled-260816/REQ-7`, `REQ-8`, `REQ-10`, `REQ-11`, `REQ-12`, `REQ-14`

`submit_scheduled_task_result` first commits the canonical Scheduled Task outcome
inside PostgreSQL. One transaction validates the current work-cycle authority,
appends a dedicated typed Scheduled Task result event to the target Session,
commits the `finished` or `failed` outcome, removes the completed Toolkit State,
deletes a one-time Task when it still exists, and advances any surviving recurring
Task from its active-cycle fence to future or coalesced-pending eligibility.

The result event is the durable conversational result. It renders as Agent output
in the Session and participates in later model context so the user can continue
from it. Terminalization uses the work-cycle definition snapshot and succeeds when
the Task row was independently deleted after AgentRun execution began. It also
succeeds when the Session was archived or the selected Binding was disconnected
after the cycle started. An archived Session retains the result; a disconnected
Binding yields unavailable provider effects without suppressing the Session result.

Only after the canonical transaction commits does the terminal action publish the
Session event to live clients and attempt channel-bound terminal effects. It makes
one immediate ordered provider-publication attempt, records no provider delivery
authority in the Task product, and attempts Activity Tracker deletion after the
publication effects regardless of delivered, failed, or unknown outcomes. The tool
returns the immediate provider outcomes to the Agent.

A process or provider failure after canonical commit does not reopen the cycle,
recreate a deleted Task, or create durable delivery, cleanup, compensation, or
replay work. Session persistence therefore remains authoritative even when
provider presentation is missing or ambiguous.

**Rejected alternatives:**

- Relying on a later ordinary assistant message was rejected because the terminal
  tool result, durable cycle state, and user-visible Session result could diverge
  or the additional message could be omitted.
- Publishing to the provider before database commit was rejected because external
  side effects cannot be rolled back when terminal persistence fails and could be
  duplicated by recovery.
- A transactional outbox or durable provider retry state was rejected because the
  confirmed product uses immediate one-attempt presentation rather than a durable
  delivery authority.

### scheduled-260816/ADR-D6: Keep provider progress state distinct from Channel Work

**Affected requirements:** `scheduled-260816/REQ-10`, `REQ-11`, `REQ-12`, `REQ-15`

Scheduled Task registration presentation, Activity Tracker state, ordered progress, and terminal cleanup remain Scheduled Task-owned state. They do not replace, share, or reinterpret canonical Channel Work Toolkit State even when both use the same Binding.

The implementation may reuse lower-level External Channel authorization, provider-client, rendering, file-transfer, message-splitting, and delivery primitives. Provider-native parent surfacing remains derived from the exact bound conversation and does not create a second destination.

**Rejected alternatives:**

- Reusing Channel Work state was rejected because ordinary Channel Work and multiple Scheduled Task cycles can coexist independently on one Binding.
- A generic shared Work product model was rejected because it would merge distinct terminal, continuation, cleanup, and lifecycle contracts without product authority.

### scheduled-260816/ADR-D7: Use one automatically connected ScheduledToolkit

**Affected requirements:** `scheduled-260816/REQ-2`, `REQ-6`, `REQ-7`, `REQ-17`

Provide Scheduled Task management tools, active-cycle behavior, terminal action, idle hooks, and the creation Skill through one automatically connected built-in `ScheduledToolkit`. It requires no user-created ToolkitConfig, credentials, or attachment.

The Skill is a Toolkit-owned release VFS package rather than a global Skill. Its canonical package is rooted under the Scheduled Toolkit release resources and is projected under the Toolkit namespace. The same Toolkit owns `add_scheduled_task`, `list_scheduled_tasks`, `delete_scheduled_task`, and the cycle-only `submit_scheduled_task_result` tool.

**Rejected alternatives:**

- A global Scheduled Task Skill was rejected because Skill availability must follow the capability that owns the tools.
- A user-configured Toolkit was rejected because Scheduled Tasks are a built-in Agent capability with no credentials or optional connection lifecycle.
- Separate management and execution Toolkits were rejected because they would split one product lifecycle and Skill trigger across independent capability owners.

## Consequences

- PostgreSQL is the only durable scheduling and canonical terminal-result
  authority.
- The existing Scheduler deployment gains one bounded user-Task dispatcher while
  Agent execution remains in AgentWorker.
- Due work enters Sessions through durable FIFO Mailbox admission and existing
  recovery.
- Active work-cycle state remains domain-specific Session Toolkit State.
- Task deletion and owning lifecycle transitions stop future scheduling without
  interrupting already-started work.
- Channel progress state remains independent from ordinary Channel Work.
- Scheduled Task tools and Skill ship together through the auto-bound
  ScheduledToolkit.
- Provider publication and Tracker cleanup remain immediate, non-authoritative,
  and non-replayed effects after canonical terminal commit.
