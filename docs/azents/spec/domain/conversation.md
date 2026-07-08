---
title: "Conversation & Events"
created: 2026-04-20
tags: [backend, engine]
spec_type: domain
domain: conversation
owner: "@Hardtack"
code_paths:
  - python/apps/azents/src/azents/services/chat/**
  - python/apps/azents/src/azents/core/config.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/run/types.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents-runtime-runner/**
  - python/apps/azents-runtime-provider-docker/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/worker/scheduler.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/event.py
  - python/apps/azents/src/azents/rdb/models/input_buffer.py
  - python/apps/azents/src/azents/rdb/models/session_git_worktree.py
  - python/apps/azents/src/azents/rdb/models/action_execution.py
  - python/apps/azents/src/azents/rdb/models/chat_write_request.py
  - python/apps/azents/src/azents/rdb/models/scheduled_task.py
  - python/apps/azents/src/azents/rdb/models/exchange_file.py
  - python/apps/azents/src/azents/repos/agent_session/**
  - python/apps/azents/src/azents/repos/agent_run/**
  - python/apps/azents/src/azents/repos/message/**
  - python/apps/azents/src/azents/repos/input_buffer/**
  - python/apps/azents/src/azents/repos/session_git_worktree/**
  - python/apps/azents/src/azents/repos/action_execution/**
  - python/apps/azents/src/azents/repos/chat_write_request/**
  - python/apps/azents/src/azents/repos/scheduled_task/**
  - python/apps/azents/src/azents/repos/exchange_file/**
  - python/apps/azents/src/azents/repos/session_workspace_project/**
  - python/apps/azents/src/azents/services/exchange_file/**
  - python/apps/azents/src/azents/services/agent_session_input.py
  - python/apps/azents/src/azents/services/chat_write.py
  - python/apps/azents/src/azents/services/input_buffer.py
  - python/apps/azents/src/azents/services/session_workspace_project/**
  - python/apps/azents/src/azents/services/session_git_worktree/**
  - python/apps/azents/src/azents/services/action_execution.py
  - python/apps/azents/src/azents/services/file_storage.py
  - python/apps/azents/src/azents/api/public/chat/**
  - python/apps/azents/src/azents/api/internal/agent_home/v1/projects.py
  - python/apps/azents/src/azents/api/internal/agent_home/v1/terminate.py
  - typescript/apps/azents-web/src/app/(app)/api/chat/exchange-files/**
  - typescript/apps/azents-web/src/app/(app)/w/[handle]/**
  - typescript/apps/azents-web/src/features/agents/**
  - typescript/apps/azents-web/src/features/chat/**
  - python/apps/azents/src/azents/engine/tools/todo.py
  - python/apps/azents/src/azents/engine/tools/goal.py
  - python/apps/azents/src/azents/engine/tools/skill.py
  - python/apps/azents/src/azents/engine/tooling/toolkit_state.py
  - python/apps/azents/src/azents/transport/chat.py
  - python/apps/azents/src/azents/worker/deps.py
  - python/apps/azents/src/azents/repos/toolkit_state/**
api_routes:
  - /chat/v1
  - /chat/v1/sessions/{session_id}/messages
  - /chat/v1/sessions/{session_id}/edit-message
  - /chat/v1/sessions/{session_id}/commands
  - /chat/v1/agents/{agent_id}/team-primary-session
  - /chat/v1/agents/{agent_id}/sessions
  - /chat/v1/agents/{agent_id}/sessions/messages
  - /chat/v1/agents/{agent_id}/sessions/{session_id}
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/archive
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/git-worktree/cleanup
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/action-executions/{action_execution_id}/retry
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/action-executions/{action_execution_id}/discard
  - /chat/v1/agents/{agent_id}/git-refs
  - /chat/v1/sessions/{session_id}/title
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/context
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/projects
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/{project_id}
  - /chat/v1/agents/{agent_id}/sessions/{session_id}/workspace/project-browser-manifest
  - /chat/v1/agents/{agent_id}/workspace/project-browser-manifest/preview
  - /chat/v1/sessions/{session_id}/history
  - /chat/v1/sessions/{session_id}/live
  - /chat/v1/sessions/{session_id}/exchange-files
  - /chat/v1/sessions/{session_id}/input-buffers/{buffer_id}
  - /chat/v1/exchange-files/{file_id}/download
  - /internal/agent-home/v1/runtimes/{agent_runtime_id}/hibernate
  - /internal/agent-home/v1/runtimes/{agent_runtime_id}/projects
last_verified_at: 2026-07-08
spec_version: 88
---

# Conversation & Events

The `conversation` domain owns `AgentSession`, event transcript events, durable
`agent_runs`, input buffers, exchange files, and scheduled task dispatch.

Production agent execution now uses the event runtime. OpenAI Agents SDK `RunState` and legacy
raw `runtime/llm.py` are not production conversation state.

## 1. Domain Model

```mermaid
erDiagram
    Agent ||--|| AgentRuntime : "has runtime"
    Agent ||--o{ AgentSession : "has sessions"
    AgentRuntime }o--|| Workspace : "scoped to"
    AgentSession ||--o{ Event : "event transcript"
    AgentSession ||--o{ AgentRun : "durable execution runs"
    AgentSession ||--o{ ExchangeFile : "shows uploads and artifacts"
    AgentSession ||--o{ SessionWorkspaceProject : "working projects"
    AgentSession ||--o{ SessionGitWorktree : "owned worktrees"
    AgentSession ||--o{ ActionExecution : "operation TurnAction executions"
    AgentRuntime ||--o{ ExchangeFile : "owns sandbox artifacts"
    ScheduledTask }o--|| Agent : "targets"
```

`AgentSession` is the conversation boundary. Direct session write routes target the requested session.
The default team conversation is the agent's team primary session, represented by
`agent_sessions.primary_kind = 'team_primary'`. Runtime current/active session lookup must not
redirect direct session writes or default team session lookup to another session.

`AgentRuntime` remains the long-lived shared runtime identity and sandbox lifecycle owner. Session
execution control state is stored on `AgentSession`; detailed run phase/tool state is stored in
`agent_runs`. Runtime lifecycle state must not be used as the authority for a session run, pending
command, stop intent, or run heartbeat.

## 2. AgentSession

`rdb/models/agent_session.py` stores session identity and lifecycle.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `str(32)` | UUID7 hex |
| `handle` | string | Human-readable, BIP-39-derived session handle used for user-facing allocation names such as owned Git worktree paths. |
| `workspace_id` / `agent_id` | FK | Workspace and agent boundary |
| `status` | enum | `active` or `archived` |
| `primary_kind` | enum \| null | `team_primary` marks the agent's default team conversation; future non-primary sessions may use `null` or another explicit kind. |
| `start_reason` | enum | `initial`, `system_recovery` |
| `title` | string \| null | Optional user-facing title. `null` means no title is available and clients should render a contextual fallback. |
| `title_source` | enum \| null | `manual`, `auto_initial`, or `auto_generated`; null means no title source yet. |
| `title_generated_at` | timestamptz \| null | Last automatic title generation timestamp. |
| `title_generation_event_id` | `str(32)` \| null | Event used as the automatic title generation boundary. |
| `last_user_input_at` | timestamptz | Latest non-reverted `user_message` timestamp used for session list ordering; initialized to `created_at` until user input exists. |
| `end_reason` | enum \| null | Archive reason |
| `model_input_head_event_id` | `str(32)` \| null | Event model-input head after append-only compaction |
| `run_state` / `run_heartbeat_at` | enum / timestamptz | Session execution recovery state |
| `pending_command_*` | mixed | Single pending idle command for this session |
| `stop_requested_*` | mixed | Durable stop intent for this session |

Only one team primary session may exist per agent in the current product state. Additional active
non-primary team sessions may exist under the same agent with `primary_kind = null`.
`GET /chat/v1/agents/{agent_id}/sessions` lists active agent sessions with the team primary session
first and the remaining sessions ordered by persisted `last_user_input_at`, the timestamp of the
most recent non-reverted `user_message` event or the session creation time when no user input exists.
This lets newly created sessions appear naturally in the active list before their first message. Each
session item includes `run_state` so azents-web can mark running sessions in the Agent rail session
list. `POST /chat/v1/agents/{agent_id}/sessions` creates an active non-primary team session. The
current request shape is `existing_project_paths` plus ordered `setup_actions`.
`existing_project_paths` registers explicit Project paths supplied by the client and does not copy
Projects from the team primary session. Each `create_git_worktree` setup action is stored as an
ordered `action_message` input before the first user message; the action execution creates an
Azents-owned Git worktree from the source Project path and starting ref before registering the created
worktree as a session Project. Legacy `workspace_items`, `workspace_mode`, and `project_paths` request
fields are not part of the current contract.
`POST /chat/v1/agents/{agent_id}/sessions/messages` creates the same kind of non-primary team session
and enqueues setup action inputs plus the first user message in one write boundary. Setup action inputs
remain ahead of the user message in FIFO order. Successful Project-mutating action execution gates the
first model run until context can be rebuilt from the updated Project registry; failed actions are
marked failed and FIFO processing continues to the first user message. The first-message create
response is `ChatWriteResponse`, including the created `session_id` and live snapshot. azents-web Agent detail routes surface the active
session list in the Agent rail and navigate selected sessions through
`/w/{handle}/agents/{agent_id}/sessions/{session_id}`. The Agent rail new-session action navigates to
`/w/{handle}/agents/{agent_id}/sessions/new`, which is a draft route and must not create an
`AgentSession` row. The draft route renders the Agent top bar plus the chat input surface, but it does
not render session-scoped Projects or Context tabs. The draft composer shows a compact additive
workspace selector where repository folders are added to one list and each selected folder can switch
between repository and new worktree modes from the row-level type selector; the worktree base branch
picker shows local branches only. On first-message success, azents-web replaces the draft
URL with the created session URL and invalidates the Agent session list cache.

Each session may have a user-facing `title`. `PATCH /chat/v1/sessions/{session_id}/title`
sets or clears a manual title after workspace membership validation. The request body uses `{ "title":
string | null }`: non-null titles are trimmed and must be non-empty and at most 200 characters; an
explicit `null` clears the title and title source so automatic title generation may run again. Manual
titles set `title_source = manual` and automatic generation must never overwrite them.

Automatic title generation has two phases. When the first user message is promoted into the durable
transcript and the session has no title source, the server stores a deterministic `auto_initial` title
from the beginning of that message. The worker then immediately schedules best-effort lightweight
model title generation from that initial user prompt without waiting for the first run to complete.
The resulting concise `auto_generated` title only replaces the deterministic title while
`title_source = auto_initial` and `title_generation_event_id` still points at the same initial prompt
event. Manual title updates or clears therefore remain authoritative, while long-running first turns
do not delay automatic title generation. Title generation failures must not affect run execution.
Clients display `title` when present and otherwise fall back to a contextual label such as "Team
primary" or "Session". Concrete session route top bars show this session title while preserving the
Agent avatar/icon affordance, and expose an inline title edit action that calls the manual title update
endpoint.

`POST /chat/v1/agents/{agent_id}/sessions/{session_id}/archive` archives an active non-primary
AgentSession. Archive is a soft lifecycle transition: durable transcript data, run rows, exchange
files, and project registry rows remain, while the session is removed from active session lists.
Team-primary AgentSessions cannot be archived because they are the stable default conversation anchor
for an Agent. Running sessions cannot be archived; users must stop the run before archiving. Archived
sessions are not part of the current active session UI/API surface.

The Agent rail shows session actions in a row action menu. Rename remains available from that menu
when the title mutation is wired. Archive appears in the same menu only for non-primary sessions that
are not running and opens a confirmation dialog before calling the archive API. If the archived
session is currently selected, the UI returns to the independent Agent settings page at
`/w/{handle}/agents/{agent_id}/settings` instead of resolving a replacement session implicitly.

For sessions with an Azents-owned Git worktree allocation, archive requests mark cleanup pending and
schedule best-effort cleanup after the archive response. Cleanup removes only the explicitly owned
worktree path and Azents-created branch after validating the `session_git_worktrees` ownership row.
Cleanup failure does not roll back archive; it records a user-safe cleanup summary and leaves manual
retry available through `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/git-worktree/cleanup`.
Hard delete of a session must not erase the ownership metadata before cleanup reaches `cleaned` or
`cleanup_failed`.

Direct session writes are session-scoped. When a route contains `session_id`, input buffers, live
projections, broker wake-up, and the REST response use that same session id. Runtime current/active
session lookup is invalid for that direct write path and for default team session selection. If any
internal write helper produces a different session id from the REST boundary's resolved target, the
write is invalid and must not enqueue a broker wake-up for that alternate session. `agent_runtime_id`
is not stored on `AgentSession`; runtime lookup happens only after a session target has already been
selected.

### SessionWorkspaceProject

`rdb/models/session_workspace_project.py` stores the project registry used as session working
context. `SessionWorkspaceProject` rows are owned by `AgentSession` through `session_id`.
Runtime owns only the physical workspace where project paths exist.

Project and context inspector routes are session-scoped under
`/chat/v1/agents/{agent_id}/sessions/{session_id}/...`. They validate that the selected session
belongs to the requested agent and that the requester is a workspace member before reading or writing
that session's rows. Runtime lookup is allowed only after that session context is selected, and only
for physical workspace validation or runner filesystem operations. Runtime current project, selected
project, active project, team-primary fallback, and runtime-owned project catalog state are not part of
the conversation prompt contract. The Agent Project catalog is only a reusable path/status projection
for browser and new-session preview UI; session Project rows remain the prompt-eligibility source.

RuntimeToolkit loads registered project prompt content from the current logical `AgentSession` ID.
Runtime context sharing affects shell/file operations; it must not make project registry ownership or
project prompt selection fall back to a parent, team-primary, or runtime session.

### ActionExecution and SessionGitWorktree

The legacy setup lifecycle tables are no longer part of the current conversation model. Setup work that affects a session is represented by
durable operation TurnActions, and ordinary sessions have no separate setup baseline row. The session
runner processes pending action messages before later model input. A Project-mutating action that
succeeds invalidates prepared context and forces the next processing boundary to rebuild context;
failed actions are marked failed and do not block later FIFO input.

`action_executions` stores durable execution state for operation TurnActions keyed by the
corresponding durable `action_message` event id. `action_execution_events` stores ordered progress
records such as step start, command start/completion, stdout/stderr text, warning, failure, retry
request, failed-final discard, and completion. `GET /chat/v1/sessions/{session_id}/live` and REST
write snapshots expose `action_executions` as execution state plus event log so reconnect can rebuild
the current action card without reading chat history. Retry and discard APIs mutate only failed action
executions and return the updated action execution projection.

`session_git_worktrees` is the cleanup authority for Azents-owned worktrees. It stores the source
Project path, starting ref, generated worktree path, generated branch name, base commit, status,
failure summary, cleanup summary, and the owning action execution when the worktree came from a
TurnAction. Worktree creation uses typed Runner Git operations, registers exactly the created path in
`session_workspace_projects`, and upserts the Agent Project catalog entry without updating
last-created-session defaults. Existing Project selections still refresh presets/defaults directly;
worktree actions refresh source-path presets and register only the created worktree path as prompt
context. The ownership row, not reserved-root membership or `session_workspace_projects`, is required
before destructive cleanup can remove a path or branch.

## 3. AgentRun

`agent_runs` is the durable execution-state table for the event loop.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `str(32)` | UUID7 hex run id |
| `session_id` | FK `agent_sessions` | Owning conversation |
| `run_index` | int | Session-scoped monotonic run index |
| `phase` | enum | UI activity source |
| `status` | enum | `running`, `completed`, `stopped`, `failed`, `interrupted`, or `cancelled` |
| `active_tool_calls` | JSONB array | `call_id`, `name`, redacted/summarized `arguments`, `started_at`, `background` |
| `retry_state` | JSONB \| null | Durable failed-run retry state while the run remains `running`; cleared on terminal transition |
| `last_completed_event_id` | `str(32)` \| null | Terminal run boundary event id when available |
| `created_at` / `updated_at` | timestamptz | Durable lifecycle timestamps |

Phase values are `idle`, `preparing_input`, `waiting_for_model`, `streaming_model`,
`normalizing_output`, `executing_tools`, `appending_events`, `compacting`, and `stopping`.

`retry_state` is the source of truth for failed-run retry progress. While present, the run remains
`running` and live run state may expose a retry projection. Terminal run updates clear `retry_state`
so stale retry progress cannot leak into completed, stopped, failed, interrupted, or cancelled runs.

## 4. Event Transcript Events

Event transcript is the durable source of truth for model/tool/session output. Event payloads are
stored as JSONB and validated by event kind.

Event kinds:

- `user_message`
- `background_completion`
- `assistant_message`
- `reasoning`
- `client_tool_call`
- `client_tool_result`
- `provider_tool_call`
- `provider_tool_result`
- `turn_marker`
- `run_marker`
- `interrupted`
- `compaction_marker`
- `compaction_summary`
- `system_reminder`
- `goal_continuation`
- `goal_updated`
- `action_message`
- `action_execution_result`
- `skill_loaded`
- `goal_briefing`
- `system_error`
- `unknown_adapter_output`

`action_message` records user-selected TurnActions. `skill` actions load Skill context and are hidden
from the chat timeline once the matching `skill_loaded` event and optional normal user message are
present. `create_git_worktree` actions are operation actions: the action message is the operation
identity, the action payload is the request source of truth, and action execution state is stored in
`action_executions` instead of patching the transcript event payload. `action_execution_result` is a
durable transcript event containing the terminal action execution projection after a worktree action
completes; it lets history reloads render completed operation logs without treating them as model
input or ordinary chat bubbles.

`skill_loaded` records a Skill turn action side effect. Its payload stores the Skill display name,
exact `skill_path`, full Skill body, original user action message, content hash, source label, and
relative hint. Model lowering injects `skill_loaded` as a required user-role instruction to read and
follow the embedded Skill body; the original user action message is promoted as the following normal
`user_message` event when non-empty. The UI renders `skill_loaded` as an expandable control event and
hides the durable Skill `action_message` so the user's request appears once as a normal message.

`system_error` payloads may include optional user-safe failed-run metadata under `failure`. The
metadata identifies terminal failed-run output, finalization reason, retry counts, last error type,
and future retry classification fields. Stack traces, raw provider response bodies, and credential
details are not stored in durable transcript payloads.

Attachments are payload-specific, not event-common. Tool result output is always a part array using
`output_text`, `output_image`, `output_file`, `output_audio`, or `output_video`.

events have both physical append identity and model-visible order. Physical ids keep the
durable append/audit sequence. `model_order` is scoped to a session and is the ordering/filtering key
used when reading future model input. Sequential appends allocate `model_order` with a gap so later
compaction can insert model-visible system events without renumbering the whole transcript.
Compaction keeps append-only storage while presenting future model input from a single
`compaction_summary` head event.

`NativeArtifact.item` is adapter-native opaque payload. Event core does not interpret it.
Same-native pass-through is allowed only when the compat key matches:

```text
adapter:native_format:provider:model:schema_version
```

## 5. History And Live Event APIs

The final `events` table is the durable transcript table. Public chat readers use two separate
event-list APIs:

- `GET /chat/v1/sessions/{session_id}/history` returns persisted transcript events, paginated by
  durable event id. `before` pages older history and `after` pages newer history; the two cursors
  are mutually exclusive. Responses include `has_more` for older pages and `has_newer` for newer
  pages.
- `GET /chat/v1/sessions/{session_id}/live` returns current non-durable live state such as
  streaming assistant text, streaming reasoning, active tool calls, pending input buffers, run state,
  session todo snapshot, and action execution projections.

Both responses use the same event transport shape as the durable transcript. The removed
`/chat/v1/sessions/{session_id}/messages` aggregate endpoint is not part of the public contract:
history, live state, pending input, and activity state must not be recombined into a message-list
schema at the API boundary.

Live projections are stored behind a `LiveEventStore` abstraction. The production implementation uses
Redis, while tests may use the in-memory implementation. Pending input buffers are persisted in the
input-buffer table and are exposed through `/live` as projections with metadata marking the projection
source. Goal continuation starts as a pending `goal_continuation` input buffer and becomes a durable
`goal_continuation` event only when the session runner flushes buffers into the next model input.
`goal_updated` is appended when the user updates the session Goal. User-requested stop appends
`interrupted` before the terminal run marker. The UI must not render these control events as user
bubbles or delete controls; it may render non-interactive timeline indicators such as goal controls or
an interrupted divider.

Session todo is persisted in `toolkit_states`, not in the transcript. `/live` and REST write snapshots expose it as `todo: { items }`; each item has `content` and status `pending`, `in_progress`, or `completed`. The same live and write snapshots expose `action_executions` as the current operation TurnAction projections. Terminal action projections are also appended as durable `action_execution_result` events so completed worktree progress remains visible after live state is cleared. The worker broadcasts `todo_state_changed` after `update_todo` so the chat UI can update without a separate todo read API.

WebSocket chat clients receive subscription and event actions:

- `subscribed` after the server has registered the session broadcast subscription;
- `subscription_health_check_ack` for visible-state subscription reconcile requests;
- `history_event_appended` for newly persisted transcript events;
- `live_event_upserted` for current live projections;
- `live_event_removed` when a projection is no longer current;
- `input_actions_updated` when composer action definitions change, including Skill projection list changes;
- `todo_state_changed` when the session-scoped TodoToolkit State changes;
- `live_run_updated` when the authoritative running run projection changes, including failed-run retry state;
- `live_run_cleared` when terminal run cleanup removes the current run projection;
- `action_execution_updated` when an operation TurnAction execution projection changes.

Durable/live handoff follows these invariants:

- `history_event_appended` is renderable event state and clients must not skip tool calls only
  because the event arrived through the history action.
- `live_event_removed` removes only the live projection. It must not remove a durable view model that
  has already been promoted from `history_event_appended`.
- `live_run_updated` replaces the current `run` live-state snapshot atomically; `live_run_cleared`
  clears only the live run snapshot and does not remove durable transcript events.
- When a durable event has a matching live counterpart, the worker publishes the history
  append action before publishing the live removal action.
- If the same semantic entity is present in both durable history and live projection, durable history
  wins for rendering.

Text and reasoning streaming projections are server-side batched before live store upsert and
`live_event_upserted` broadcast. The worker flushes pending `ContentDelta` and `ReasoningDelta`
batches before event durable boundaries and terminal runtime boundaries. Redis stores only the
latest live projection, not every provider delta.

Legacy chat UI deltas and input-buffer notifications such as `content_delta`,
`reasoning_delta`, `function_call_delta`, `run_started`, `run_phase_changed`, `input_buffered`, and
`input_buffer_deleted` are not frontend state contracts.

### Frontend Markdown rendering

azents-web renders user-visible chat Markdown with GitHub Flavored Markdown, soft line breaks, and
compact chat typography. Fenced code blocks render through the chat code block renderer. A fenced code
block with language `mermaid` renders as an inline Mermaid diagram instead of syntax-highlighted text.
The Mermaid renderer is client-side, lazy-loads the Mermaid package, uses strict Mermaid security
settings for untrusted chat content, and falls back to the original source block with a user-visible
error message when diagram rendering fails.

## 6. Input Buffers And Session Inputs

Chat route input buffers are flushed before model-call boundaries and promoted to durable session
input. Session runner payload ingress uses input buffers. The supported input buffer kinds are
`user_message`, `edited_user_message`, `background_completion`, `goal_continuation`, and
`action_message`. Broker messages do not carry model input payloads.

Input buffers are session-bound. The `input_buffers` table stores `session_id`, not
`agent_runtime_id`. Runtime-specific columns or runtime-scoped buffer queries are invalid because the
buffer is part of the conversation, not the sandbox lifecycle.

`InputBufferService` owns all input-buffer reads and writes. Public chat routes, worker idle
continuation, session runner flushing, and tests should go through this service instead of calling
`InputBufferRepository` directly, except where repository tests or migrations explicitly exercise the
storage layer. Service methods are responsible for these transaction boundaries:

- enqueueing or moving buffers to a session marks `agent_sessions.run_state` as `running` in the same
  database transaction as the buffer mutation;
- flushing buffers claims the session-bound pending set, appends the corresponding durable events,
  and deletes the claimed buffers after successful promotion;
- buffer idempotency is scoped to `(session_id, kind, idempotency_key)` when an idempotency key is
  present.

The durable event kind is determined by buffer kind at flush time:

| Input buffer kind | Durable event kind |
| --- | --- |
| `user_message` | `user_message` |
| `edited_user_message` | `user_message` |
| `background_completion` | `background_completion` |
| `goal_continuation` | `goal_continuation` |
| `action_message` | `action_message` |

Wake-up delivery is a signal only. The persisted buffer plus the `running` state transition is the
recovery source of truth if the signal is lost. Operation `action_message` buffers are promoted and
executed before later model input at the same boundary. A failed operation action is marked failed and
FIFO processing continues to later pending input; no separate session-initialization gate exists.

Web chat message/edit/command writes use REST commit endpoints instead of WebSocket write payloads.
`GET /chat/v1/agents/{agent_id}/team-primary-session` resolves or creates the agent's team
primary session and returns its `session_id`.
`GET /chat/v1/agents/{agent_id}/sessions/{session_id}` validates that a URL-selected session belongs
to the path agent and is visible to the requester; session missing, agent/session mismatch, and access
denied all return 404.
`POST /chat/v1/sessions/{session_id}/messages` appends a user message input to an existing session.
`POST /chat/v1/sessions/{session_id}/edit-message`,
`POST /chat/v1/sessions/{session_id}/commands`, and
`POST /chat/v1/sessions/{session_id}/retry-failed-run` are idle-only control boundaries. All REST write
requests require `client_request_id`; accepted writes are recorded in `chat_write_requests` so
retries with the same key return the same accepted target instead of creating duplicate side effects.
REST write idempotency is scoped to `(session_id, user_id, client_request_id)`. The same
`client_request_id` may be reused independently for different explicit session routes because the URL
session is the write boundary. Message writes commit a `user_message` input buffer
to the explicit path session before returning success, mark the same session running through
`InputBufferService`, then send a worker wake-up signal for that session. The message path must not
resolve runtime current/active session state to replace the requested `session_id`. Edit writes
rewrite durable history state, clear pending input buffers, commit an
`edited_user_message` input buffer, mark the session running through `InputBufferService`, and send a
wake-up for the explicit path session. Command writes do not enter the input buffer; they store a
single pending command on `agent_sessions`, mark the explicit path session running, and send a wake-up
for that session. Failed-run retry writes target the latest visible failed-run `system_error`; they
are rejected with `409 Conflict` if any newer visible durable event exists, if the session is running,
or if pending input/command state exists. Accepted retry writes soft-revert the failed event and later
visible events, mark the session running, send a normal wake-up, return accepted type
`failed_run_retry`, and set `history_reload_required = true`. Signal delivery is not the persistence source of truth. REST write
responses include `session_id`, `client_request_id`, an accepted target, an authoritative live
snapshot, and `history_reload_required` for writes such as edit/command that require durable history
reload.

WebSocket chat connections are existing-session live subscription channels. They publish
subscription/history/live event actions and accept only the `subscription_health_check` control
message for subscription reconcile. Chat input, edit, command, and stop payloads are not accepted on
WebSocket. Stop is a REST control boundary: `POST /chat/v1/sessions/{session_id}/stop`.
Stop records a durable `agent_sessions.stop_requested_at` intent and sends a best-effort broker stop
signal so an active runner can cancel immediately. Runner polling of the DB intent covers broker
signal loss.
`/chat/v1/sessions/new` is not a WebSocket write or subscription route. Web clients first resolve
the team primary session through `GET /chat/v1/agents/{agent_id}/team-primary-session`, navigate to
`/w/{handle}/agents/{agent_id}/sessions/{session_id}`, and then write through
`POST /chat/v1/sessions/{session_id}/messages`. Legacy message/edit/command/stop
WebSocket compatibility paths are not part of the public contract and must not create input buffers,
edits, commands, stop requests, or compatibility error responses.

User messages preserve durable `content`, payload-specific `attachments`, and `metadata` in event
`user_message` payloads. Adapter lowerers may render headers or attachment context into model input,
but that model-visible rendering is not stored by mutating the event content text.

## 7. Exchange Files And Attachments

Exchange files remain the durable user-visible file/artifact surface. Generated model image/file output
is represented in event transcript as provider tool call/result events with attachments.

## 8. Compaction

Compaction is append-only. It appends `compaction_marker` and `compaction_summary`, keeps old events
for UI/audit, and moves `agent_sessions.model_input_head_event_id` to the summary id so future model
input starts from the compacted head.

Future model input is selected and sorted by event `model_order`. Auto and manual compaction both
summarize the full selected model-input transcript into one `compaction_summary` event. Runtime
compaction summary hooks may enrich the generated summary before continuity is appended. The summary
content also includes bounded `Recent User Messages` and `Recent Transcript` sections. The
user-message section keeps the last five user messages visible even when a long tool-heavy run leaves
no user messages in the recent turn window. The transcript section uses readable model-visible
excerpts from the last five completed model turns. Each excerpt is truncated independently before it
is embedded in the summary payload, so oversized tool output cannot remain as an unbounded raw tail or
storage JSON dump.

## 9. Invariants

- `AgentSession` is the conversation boundary; interface type is not a session partition.
- Event transcript is the durable model/tool source of truth.
- Native artifacts are opaque replay optimizations, never event state.
- `agent_runs.phase` and `active_tool_calls` are the durable UI activity source.
- Public chat UI state is restored from `/history`, `/live`, and event WebSocket actions, including session todo and action execution state.
- Existing transcript/session data migration is not required for the private service cutover.
- Web chat message/edit/command writes have a single REST commit boundary; WebSocket is not a fallback write path.
- Web chat stop has a single REST control boundary; WebSocket is not a fallback stop/control path.
- `client_request_id` retry for chat writes must converge to the same accepted target without duplicate side effects.
- Input buffers are session-bound and must not store or require `agent_runtime_id`.
- Any service path that enqueues input buffers must mark `agent_sessions.run_state` as `running` in
  the same transaction.

## 10. Verification

Current verification:

- `cd python/apps/azents && uv run pytest src/azents/runtime -q`
- `cd python/apps/azents && uv run pyright`
- `cd testenv/azents && uv run pytest testenv/tests -q`
- deterministic azents E2E CI for public chat/tool behavior
- `cd testenv/azents/e2e && uv run pyright src/tests/azents/public/test_chat_input_buffer.py`
- `cd testenv/azents/e2e && uv run pytest -vv src/tests/azents/public/test_session_git_worktree_lifecycle.py` in deterministic E2E CI
- REST chat write verification evidence is recorded in `docs/azents/design/rest-chat-write-boundary.md`; preemptive stop audit and E2E coverage evidence is recorded in `docs/azents/design/preemptive-user-stop-phase6-audit.md` and `docs/azents/design/preemptive-user-stop-phase7-verification.md`. Docker/testcontainers blocker #4468 and browser-runner blocker #4469 track scenarios that could not run in the current agent runtime.

## 11. Changelog

- **2026-07-08** — v88. Clarified TurnAction FIFO behavior: failed operation actions are marked failed and later input continues, while successful Project mutation rebuilds context at the next boundary.
- **2026-07-06** — v86. Removed SessionInitialization from current conversation state and added durable `action_execution_result` terminal history events.
- **2026-07-05** — v85. Promoted operation TurnAction execution for new-session Git worktree setup, action execution projections, and clean setup request fields.
- **2026-07-04** — v83. Removed existing-session Git worktree attachment from the current conversation API and initialization contract.
- **2026-07-04** — v81. Added session initialization, worktree-mode session creation, run gating, live initialization projections, and Azents-owned Git worktree cleanup semantics.
- **2026-06-25** — v60. Moved coarse run state, run heartbeat, pending command, and stop intent
  ownership from `AgentRuntime` to `AgentSession`; `AgentRuntime` remains shared sandbox lifecycle
  state.
- **2026-06-20** — v59. Documented session-bound input buffers, removed runtime-bound buffer
  ownership from the spec, and defined the `InputBufferService` transaction boundary for running-state
  transitions and goal continuation promotion.
- **2026-07-03** — v80. Reflected explicit Project path session creation and separated Agent Project catalog UI projection from session Project prompt ownership.
- **2026-07-05** — v84. Added failed-run retry attempt history, live-run update/clear WebSocket actions, and manual failed-run retry write semantics.
- **2026-06-13** — v54. Added session todo snapshot and `todo_state_changed` WebSocket event to Chat live state. Todo is side state stored in `toolkit_states`, not durable transcript/compaction state.

- **2026-07-07 (spec_version=87)** — Removed unimplemented Project registration request API and storage from current conversation/session behavior.
