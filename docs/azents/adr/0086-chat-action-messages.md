---
title: "ADR-0086: Chat Action Messages"
created: 2026-06-30
tags: [architecture, frontend, backend, chat, engine]
---
# ADR-0086: Chat Action Messages

## Context

Azents currently has multiple chat-input control paths that look similar to the user but are implemented as separate mechanisms:

- Normal user messages are sent through the chat message write path and become input-buffer work for the normal run loop.
- Slash commands are discovered through `GET /chat/v1/commands`, displayed by `ChatInput` as a simple `/name` autocomplete list, and sent through `POST /chat/v1/sessions/{session_id}/commands`.
- The only registered command is currently `compact`; it is stored as a pending session command and processed before buffered user messages.
- Session Goal state is visible near the input through `TodoPreviewBar` and supports edit, delete, pause, and resume for an existing Goal.
- There is no user-facing UI for directly creating a Goal. Goal creation is currently exposed to the agent through the Goal toolkit (`create_goal`) rather than as a first-class chat input action.

This makes the current slash-command UI too narrow for upcoming input actions. Future input affordances need to support not only execute-and-finish commands such as compaction, but also Goal creation and later Skill invocation that should participate in the normal run loop.

The chat input needs a standard payload shape that can represent these actions without turning every feature into another bespoke input branch.

## Research notes

### Current frontend behavior

`ChatInput` detects slash suggestions with a simple parser:

- trim leading whitespace;
- require the input to start with `/`;
- reject the suggestion mode once the command segment contains a space;
- filter `slashCommands` by `command.name.startsWith(query)`.

Selecting a slash command immediately calls `onSendCommand(command.name)`. It does not put the selected command into input state, and it does not support command arguments, action chips, keyboard selection, typed action payloads, or action-specific message validation.

The draft new-session screen passes `slashCommands={[]}` and `onSendCommand={() => Promise.resolve(false)}`, so slash commands are session-only.

### Current backend command behavior

The command registry is a Python mapping from command name to handler. The only registered command is `compact`.

A command write validates that the command exists, validates session access, creates an idempotent pending command on the `agent_sessions` row, and wakes the session worker. The worker checks pending commands before normal input-buffer work and dispatches the command handler through `CommandExecutor`.

The pending command storage already has a command payload field, so it can preserve an action-message payload while still storing the command name separately for dispatch.

### Current Goal behavior

The chat service exposes REST methods to update or clear an existing Goal and to pause or resume an existing Goal. The current update path intentionally does not create a Goal when no Goal exists. Existing Goal management is covered by the Goal preview/detail UI.

Goal creation needs a user-facing action path, but existing Goal edit/delete/pause/resume should remain in the existing Goal UI instead of becoming additional action types.

## Decision

### ADR-0086-D1. Introduce Chat Action Messages

Azents will standardize input-triggered actions with a two-field action-message envelope:

```ts
type ActionMessage = {
  action: ChatAction;
  message: string;
};
```

`message` is the user-authored input for the selected action. Its exact meaning is action-specific. For example, a Goal action uses `message` as the Goal objective, while `compact` currently does not require a message.

### ADR-0086-D2. Define `ChatAction` as a discriminated union

`action.type` is the discriminator. The initial union is:

```ts
type ChatAction = CommandAction | TurnAction;

type CommandAction = {
  type: "command";
  name: string;
};

type TurnAction =
  | {
      type: "goal";
    }
  | {
      type: "skill";
      skillId: string;
    };
```

The `skill` variant is reserved for the upcoming Skill design. This ADR only records the category and payload direction needed to keep the input protocol extensible.

### ADR-0086-D3. Categorize actions into Command Actions and Turn Actions

Azents will distinguish two action categories:

1. **Command Action**
   - Requires the session to be idle at the server boundary.
   - Is a prioritized session-control operation.
   - Is processed before any buffered messages that may already exist.
   - Executes and finishes as a command run.
   - Initial example: `{ type: "command", name: "compact" }`.

2. **Turn Action**
   - Is queued with normal user input in the input-buffer flow.
   - Is processed inside the normal run loop.
   - Represents a special user input turn rather than a prioritized control operation.
   - After the action turn is handled, the run loop can naturally continue to subsequent buffered input.
   - Initial examples: `{ type: "goal" }` and future `{ type: "skill", skillId }`.

The term **Turn Action** is adopted for the second category because the action participates in the conversational run loop as a turn-like input.

### ADR-0086-D4. Generalize command handling around `CommandAction`

The existing command registry and pending-command execution path remain the right mechanism for command actions.

Command writes should be expressed as action messages where the action is a `CommandAction`:

```json
{
  "action": { "type": "command", "name": "compact" },
  "message": ""
}
```

The pending command row should continue to store the command name for dispatch. The pending command payload should preserve the full action-message envelope so future command handlers can read action metadata and message input without another schema migration.

`SlashCommandDefinition` should evolve toward a command/action definition model that can describe labels, descriptions, and message policy. The current `name` and `description` fields are sufficient for `compact`, but the UI should not remain tied to a command-only list.

### ADR-0086-D5. Treat Goal as a create-only Turn Action

The Goal action creates a new session Goal:

```json
{
  "action": { "type": "goal" },
  "message": "Ship the mobile chat scrolling fixes"
}
```

For Goal actions:

- `message` is the Goal objective.
- `message.trim()` is required.
- Existing Goal edit, delete, pause, and resume remain in the existing Goal UI.
- The backend must add create semantics because the existing Goal update path does not create a Goal when none exists.
- If an unfinished Goal already exists, the server should reject creation with a user-visible conflict instead of silently replacing it.

Whether a completed Goal allows a new Goal is an implementation detail to finalize with the Goal service design, but replacing an active/paused/blocked Goal through the create action is not adopted.

### ADR-0086-D6. Prefer failure handling over hard client-side availability blocking

The client can show availability hints, but remote state is not perfectly synchronized. At send time, the server may know that a command is no longer allowed, a Goal already exists, or a session is not idle even if the client believed otherwise.

Therefore:

- The server remains the authority for action acceptance.
- The client should avoid hard-blocking actions based only on remote state hints.
- The client may still perform local validation, such as requiring a non-empty Goal objective.
- On failure, the selected action chip and message should remain in the input so the user can retry, edit the message, or remove the action.
- Failure should be shown near the input as action-aware inline feedback.

This replaces the current command-only pattern where the UI attempts to block commands during a run and then shows a generic command-blocked message.

### ADR-0086-D7. Use an action chip inside the chat input box

The chat input UI will represent selected actions explicitly.

The desired interaction model is:

1. User types `/`.
2. The input shows an action list, not only command suggestions.
3. Selecting an item stores the selected `ChatAction` in input state.
4. The input box renders an action chip on the first line inside the composer.
5. Clicking the chip clears the selected action.
6. Sending without an action sends a normal message.
7. Sending with an action sends an `ActionMessage`.

The action chip makes the selected action visible and cancellable before submission. It also gives Goal and future Skill actions a natural place to present action-specific state without overloading slash text parsing.

### ADR-0086-D8. Queue Turn Actions with a single `action_message` input-buffer kind

Turn Actions will use one input-buffer kind instead of adding a new buffer kind per action type.

The input-buffer record should identify the category with `kind = "action_message"`, and its payload should preserve the Action Message envelope:

```json
{
  "action": { "type": "goal" },
  "message": "Ship the mobile chat scrolling fixes"
}
```

A future Skill action uses the same kind and shape:

```json
{
  "action": { "type": "skill", "skillId": "review-pr" },
  "message": "Check this PR for UX regressions"
}
```

`kind = "action_message"` means the queued item is a Turn Action. The specific behavior is dispatched by `payload.action.type`. This keeps the input-buffer queue stable as new Turn Action variants are added.

### ADR-0086-D9. Preserve processed Turn Actions as `action_message` durable events

When a Turn Action input buffer is processed, Azents will append a durable `action_message` event that preserves the original Action Message envelope.

The event records what the user sent:

```json
{
  "action": { "type": "goal" },
  "message": "Ship the mobile chat scrolling fixes"
}
```

Action-specific side effects are separate from the original user action event. For example, a successful Goal create action may also append a Goal state/control event such as `goal_updated` with metadata indicating creation. The roles are distinct:

- `action_message` records the user-authored action input.
- Goal or Skill side-effect events record resulting system state transitions.

The UI does not need to render every side-effect event. It can render `action_message` as a user-visible action bubble and keep state/control events hidden or compact when appropriate.

### ADR-0086-D10. Treat `action_message` input-buffer items as turn barriers

Turn Actions preserve FIFO input-buffer order and act as turn barriers inside the normal run loop.

The runner may batch adjacent normal user-message buffer items into one normal turn, but it must not batch across an `action_message` item. An `action_message` item is processed as its own turn.

For example:

```text
user_message A
user_message B
action_message Goal G
user_message C
user_message D
```

is processed as:

```text
turn 1: user_message A + user_message B
turn 2: action_message Goal G
turn 3: user_message C + user_message D
```

This gives Turn Actions a precise ordering model:

- user messages before the action are processed before the action;
- the action side effect happens at the action's FIFO position;
- user messages after the action are processed after the action.

`action_message` must therefore never be mixed into a normal user-message batch, and normal user-message batching must stop at action boundaries.

### ADR-0086-D11. Apply Goal Turn Action side effects during run-loop processing

Goal creation is a Turn Action side effect and must happen when the `action_message` input buffer is processed by the run loop, not at REST accept time.

At REST accept time, Azents should enqueue the `action_message` input buffer and return the accepted write snapshot. It should not immediately create or mutate Goal state merely because the request was accepted.

When the run loop reaches the Goal action buffer item, it should:

1. append the durable `action_message` event;
2. create the session Goal if allowed;
3. append any Goal state/control event needed to record the side effect;
4. continue the normal loop behavior.

This preserves Turn Action ordering semantics: action side effects occur in the same sequence as queued user inputs. It also matches future Skill behavior, where accepting an action request should not imply that the Skill has already been applied.

### ADR-0086-D12. Lower Turn Actions through action-specific handlers, not as plain user text

A processed `action_message` must not be lowered into model input as a plain user message by default. The run loop delegates model-input lowering to the action handler.

For Goal create, the handler should create Goal state and lower the turn as a Goal-created reminder/control input. The original `action_message` remains the durable user-authored action record; the model-visible input is the Goal-specific lowering.

Future Skill actions follow the same category rule but use Skill-specific lowering: the Skill handler will force-load the Skill body and then convert the action message into a normal message enriched by that Skill context. Skill execution details are outside this ADR's immediate implementation target, but this preserves the intended direction.

### ADR-0086-D13. Consume failed Turn Actions and report with `system_error`

Once the run loop attempts to process a Turn Action input-buffer item, the item is consumed. Azents will not leave a failed `action_message` in the input buffer for automatic retry.

On failure, Azents appends a user-visible `system_error` event describing the failure. This keeps the queue moving across action barriers and avoids permanently blocking later buffered input behind an action that may be invalid, such as a Goal create request when an unfinished Goal already exists.

The initial failure reporting path intentionally reuses `system_error` instead of adding a dedicated `action_failed` event kind. A future ADR may introduce structured action-failure events if richer action-specific timeline UI or analytics become necessary.

### ADR-0086-D14. Record successful Goal creation with `action_message` and `goal_updated`

A successful Goal Turn Action appends both the user-authored `action_message` event and a Goal control event using the existing `goal_updated` kind.

The `action_message` event preserves the original user action input. The `goal_updated` event records the resulting Goal state transition and should include metadata such as `goal_control_action = "create"`, the objective, and the active status.

This reuses the existing Goal event/lowering path instead of introducing a separate `goal_created` event kind. UI may render the `action_message` as the primary visible bubble and suppress or compact the `goal_updated` control event to avoid duplicate-looking output.

### ADR-0086-D15. Reject Goal create only when an unfinished Goal exists

A Goal Turn Action creates a new active Goal only when no unfinished Goal exists.

Unfinished means a Goal whose status is `active`, `paused`, or `blocked`. If an unfinished Goal exists when the run loop processes a Goal create action, the action fails, is consumed, and reports a user-visible `system_error` as described in ADR-0086-D13.

A completed Goal does not block a new Goal create action. This allows long-lived sessions to complete one Goal and then start another. Historical evidence of the completed Goal remains in transcript/control events rather than requiring the Goal state slot to remain permanently occupied.

### ADR-0086-D16. Render pending and durable action messages as input-box-like cards

Accepted Turn Action writes appear in the timeline as pending action-message entries until the run loop processes them. Goal state UI updates only after the Goal action succeeds; REST accept alone must not show the Goal as active.

Pending and durable action messages should render as input-box-like cards with the selected action chip inside the card's top row. This preserves visual continuity between composing an action message and seeing it in the chat timeline.

For example, a Goal action message should appear conceptually as:

```text
┌──────────────────────────────┐
│ [Goal]                       │
│ Ship the mobile scroll fix   │
└──────────────────────────────┘
```

Pending entries may show a compact pending indicator in the same card. If processing fails, the action-message card remains as the record of the attempted user action and the failure is shown through the following `system_error` event.

### ADR-0086-D17. Replace separate composer write endpoints with `/inputs`

Azents will introduce one session-scoped composer write endpoint:

```http
POST /chat/v1/sessions/{session_id}/inputs
```

The request accepts a user-authored `message`, an optional `action`, and optional attachments. Missing `action` creates a normal user-message input-buffer item. A `CommandAction` creates a prioritized pending command. A `TurnAction` creates an `action_message` input-buffer item.

The existing implementation-era composer write endpoints for plain messages and commands should be removed as public/frontend write paths during this migration rather than kept as parallel legacy fallbacks:

- `POST /chat/v1/sessions/{session_id}/messages`
- `POST /chat/v1/sessions/{session_id}/commands`

The unified `/inputs` endpoint is the authoritative write boundary for composer submissions after the migration.

### ADR-0086-D18. Use optional `action`, string `message`, and action-specific validation

The `/inputs` request schema uses a required string `message`, an optional `action`, and optional attachments:

```ts
type ChatInputWriteRequest = {
  agent_id: string;
  client_request_id: string;
  message: string;
  action?: ChatAction;
  attachments?: string[];
};
```

`action` is omitted for normal user messages. `action: null` is not required.

`message` is always present as a string, but empty-message validity is determined after dispatch:

- normal user message: non-empty message or attachments are required;
- `command` action: command definition decides message policy, and `compact` allows an empty message;
- `goal` action: non-empty `message.trim()` is required because it is the Goal objective;
- `skill` action: future Skill definition decides message policy.

Attachments are accepted by the request schema, but support is action-specific. Plain messages support attachments. Goal create and the initial `compact` command do not support attachments and should reject them through action-specific validation rather than silently ignoring them. Future Skill actions may support attachments if their definitions allow it.

The endpoint reuses `ChatWriteResponse`. Normal messages and Turn Actions return `accepted.type = "input_buffer"`; Command Actions return `accepted.type = "command"`.

### ADR-0086-D19. Expose composer actions through `/actions`

Azents will replace the command-only listing endpoint with a session-scoped composer action listing endpoint:

```http
GET /chat/v1/sessions/{session_id}/actions
```

The existing command-only listing endpoint should be removed as the primary frontend/public composer action source:

```http
GET /chat/v1/commands
```

The `/actions` response returns action definitions for items selectable from the chat composer. The endpoint is session-scoped because available actions, message policy, attachment policy, and UI hints may depend on session, agent, Goal, Skill, permission, or runtime state. These hints are not authoritative acceptance decisions; `/inputs` remains the final validation and write boundary.

An action definition includes a `keyword` used by slash search. `keyword` is not required to be globally unique. The UI filters action definitions by keyword when the user opens slash search. Because slash is currently the only trigger mechanism, the definition does not include a generic `trigger` field.

Slash action search should use ranked fuzzy matching over `keyword`. Exact and prefix matches should rank ahead of weaker contains or fuzzy matches. The UI should highlight matched characters in the displayed keyword, preferably by using a small client-side fuzzy matching library that exposes match ranges or highlight helpers instead of custom matching logic.

```ts
type InputActionDefinition = {
  id: string;
  keyword: string;
  label: string;
  description: string;
  action: ChatAction;
  category: "command" | "turn";
  message: {
    policy: "none" | "optional" | "required";
    placeholder?: string;
    maxLength?: number;
  };
  attachments: {
    policy: "unsupported" | "optional" | "required";
  };
  availabilityHint?: {
    state: "ready" | "warning";
    message?: string;
  };
};
```

Examples:

```json
{
  "id": "command:compact",
  "keyword": "compact",
  "label": "Compact",
  "description": "Summarize previous conversation and compact the context window.",
  "action": { "type": "command", "name": "compact" },
  "category": "command",
  "message": { "policy": "none", "placeholder": "Send to compact the conversation." },
  "attachments": { "policy": "unsupported" }
}
```

```json
{
  "id": "goal",
  "keyword": "goal",
  "label": "Goal",
  "description": "Create a session goal.",
  "action": { "type": "goal" },
  "category": "turn",
  "message": {
    "policy": "required",
    "placeholder": "Describe the goal for this session.",
    "maxLength": 4000
  },
  "attachments": { "policy": "unsupported" }
}
```

### ADR-0086-D20. Move selected actions into composer chip state

Selecting an action from slash search moves the action into explicit composer chip state and clears the slash query from the textarea. The textarea then holds only the action message input.

Initial implementation does not parse inline slash arguments. For example, users select `/goal` first and then type the Goal objective as the message. Support for moving trailing inline text such as `/goal Ship mobile fixes` into the message field may be added later, but it is not part of the initial contract.

Clearing the chip removes only the selected action and preserves the current message text. This lets the user convert an action message draft back into a normal message without losing text.

### ADR-0086-D21. Persist selected action in composer drafts

Composer drafts must persist both the selected `ChatAction` and the message text. Persisting only text is insufficient because the same text can mean a normal user message, a Goal objective, or a Skill input depending on the selected action.

The draft should store the action payload, not the full action definition:

```ts
type ChatComposerDraft = {
  message: string;
  action?: ChatAction;
  attachments?: UploadedFile[];
};
```

Labels, descriptions, placeholders, and validation policies should be resolved from the current `/actions` response when possible. If an action definition is no longer available, the UI may render a fallback chip from the stored action and allow the user to clear it; final acceptance remains the responsibility of `/inputs`.

Send success clears the draft. Send failure preserves the draft, including the selected action.

### ADR-0086-D22. Use action policy for deterministic local validation

Composer submit validation uses the selected action definition's message and attachment policies from `/actions` for deterministic local checks. Final acceptance remains server-side in `/inputs` because session and runtime state may change between UI rendering and submission.

Local validation should block only violations the client can know without relying on remote freshness:

- required message is empty;
- unsupported attachments are present;
- required attachments are missing;
- file uploads are still pending.

The initial policies are:

- normal message: non-empty message or attachments required;
- `compact` command: optional message, unsupported attachments;
- Goal create: required message, unsupported attachments;
- Skill: future Skill definition decides message and attachment policies.

Using optional message policy for `compact` keeps the composer shape stable and leaves room for future compaction hints, even if the initial command handler ignores the message.

### ADR-0086-D23. Keep Goal create visible with warning when an unfinished Goal appears to exist

The `/actions` endpoint should keep the Goal create action visible even when current session state suggests that an unfinished Goal exists.

When the server can infer that a Goal with status `active`, `paused`, or `blocked` exists, it should return a warning availability hint for the Goal action rather than hiding it. The warning should direct the user to manage the existing Goal from the Goal UI.

The client may display this warning in slash search and selected action UI, but it must not treat the hint as an authoritative acceptance decision. `/inputs` remains the final validation boundary, and Goal create may still fail during run-loop processing according to ADR-0086-D15 and ADR-0086-D13.

### ADR-0086-D24. Ship the composer action migration as one atomic PR

The Action Message migration should ship as one atomic PR rather than as a compatibility stack.

The public API, generated OpenAPI client, backend input dispatch, run-loop `action_message` semantics, Goal Turn Action side effects, and frontend composer UI are tightly coupled. The old composer endpoints are removed rather than retained as parallel legacy fallbacks, so splitting the work would create unsupported intermediate states.

The PR should include at least:

- new `/actions` and `/inputs` public API surface;
- removal of old command/message composer endpoints;
- OpenAPI client regeneration;
- backend command dispatch through `CommandAction`;
- Turn Action input-buffer/event/run-loop support;
- Goal create Turn Action handling;
- frontend action picker, input-box action chip, draft persistence, `/inputs` submit path, and action-message timeline rendering;
- cleanup of command-only frontend and API code paths.

## Consequences

- Slash input becomes an action-picker trigger rather than a command executor.
- `compact` can migrate into the action-message model while preserving the existing pending-command executor.
- Goal creation becomes a first-class user action without moving Goal edit/delete/pause/resume out of the existing Goal UI.
- Future Skill actions can reuse the same action-message envelope and chip UI.
- Backend action handling must split at the category boundary: Command Actions go through the prioritized pending-command path, while Turn Actions go through input-buffer/run-loop processing.
- Error handling must be action-aware and preserve the input state on failure.

## Deferred work

- Final REST endpoint shape for Action Messages.
- Exact OpenAPI/Pydantic schema names.
- Command definition metadata fields beyond `name` and `description`.
- Skill action semantics and registry design.
- Goal service create semantics for completed Goal replacement.
- Timeline rendering details for Goal creation action events.
