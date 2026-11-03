---
title: "Goals and Session Todos"
created: 2026-11-04
tags: [wiki]
---

# Goals and Session Todos

Owns explicitly requested long-running objectives and the independently displayed Todo list. Neither represents a scheduled occurrence, a Routine’s usefulness judgment or Channel Work completion.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Session Routines](../domain/routine.md)
- [Scheduled Tasks](../domain/scheduled-task.md)
- [Agent execution](../flow/agent-execution-loop.md)
- [Toolkit State and execution binding](../execution/tool-state.md)
- [Toolkits](../domain/toolkit.md)

Goal is a session-scoped objective tracked across multiple turns of one `AgentSession`. A Goal is
created only when the user explicitly asks to set a longer-running objective or when system
instructions explicitly require one. The runtime must not create a Goal merely because a task is
large or long-running.

## State Model

Goal state is stored in `toolkit_states` at session scope.

- toolkit namespace: `goal`
- state name: `goal`
- schema version: `1`

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `objective` | `string | null` | User-provided objective text |
| `status` | `active | paused | blocked | complete | null` | Goal lifecycle state |
| `created_at` | `string | null` | Creation timestamp |
| `updated_at` | `string | null` | Update timestamp |

`objective` is user-provided data, not a higher-priority instruction than system or developer
instructions. The model must not redefine or shrink the Goal into an easier objective.

Status meanings:

- `active`: the Goal is eligible for automatic idle continuation.
- `paused`: the user explicitly paused automatic continuation.
- `blocked`: the agent determined it cannot make meaningful progress because the same blocking
  condition persists.
- `complete`: the Goal is finished.

### State and execution mutation boundary

Goal payload load, create, clear, objective and status changes are private Session
Toolkit State operations. They use existing version CAS without a generic root,
Agent or ancestor owner lock. The resolved Toolkit still binds one immutable
execution identity. Actual Goal completion briefing Event publication verifies
that the captured owner Session matches the target, then holds the exact Session
owner-generation mutation fence through Event commit. An obsolete Worker cannot
append current transcript output; ordinary Goal descriptions never inherit that
critical Event fence. Public requester mutations explicitly use their existing
non-execution authority rather than inventing a Worker owner.

## Tool Contract

Goal Toolkit exposes these unprefixed tools in turns that have session context:

- `get_goal`: read the current session Goal.
- `create_goal`: create a new Goal when no unfinished Goal exists.
- `update_goal`: mark the active Goal `complete` or `blocked`.

The exposed Goal tool set is fixed across empty, active, blocked, paused, and complete state. Goal state changes must not add or remove model-visible Goal tools.

Creation and update rules:

- Creating a new Goal is rejected while an unfinished Goal (`active`, `paused`, or `blocked`) exists.
- Marking a Goal `complete` requires evidence that the objective is actually complete.
- Marking a Goal `blocked` is allowed only when the agent cannot make meaningful progress.

The Goal composer TurnAction is registered through the shared closed TurnAction
capability policy. It remains composer-visible, requires a non-empty objective of
at most 4,000 characters, rejects attachments, and requires an inference profile
at public admission. Preparation is Goal-owned: it updates Goal state and emits
the canonical `goal_updated` event followed by the normal user message. An empty
objective or unfinished existing Goal becomes the deterministic handled
`system_error` outcome rather than an operation execution.

UI-only edit/delete/pause/resume mutations go through the public Chat API session Goal mutation. They
update `toolkit_states`; they are not model tools. UI/API can move a Goal between `active` and
`paused`, can resume a `blocked` Goal to `active`, and can provide an optional `resume_hint`.
`resume_hint` is user-provided context data only. UI/API cannot directly set `blocked`; only the
agent/model tool can mark an active Goal blocked.

## Idle Continuation

Goal continuation is produced through the general session idle lifecycle.

The required order is:

1. A foreground run reaches a terminal `RunComplete` boundary and the durable run status is
   `completed`.
2. That terminalization atomically stores the Run ID in
   `AgentSession.pending_idle_continuation_run_id`. Other terminal statuses do not create this
   pointer.
3. The runner confirms there is no pending command, wake-producing mailbox item, queued actionable
   wake-up, or active Run. Starting an actionable replacement Run clears an earlier pointer because
   that earlier boundary did not remain idle.
4. The runner resolves current session hook providers and dispatches `on_session_idle` with the
   stored Run ID.
5. Goal Toolkit returns continuation input only when the current Goal has `status == active` and a
   non-empty `objective`.
6. One transaction rechecks the durable idle conditions, conditionally consumes the matching pointer,
   and either inserts typed `goal_continuation` mailbox envelopes plus `running` state or commits
   `idle` state when no hook returns continuation input.
7. Continuation mailbox envelopes use deterministic Run/provider/ordinal idempotency keys. The worker
   publishes newly created typed pending mailbox state and sends a broker wake-up signal after
   commit.

`paused`, `blocked`, `complete`, or empty Goal state returns no continuation. If the latest terminal
run status is `failed`, `stopped`, `interrupted`, or `cancelled`, idle continuation is skipped even
though the session may still transition to `idle`. If retry is active, the run remains `running` and
the idle continuation path is not reached. If any pending mailbox item already exists when the idle
hook boundary is reached, idle continuation is deferred so existing user or system input runs first.

Hook providers do not write durable transcript events and do not send broker wake-ups directly. They
return `SessionContinuationInput`; the worker converts it into session-bound mailbox envelopes. Broker
wake-up is only a signal. The recoverable source of truth is the pending idle-continuation pointer
until its atomic outcome commits, then the pending mailbox envelope plus the same-transaction `running`
state transition.

A broker wake-up with no pending mailbox item still starts a turn when the transcript tail after the
latest run marker contains an actionable direct control event, including `goal_updated`. A wake-up
with neither pending mailbox item nor an actionable transcript tail is ignored.

## Goal Control Events

Goal control events are not user-authored chat messages. The UI must not expose them as editable or
deletable user bubbles.

`goal_continuation` is the dedicated durable event kind for Goal idle-hook
continuation input. Other idle-hook providers use their own mailbox and event
kinds.

Event shape:

- kind: `goal_continuation`
- source: promoted from a `goal_continuation` mailbox envelope
- payload shape: `UserMessagePayload`
- content: continuation input content returned by the idle hook
- attachments: empty list

Metadata:

  - `source=goal`
  - `provider_slug=goal`
  - `goal_objective=<Goal objective snapshot>`
  - `goal_status=<Goal status snapshot>`
  - `goal_created_at=<Goal created_at snapshot>`
  - `goal_updated_at=<Goal updated_at snapshot>`

`goal_updated` event:

- kind: `goal_updated`
- source: appended directly by the public Goal mutation service
- payload shape: `UserMessagePayload`
- content: empty string
- attachments: empty list
- metadata:
  - `source=goal`
  - `provider_slug=goal`
  - `goal_objective=<Goal objective after mutation>`
  - `goal_status=<Goal status after mutation>`
  - `goal_created_at=<Goal created_at after mutation>`
  - `goal_updated_at=<Goal updated_at after mutation>`
  - `goal_control_action=resume` for resume events only
  - `previous_goal_status=paused|blocked` for resume events only
  - `resume_hint=<user-provided resume hint>` only when a resume hint exists

`goal_updated` is appended when the user edits an active Goal objective or resumes a `paused` or
`blocked` Goal to `active`. It wakes the session after append so the next run can see the update.
Pausing an active Goal does not create a wake-up event. Agent/model tools cannot edit the objective
or pause/resume a Goal; they can only mark an active Goal `complete` or `blocked`.

`goal_briefing` event:

- kind: `goal_briefing`
- payload shape: `GoalBriefingPayload`
- `objective`: completed Goal objective
- `created_at`: Goal creation timestamp
- `completed_at`: Goal completion timestamp
- `duration_seconds`: elapsed seconds from creation to completion, or `null` when unavailable

`goal_briefing` is appended immediately after Goal Toolkit handles `update_goal(status="complete")`.
It is UI-only and is not lowered into model input.

Forbidden behavior:

- Do not append `goal_continuation` directly from the idle hook.
- Do not store `goal_continuation` in any runtime-bound mailbox item.
- Do not render `goal_continuation` or `goal_updated` as user-authored chat bubbles.

## Prompt Rendering Boundary

Goal control prompts are not stored as frontend-only copy or WebSocket-only payloads. The runtime
stores normalized state and metadata, then materializes model-visible prompt prose at lowering time.

The Goal Toolkit prompt itself is fixed instruction text. It does not include the current Goal
objective or status. A model that needs exact current state must call `get_goal`; active-goal idle
continuation carries the objective through continuation metadata instead of duplicating it in the
Toolkit prompt. During compaction, Goal Toolkit appends a readable `Goal Snapshot` to the summary
only when Goal state is unfinished and non-empty. Empty or completed Goal state does not render a
Goal snapshot section.

Lowering rules:

- `EventKind.GOAL_CONTINUATION` always lowers as a user-role compatible reminder
  to keep pursuing the active session Goal.
- The continuation prompt includes the Goal objective and treats continuation content as internal
  control input, not as a new user message.
- `EventKind.GOAL_UPDATED` lowers as a reminder that the active Goal was updated by the user.
- If `goal_updated` metadata has `goal_control_action=resume`, the lowerer renders a `goal_resumed`
  reminder containing `goal_objective`, `previous_goal_status`, and optional `resume_hint`.
- A resume hint is user-provided context, not a higher-priority instruction. If the previous status
  was `blocked`, the model must re-check the current state instead of assuming the blocker is gone.
- Goal reminders use the common `<system_reminder>` envelope with fixed `<instruction>` and `<data>`
  children. User-provided values appear only as `<data><item ...>...</item></data>` entries.
- `EventKind.GOAL_BRIEFING` is UI-only and is not lowered into model input.

## UI Projection

Chat UI renders Goal state and Goal control events separately.

Goal state:

- `/chat/v1/sessions/{session_id}/live` and REST write snapshots expose the `goal` field.
- The input preview keeps the existing Todo-tab design.
- Active Goals do not show a status badge in preview.
- `paused` and `blocked` Goals show preview status badges.
- The detail sheet/card status badge must not truncate.
- Active Goal detail exposes a user `Pause` action with confirmation.
- Paused and blocked Goal detail expose a user `Resume` action with confirmation and optional resume
  hint input.
- Goal edit/delete/pause/resume buttons must call the real API mutation; they must not remain
  disabled placeholders.

Goal continuation/update:

- Do not display raw prompt prose.
- Do not display as a user-authored message.
- Pending state uses the typed Goal continuation projection with common reduced emphasis; any delete
  affordance follows existing mailbox mutation authorization rather than presentation visibility.
- Goal continuation uses the Goal label and target icon. External Channel
  continuation is a separate event and presentation contract owned by the
  External Channel domain.

Goal briefing:

- Render durable `goal_briefing` events as cards.
- The card shows the completed Goal, elapsed time from Goal creation to completion, and completion
  timestamp.

## Verification

Primary checks:

- `cd python/apps/azents && uv run pytest src/azents/engine/tools/goal_test.py`
- `cd python/apps/azents && uv run pytest src/azents/engine/events/pydantic_ai_lowering_test.py`
- `cd python/apps/azents && uv run pytest src/azents/engine/hooks/dispatcher_test.py`
- `cd python/apps/azents && uv run pytest src/azents/services/mailbox_test.py`
- `cd python/apps/azents && uv run pytest src/azents/worker/session/idle_continuation_test.py`
- `cd python/apps/azents && uv run pytest src/azents/api/public/chat/v1/chat_api_test.py`
- `cd python/apps/azents && uv run pyright`
- `cd typescript && pnpm run lint --filter=@azents/web`
- `cd typescript && pnpm run typecheck --filter=@azents/web`

## Session Todo state

TodoToolkit stores todo list as session-scope Toolkit State.

- scope: `session`
- toolkit namespace: `todo`
- state name: `todo`
- schema version: `1`

Payload is `items` array. Each item has `content`, `status`. Status values allowed are only `pending`, `in_progress`, `completed`.

TodoToolkit is always-on toolkit not exposed as user Toolkit config, like shell/builtin, and provides unprefixed `update_todo` tool. Operations:

- `replace`: replace entire list with input item array.
- `clear`: clear entire list.

After `update_todo`, saved snapshot is exposed to UI through chat live state `todo` field and WebSocket `todo_state_changed` event. Todo is not durable transcript event and is not separately injected into compaction input.

## Prompt and result stability

Goal and Todo auto-bound toolkits expose fixed tool definitions independent of current stored state. Their Toolkit prompts are fixed instruction text and do not include the current Goal objective/status or Todo list. The model can call `get_goal` when it needs exact Goal state; Todo UI/state snapshots remain the user-visible source of truth for Todo state. Goal Toolkit is root/user-facing and is filtered out of subagent-mode auto-binding.

`update_todo` persists the new state and publishes `TodoStateChanged`, but returns compact acknowledgement text (`Done`) instead of echoing the full Todo JSON. During compaction, Todo Toolkit appends a readable `Todo Snapshot` to the compaction summary only when the Todo list is non-empty. Goal Toolkit similarly appends a readable `Goal Snapshot` only for unfinished non-empty Goal state.

## Goal Toolkit eligibility

Goal Toolkit is a session-scoped Toolkit State tool that is always auto-bound without user settings. State namespace/name is `goal/goal`; it stores `schema_version`, `objective`, `status`, `created_at`, `updated_at`. Supported statuses are `active`, `paused`, `blocked`, `complete`.

Exposed tools are `get_goal`, `create_goal`, `update_goal`. `create_goal` fails if unfinished Goal already exists. `update_goal` only allows transitioning active Goal to `complete` or `blocked`.

Goal Toolkit registers `on_session_idle` runtime hook. If active Goal exists, it returns continuation input containing Goal objective. Dispatcher merges continuations from multiple providers in provider order and attaches provider slug/index metadata.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/engine/tools/goal.py`](../../../../python/apps/azents/src/azents/engine/tools/goal.py)
- [`python/apps/azents/src/azents/repos/goal/store.py`](../../../../python/apps/azents/src/azents/repos/goal/store.py)
- [`python/apps/azents/src/azents/engine/tools/todo.py`](../../../../python/apps/azents/src/azents/engine/tools/todo.py)
