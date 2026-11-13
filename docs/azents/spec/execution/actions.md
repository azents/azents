---
title: "Durable Session actions"
created: 2026-11-04
tags: [wiki]
---

# Durable Session actions

Owns admission, progress, terminal results and model continuation for operation-backed Session actions. Project policy and destructive Git ownership live in Projects; this page defines the durable execution envelope.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Session mailbox and input admission](mailbox.md)
- [Projects, working folders and worktrees](../runtime/projects.md)
- [Run recovery](../flow/run-resume.md)
- [Conversations and events](../domain/conversation.md)

## Action admission, execution and continuation

The supported TurnAction set is a closed typed product contract. One service-layer
capability registry owns the policy used by public composer discovery and REST
admission, including visibility, message, attachment, and inference requirements.
The same registry performs detached Goal and Skill preparation and hands
operation-backed actions to Worker execution without changing their persisted
discriminators. Attachment and managed Skill VFS resolution complete before the
final Mailbox transaction. The final database-only promotion operation re-locks
the Session followed by the FIFO head, revalidates owner generation and expected
head identity, revalidates an exact filesystem Skill projection when applicable,
and atomically applies Goal/Skill effects, appends events, creates operation
execution state, associates Run input, acknowledges agent results, and deletes
the source row.
Internal working-folder and Agent-managed worktree actions are executable but are
not public composer definitions.

The legacy setup lifecycle tables are no longer part of the current conversation model. Setup work that affects a session is represented by
operation TurnActions carried through FIFO `action_message` mailbox envelopes, and ordinary sessions have
no separate setup baseline row. An action input remains queue transport rather than becoming a durable
`action_message` transcript event. Goal and Skill actions atomically apply their side effects and
append their canonical model-visible events during preparation. A `create_git_worktree` action is
atomically claimed as an `ActionExecution` before its source mailbox envelope is deleted. A Project-mutating
action that succeeds invalidates the prepared context; the same active `AgentRun` rebuilds its
turn-local request from the updated Session inference snapshot before the next model call. Failed
actions are terminal and do not block later FIFO input.

The Agent-facing `create_git_worktree` and `remove_git_worktree` tools are a closed bridge exception
to that ordinary same-Run invalidation contract. Their handlers enqueue internal
`agent_create_git_worktree` or `agent_remove_git_worktree` action mailbox items under the current
client-tool call identity and return only durable acceptance. The action terminal transaction appends
the ordinary visible `action_execution_result`, enqueues one hidden
`turn_action_continuation` mailbox item keyed by execution ID, and deletes live execution state
atomically. Its bounded continuation payload contains terminal worktree facts but not raw command
output, credentials, or internal exceptions.

`turn_action_continuation` uses `wake_session` scheduling and is omitted from pending human-message
presentation. It may promote only after its recorded predecessor Run is terminal. Promotion
validates a completed same-Session `originating_run_id` as the work source. The
predecessor must be no earlier than that source and either completed or cancelled
without ever starting a model turn. Its accumulated work context is merged with the
origin's context using the same resolver as lifecycle admission. Ordinary idle
continuations still require a completed source. These checks consume existing
valid queued results without rerunning the operation or changing Run status.
Promotion
atomically deletes the mailbox row and appends one invisible `system_reminder` event with a
deterministic external identity, making the turn eligible for inference. The action result remains
the user-visible history authority; the reminder is model input only. Replay exposes either the
pending mailbox row or the promoted event, never duplicate continuation input.

`action_executions` stores live operation TurnAction state keyed by the source
`source_mailbox_item_id` and
includes the typed action payload plus the admitting Session `owner_generation`.
`action_execution_events` stores its ordered live progress records such as step start, command
start/completion, stdout/stderr text, warning, failure, and completion. `GET
/chat/v1/sessions/{session_id}/live` and REST write snapshots expose these active projections.

Completion, failure, or cancellation atomically appends one durable `action_execution_result` snapshot
with deterministic identity `action_execution_result:{execution_id}` and deletes the live execution
and progress rows. Terminal state is therefore owned only by transcript history. A worker takeover
cancels leftover active operations before new work and never replays their potentially completed side
effects. Failed and cancelled actions are not retried or discarded through a separate mutation API.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/session_execution`](../../../../python/apps/azents/src/azents/repos/session_execution)
- [`python/apps/azents/src/azents/worker`](../../../../python/apps/azents/src/azents/worker)
- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
