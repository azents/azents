---
title: "Goal Domain Spec"
created: 2026-06-15
tags: [backend, engine]
spec_type: domain
domain: goal
code_paths:
  - python/apps/azents/src/azents/engine/tools/goal.py
  - python/apps/azents/src/azents/engine/events/litellm_responses.py
  - python/apps/azents/src/azents/engine/events/system_reminders.py
  - python/apps/azents/src/azents/engine/hooks/**
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/worker/session/**
  - python/apps/azents/src/azents/services/input_buffer.py
  - python/apps/azents/src/azents/services/chat/**
  - python/apps/azents/src/azents/api/public/chat/v1/**
  - typescript/apps/azents-web/src/features/chat/**
last_verified_at: 2026-06-29
spec_version: 7
---

# Goal Domain Spec

Goal is a session-scoped objective tracked across multiple turns of one `AgentSession`. A Goal is
created only when the user explicitly asks to set a longer-running objective or when system
instructions explicitly require one. The runtime must not create a Goal merely because a task is
large or long-running.

## 1. State Model

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

## 2. Tool Contract

Goal Toolkit exposes these unprefixed tools in turns that have session context:

- `get_goal`: read the current session Goal.
- `create_goal`: create a new Goal when no unfinished Goal exists.
- `update_goal`: mark the active Goal `complete` or `blocked`.

The exposed Goal tool set is fixed across empty, active, blocked, paused, and complete state. Goal state changes must not add or remove model-visible Goal tools.

Creation and update rules:

- Creating a new Goal is rejected while an unfinished Goal (`active`, `paused`, or `blocked`) exists.
- Marking a Goal `complete` requires evidence that the objective is actually complete.
- Marking a Goal `blocked` is allowed only when the agent cannot make meaningful progress.

UI-only edit/delete/pause/resume mutations go through the public Chat API session Goal mutation. They
update `toolkit_states`; they are not model tools. UI/API can move a Goal between `active` and
`paused`, can resume a `blocked` Goal to `active`, and can provide an optional `resume_hint`.
`resume_hint` is user-provided context data only. UI/API cannot directly set `blocked`; only the
agent/model tool can mark an active Goal blocked.

## 3. Idle Continuation

Goal continuation is produced through the general session idle lifecycle.

The required order is:

1. A foreground run reaches a terminal `RunComplete` boundary.
2. The runner confirms there is no pending command, pending input buffer, or queued actionable
   wake-up.
3. The runner transitions the session runtime to `idle`.
4. The runner dispatches `on_session_idle` hooks over the resolved toolkit bindings.
5. Goal Toolkit returns continuation input only when the current Goal has `status == active` and a
   non-empty `objective`.
6. `IdleContinuationService` enqueues returned continuation input through `InputBufferService`.
7. `InputBufferService` inserts `InputBufferKind.GOAL_CONTINUATION` rows and marks the session
   runtime `running` in the same database transaction.
8. The worker publishes pending input-buffer live state and sends a broker wake-up signal.

`paused`, `blocked`, `complete`, or empty Goal state returns no continuation. If any pending input
buffer already exists when the idle hook boundary is reached, idle continuation is skipped so existing
user or system input runs first.

Hook providers do not write durable transcript events and do not send broker wake-ups directly. They
return `SessionContinuationInput`; the worker converts it into session-bound input buffers. Broker
wake-up is only a signal. The recoverable source of truth is the pending input buffer plus the
same-transaction `running` state transition.

## 4. Goal Control Events

Goal control events are not user-authored chat messages. The UI must not expose them as editable or
deletable user bubbles.

`goal_continuation` event:

- kind: `goal_continuation`
- source: promoted from `InputBufferKind.GOAL_CONTINUATION`
- payload shape: `UserMessagePayload`
- content: continuation input content returned by the idle hook
- attachments: empty list
- metadata:
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
- Do not store `goal_continuation` in any runtime-bound buffer.
- Do not render `goal_continuation` or `goal_updated` as user-authored chat bubbles.

## 5. Prompt Rendering Boundary

Goal control prompts are not stored as frontend-only copy or WebSocket-only payloads. The runtime
stores normalized state and metadata, then materializes model-visible prompt prose at lowering time.

The Goal Toolkit prompt itself is fixed instruction text. It does not include the current Goal
objective or status. A model that needs exact current state must call `get_goal`; active-goal idle
continuation carries the objective through continuation metadata instead of duplicating it in the
Toolkit prompt.

Lowering rules:

- `EventKind.GOAL_CONTINUATION` lowers as a user-role compatible reminder to keep pursuing the active
  session Goal.
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

## 6. UI Projection

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
- Do not display as a user-authored pending bubble.
- Do not expose delete controls.
- Timeline UI may show a non-interactive indicator.

Goal briefing:

- Render durable `goal_briefing` events as cards.
- The card shows the completed Goal, elapsed time from Goal creation to completion, and completion
  timestamp.

## 7. Verification

Primary checks:

- `cd python/apps/azents && uv run pytest src/azents/engine/tools/goal_test.py`
- `cd python/apps/azents && uv run pytest src/azents/engine/events/litellm_responses_test.py`
- `cd python/apps/azents && uv run pytest src/azents/engine/hooks/dispatcher_test.py`
- `cd python/apps/azents && uv run pytest src/azents/services/input_buffer_test.py`
- `cd python/apps/azents && uv run pytest src/azents/worker/session/idle_continuation_test.py`
- `cd python/apps/azents && uv run pytest src/azents/api/public/chat/v1/chat_api_test.py`
- `cd python/apps/azents && uv run pyright`
- `cd typescript && pnpm run lint --filter=@azents/web`
- `cd typescript && pnpm run typecheck --filter=@azents/web`
