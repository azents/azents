---
title: "Subagent hierarchy and coordination"
created: 2026-11-04
tags: [wiki]
---

# Subagent hierarchy and coordination

Owns the SessionAgent tree, model inheritance, collaboration tools, capacity, waiting and direct-parent result delivery. A subagent is a participant linked to an execution Session, not another persistent Agent configuration.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Conversations and events](../domain/conversation.md)
- [Model selection and operation snapshots](../models/selection.md)
- [Session mailbox and input admission](mailbox.md)
- [Agent execution](../flow/agent-execution-loop.md)
- [Toolkits](../domain/toolkit.md)

## SessionAgent hierarchy and mutation boundaries

`rdb/models/session_agent.py` stores the live participant tree for one root session. A root
`AgentSession` has one root `SessionAgent` with path `/root`. `spawn_agent` creates child or nested
`SessionAgent` rows with `kind = subagent`, a linked hidden `AgentSession` whose `session_kind` is
`subagent`, and the same workspace and Agent boundary as the parent session. Spawn request validation,
profile derivation, child participant/session/run creation, selected context append, and initial
mailbox input commit atomically. Invalid target labels, unsupported explicit effort, full-history
profile overrides, invalid fork selections, or incomplete parent run provenance leave no child
participant, session, run, activity event, or broker wake-up.

| Field                                                    | Type                    | Notes                                                                                                                               |
| -------------------------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `id`                                                     | `str(32)`               | SessionAgent ID                                                                                                                     |
| `context_id`                                             | FK                      | Root-tree context shared by all participants in the tree                                                                            |
| `root_session_agent_id`                                  | FK self                 | Root participant for this tree                                                                                                      |
| `agent_session_id`                                       | FK `agent_sessions`     | One-to-one linked transcript/execution session                                                                                      |
| `kind`                                                   | enum                    | `root` or `subagent`                                                                                                                |
| `name`                                                   | string                  | Tree-local name segment. Child names must start with a letter or number and contain only letters, numbers, underscores, or hyphens. |
| `path`                                                   | text                    | Canonical absolute path under `/root`                                                                                               |
| `agent_type`                                             | string                  | Spawned agent type snapshot. Current supported value is `default`.                                                                  |
| `parent_session_agent_id`                                | FK self \| null         | Parent participant; null only for the root participant                                                                              |
| `last_task_message`                                      | text \| null            | Latest delegated task/message preview                                                                                               |
| `parent_observed_run_index` / `parent_observed_event_id` | int / `str(32)` \| null | Monotonic cursor advanced only when a terminal `agent_result` is promoted into the direct parent's durable transcript.              |

The tree enforces unique `(root_session_agent_id, path)` and `(parent_session_agent_id, name)`. The
repository resolves absolute paths such as `/root/reviewer` and current-agent-relative child paths.
It never resolves across root trees. Ordinary agent session list APIs filter to `session_kind = root`,
so child sessions stay hidden from the Agent rail while remaining directly readable through authorized
history, live, and detail routes.

The complete tree remains the authority for canonical agent targeting, historical
child reuse, terminal-result delivery, observation cursors, and the public
Subagent Tree. The model-facing `list_agents` result is a separate bounded,
read-only coordination projection: omission from that result neither removes a
participant nor prevents path-based targeting of its existing Session.

Tree/path/coordination descriptions are ordinary reads, including validation of
captured owner identity. Spawn and follow-up capacity are actual root-hierarchy
claims; send and interrupt admit only the exact source/target Session rows.
Mutation admission acquires the required Session rows in stable order with
ordinary waiting locks, then fences the captured source owner generation through
the dependent write commit. A database-confirmed deadlock or serialization abort
releases the complete owning DB operation before reopening and revalidating its
original owner and inputs. The finite recovery closure covers both a parent
mutation and child terminal delivery as possible victims, retaining one atomic
terminal disposition/mailbox winner without replaying execution or notification.
Cancellation, stale authority and uncertain commit propagate without replay.

Actual Stop/archive/restore/purge admission shares the hierarchy boundary with
child creation and admits the complete current tree before applying the
transition. Owner handover advances only the exact claimed Session generation;
ordinary Session reads do not lock root, parent or Agent rows. Idle eligibility
is an independent pre-hook view, while final continuation admission and matching
idle-boundary consumption remain one exact owner-fenced transaction. Pending
Run activation, terminal state and one disposition plus idempotent parent
mailbox admission retain their existing atomic winning-claim semantics.

## Execution-loop scheduling and parent delivery

Subagent runs use the same worker, broker, `AgentSession`, and `AgentRunExecution` path as root runs.
Before resolving tools, the worker reads the selected session. If `agent_sessions.session_kind = subagent`,
toolkit resolution uses subagent execution mode; otherwise it uses root execution mode. Subagent mode
excludes root/user-facing auto-bound capabilities such as Memory Write and Goal Toolkit
while keeping the subagent collaboration toolkit available.

Subagent collaboration tools communicate through resolved agent input buffers:

- `spawn_agent` first enforces the Agent's active subagent and depth limits while holding a root
  `SessionAgent` row lock for the tree. It fails with a tool error instead of queueing when the root
  tree already has `subagent_settings.max_subagents` active subagents or the requested child would
  exceed `subagent_settings.max_depth`. If allowed, it creates
  a child `SessionAgent` plus hidden child `AgentSession` and a model-independent first pending run carrying only the parent run id. Without a profile override it copies the exact current parent Session inference state into the child Session, regardless of whether that inherited Agent option allows explicit subagent selection. For `fork_turns = none` or a positive bounded count, optional `model_target_label` and `reasoning_effort` fields may instead resolve and store a complete Agent-owned override state on the child Session. An explicit target resolves only among options whose `settings.subagent_enabled` is true; unknown and disabled labels fail identically before side effects. An effort-only override retains the inherited parent target. Full-history `all` forks reject either override. Target-only changes normalize effort from the parent resolved effort; explicit efforts validate exactly. Label, effort, fork, and parent-state validation happens before child records or wake-up side effects. The first-run activation persists the selected requested label and nullable effort on the pending child run without copying resolved physical selection or limits into that row. The tool description uses the same enabled-option set, lists labels and explicit effort levels, renders optional bounded `subagent_guidance`, and does not project disabled labels or physical model and integration metadata. If the set is empty, the description advertises inheritance only. The spawn flow then forks the parent's selected model-visible
  context, appends that selected context to the child transcript, appends a
  `system_reminder` event rendered as a `<system-reminder>` boundary when any parent history
  was copied, writes an initial `agent_message`, marks the child running, and sends a broker
  wake-up. The caller may still
  explicitly select no context or a bounded number of recent turns through `fork_turns`. The
  boundary reminder is inserted immediately after copied parent history for `fork_turns=all` or a
  positive integer selection. It identifies the child by name and full path, marks preceding messages
  as inherited parent context, and states that `wait` observes the child's current mailbox plus
  descendants rather than another selected agent.
- Agent references resolve against the complete durable root tree, independently
  of model-facing list membership. `list_agents` performs one bounded PostgreSQL
  projection for the caller's root tree. It always includes the root and every
  child whose Session is running, latest Run is pending or running, or mailbox has
  pending `wake_session` input. Those required-visible children may exceed
  `subagent_settings.max_subagents` after a capacity reduction. Any remaining
  slots up to the configured child capacity are filled by inactive recency using
  `SessionAgent.last_message_at`, with creation time and canonical path as
  deterministic fallbacks. The result emits only canonical `agent_name` and
  `agent_status` fields. Omitted inactive children remain targetable by canonical
  path and reusable in their existing Session.
- `send_message` writes an `agent_message` to any resolved agent, including the root, without waking it.
- `followup_task` writes an `agent_message`, marks the target running, and sends a broker wake-up,
  but rejects the root as a target. It holds the root-tree lock while evaluating active capacity.
  Assigning more work to an already-active target is allowed at capacity; activating an idle target
  is rejected when the root tree already has `subagent_settings.max_subagents` active children.
- `wait` accepts only optional `timeout_seconds` from 0 through 900 seconds and observes any mailbox
  activity for the current SessionAgent, descendant activity, and ordinary Runner-owned shell
  lifecycle completion. Fire-and-forget commands are excluded. Worker races a cancellable,
  non-consuming `process.observe` long-poll against mailbox signals and descendant reconciliation.
  It prioritizes mailbox activity over shell completion/no-work/timeout outcomes. Cancelling
  observation does not stop execution or delay mailbox handling behind remote cancellation.
  A shell-completion result records the Runtime/generation/revision in generic tool metadata;
  later waits recover that committed position. Waiting never consumes mailbox items or shell
  output, repairs descendant delivery, or acknowledges descendant terminal results itself.
- `interrupt_agent` rejects the root and the caller itself, then records stop intent only for the
  resolved target's current run while holding the root-tree and target-session locks.

`agent_message` lowering renders mailbox payloads as explicit source-labeled envelopes for the target
session. `spawn_agent` and `followup_task` render `Message Type: NEW_TASK`; `send_message` renders
`Message Type: MESSAGE`; terminal results render `Message Type: AGENT_RESULT` with the terminal Run
status. The envelope includes the target path as task name, sender path, and payload text. Terminal
payloads additionally retain source Run identity/index/status and nullable terminal event identity in
durable metadata, while model-visible content uses only the safe terminal projection or fixed status
fallback. Child creation initializes `agent_sessions.applied_inference_profile` and
`inference_state` from the inherited or overridden selection. The first activation copies only that
requested label and nullable effort to the child `AgentRun`. Later `followup_task` runs therefore use
normal Session-applied precedence and re-resolve the saved Agent-owned label against the current
Agent snapshot rather than pinning the first run's physical snapshot. Broker wake-ups remain
payload-free; recovery is based on persisted input buffers and `agent_sessions.run_state`.

Every InputBuffer records producer-owned scheduling intent. User, Goal, action, spawn, and follow-up
input uses `wake_session`; `send_message` and terminal `agent_result` use `queue_only`. The session
runner and locked idle transition consider only pending commands, active Runs, inbox wake-ups, and
`wake_session` rows as follow-up work. A terminal session may therefore become idle while queue-only
mailbox input remains. A later wake-producing input starts one Run and normal FIFO preparation
promotes the older queue-only rows before or with the triggering input.

Mailbox enqueue admits the exact active target `AgentSession` mutation without a
generic root `SessionAgent` gate. Every
mailbox target must still be active; `spawn_agent` and `followup_task` additionally reject a target
whose stop request is already present before they create input or wake side effects.

Normal terminal database finalization composes `TerminalRunFinalizationRepository`
and `AgentMailboxRepository`: exact critical Session authority is fenced before the Run
mutation, and an eligible direct-parent delivery inserts one idempotent queue-only
`agent_result` with activity and Run delivery markers in the same transaction.
Best-effort historical repair uses separate completed
`SubagentTerminalResultRepository` candidate, direct-child, and delivery operations.
Its exact completed-Run disposition and active-target mutation ordering, and
parent-validation failure semantics, remain distinct
from normal finalization's ineligible-parent suppression and User Stop convergence.
Normal terminal handling attempts this side effect before idle evaluation. Parent `wait_agent`
polling repairs eligible results from direct children, and a later Run in the source child session
repairs older eligible terminal results. Delivery failure is logged but does not roll the Run back or
keep the child running.

Input preparation validates every promoted `agent_result` against the actual direct child and terminal
Run metadata before monotonically advancing that child's parent-observation cursor. Cursor update,
event append or deduplication, and buffer deletion share one transaction. After commit, the executor
publishes `subagent_tree_changed` for each advanced child. Merely enqueueing or observing a result in
`wait_agent` leaves it unread.

Human-authored direct writes are root-session only. REST message/edit/command/failed-run retry paths reject `session_kind = subagent` before creating input buffers,
chat write requests, pending commands, operation mutations, live projections, or broker wake-ups.
Subagent mailbox input must be written by another SessionAgent through collaboration tools as
`agent_message` buffers.

User-facing stop is subtree-aware: stopping a root session records stop intent for running linked
descendants, and stopping a child detail session records stop intent for that child subtree.
Model-visible `interrupt_agent` is intentionally narrower and records stop intent only for the named
target agent's current run after rejecting the root and the caller itself.

## Collaboration tools and waiting

`SubagentToolkitProvider` is an auto-bound toolkit resolved by the worker. It is eligible in both root
and subagent execution modes and exposes the coherent collaboration bundle as unprefixed tools:

- `spawn_agent`
- `send_message`
- `followup_task`
- `interrupt_agent`
- `list_agents`

The independent auto-bound `WaitToolkit` exposes the unprefixed `wait` tool in
root and subagent execution modes alongside this collaboration bundle.

`list_agents` is a read-only PostgreSQL projection over the caller's complete root
`SessionAgent` tree. Its exact result is
`{"agents":[{"agent_name":"/root/...","agent_status":"..."}]}`; each item has only
the canonical path in `agent_name` and the projected status in `agent_status`.
The root is always present. Every non-root participant whose linked Session is
running, whose latest Run is pending or running, or whose mailbox has pending
`wake_session` input is required-visible even when those rows exceed the current
`max_subagents` value. Remaining capacity is filled with inactive participants by
descending `last_message_at`, then descending creation time and ascending path.
The emitted rows are ordered with the root first and the selected children by
canonical path. No delegated task or message content is included.

This bounded model-facing projection does not change the durable coordination
authority. Canonical path resolution for message, follow-up, and interrupt
operations still uses the complete tree, and an omitted inactive child can be
woken in its existing Session subject to the ordinary active-capacity check.
Terminal-result delivery, parent observation cursors, and the public Subagent Tree
remain independent and complete.

Historical terminal-result repair loads candidates and direct children through
completed repository reads and commits each eligible parent delivery through a
separate database-only repair operation. Repair logging and outcome counting run
after those operations. Normal terminal finalization and repair share canonical
AgentMailbox database admission and safe result text but retain their distinct
parent-ineligibility and User Stop behavior.

`spawn_agent` currently supports only `agent_type = default`; unsupported values fail as tool errors.
Its `fork_turns` parameter defaults to `all`, so the child starts with the parent's current
model-visible context unless the caller explicitly selects no context or a bounded number of turns.
The dynamic tool description lists only Agent-owned selectable model options whose
`settings.subagent_enabled` is true. Each eligible entry includes its label, explicit reasoning-effort
values, and optional `subagent_guidance`; disabled entries and their guidance are not disclosed. The
same filtered set validates explicit `model_target_label` values. Missing and disabled labels return
the same unavailable-override tool error before durable child creation. Omitting the target label,
including an effort-only override, retains parent-target inheritance even when the inherited option is
disabled. When every option is disabled, the tool advertises inheritance only.
Before creating a child, `spawn_agent` enforces the Agent's `subagent_settings` while holding a
row lock on the root `SessionAgent`, so parallel spawn calls in the same root tree serialize before
capacity is checked. `max_subagents` limits active subagents across the root `SessionAgent` tree; a
subagent counts as active when its linked `AgentSession.run_state` is `running` or its latest run
status is `pending` or `running`. `followup_task` uses the same root-tree lock and capacity snapshot:
assigning more work to an already-active target remains allowed at capacity, while waking an inactive
target that would exceed `max_subagents` fails before input or broker side effects. `max_depth` limits
child creation by depth below `/root`. Limit failures are returned as clear tool errors and do not
queue the requested task.

Subagent policy and tree reads use completed repository operations. Spawn loads a
detached policy, parent Run, parent Session, and fork-history snapshot for pure
inference/fork projection, then enters one final database-only operation. That
operation revalidates the invoking running Run, locks the root tree, rechecks
depth and capacity, and atomically creates the child SessionAgent and Session,
pending Run, inference state, fork transcript, and initial wake-producing
mailbox item. Message, follow-up, interrupt, and bounded-list operations likewise
finish their database transaction before returning. Broker wake/stop signals,
queue-only mailbox activity notification, and `SubagentTreeChanged` publication
run only after the operation returns.

The static toolkit prompt selects the Codex Multi-Agent V2 root or child usage hint from the current
`SessionAgent.kind`. Both variants append the shared direct-tool-call and shared-workspace hint, the
configured concurrency slot count as `max_subagents + 1`, and the explicit-request-only delegation
policy. Azents changes only provider/runtime terminology, mailbox coordination wording, and the
tool-availability claim: mailbox envelopes are described as model input, `exec_command` replaces
Codex `functions.exec` namespaces, `wait` observes current-agent mailbox activity and descendant
idleness, and child execution is described as lacking Azents root/user-facing capabilities. Maximum
depth remains a runtime spawn constraint and is not included in the prompt. When parent history is
forked, the boundary reminder identifies the child by name and full path, distinguishes inherited
parent actions from the child's own actions, and explains that `wait` observes only that child's
descendants and current mailbox rather than the child itself.

The toolkit stores inter-agent delivery as target-session `agent_message` input buffers through the
typed mailbox service. `send_message` uses `queue_only` scheduling and does not wake or mark the target
running. `spawn_agent` and `followup_task` use `wake_session`, mark the target running, and send normal
payload-free broker wake-up signals. A terminal child Run is delivered to its persisted direct parent
as one queue-only `agent_result`; terminal content is the user-safe Run projection or a fixed status
fallback, never internal exception or provider diagnostic text. Mailbox writes require the target
`AgentSession` to remain active; wake-producing writes also require that no stop has
already been requested. Capacity-changing spawn and follow-up admission use the
root-hierarchy claim. Single-target `send_message` and `interrupt_agent` instead
admit their exact source/target Session rows in stable order, without that root
claim, then fence the captured source owner generation through commit. See
[`SubagentToolOperationsRepository`](../../../../python/apps/azents/src/azents/repos/subagent_tool_operations.py).
Terminal delivery and tree lifecycle transitions retain the winning-claim and
current-tree admission boundaries defined under
[SessionAgent hierarchy and mutation boundaries](#sessionagent-hierarchy-and-mutation-boundaries);
ordinary mailbox operations do not inherit a blanket root-tree lock.

`wait` has only optional `timeout_seconds`, defaulting to 30 and bounded from 0 through 900; unknown
fields are rejected. It observes any mailbox activity, active descendant paths in the current
SessionAgent subtree, and ordinary shell-process completion without consuming input or output.
A mailbox update returns
`{"outcome":"activity","reason":"new user input, agent or subagent message, scheduled continuation,
external-channel request, or action"}`. When no ordinary shell work participates, an empty tree
returns `{"outcome":"not_waitable","reason":"no_descendants"}`, an entirely idle subtree returns `{"outcome":"not_waitable",
"reason":"all_descendants_idle"}`, and deadline expiry returns `{"outcome":"timed_out"}`. Active
means a running Session, a pending/running Run, or pending `wake_session` input; queue-only input
alone does not make a descendant active. `timeout_seconds = 0` performs one immediate observation.
Waiting never repairs descendant terminal delivery, consumes mailbox rows, or advances descendant
observation cursors; the next model boundary performs FIFO promotion.

Shell-only work is eligible without descendants. A cancellable, non-consuming Runner
`process.observe` long-poll returns new terminal lifecycle states promptly without waiting for
other commands or stdout chunks. `wait` returns `outcome=activity`, `reason=shell_completion`,
and a `completed` list of process identifiers/statuses. Output and exit-code collection remain
with `write_stdin`. Fire-and-forget commands are excluded from eligibility and wake-ups.
The completed tool result stores the Runtime ID, Runner generation, and lifecycle revision
in generic metadata. Subsequent waits recover the latest committed revision from retained
Session transcript events, including compacted events; returning a Runner response alone
does not acknowledge it. New input takes precedence over simultaneous shell completion.
Cancelling observation or timing out does not terminate shell processes, and remote
cancellation cleanup does not hold mailbox handling. No automatic completion input or new Run
is created. Missing Runtime projection means no participating shell work; a failed observation
operation is surfaced as a tool error rather than being interpreted as no work.

`interrupt_agent` records stop intent only for the named target session and returns its previous
projected status; it does not close, delete, or recursively stop descendants. The toolkit emits
non-durable `subagent_tree_changed` invalidations for durable tree changes. Terminal unread state
clears only after validated `agent_result` promotion advances the direct child's observation cursor;
`wait` observation by itself does not acknowledge the result.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/subagent_tool_operations.py`](../../../../python/apps/azents/src/azents/repos/subagent_tool_operations.py)
- [`python/apps/azents/src/azents/rdb/models/session_agent.py`](../../../../python/apps/azents/src/azents/rdb/models/session_agent.py)
- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
