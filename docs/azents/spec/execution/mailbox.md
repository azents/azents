---
title: "Session mailbox and input admission"
created: 2026-11-04
tags: [wiki]
---

# Session mailbox and input admission

Owns typed input, scheduling, FIFO promotion and source provenance before work enters the durable transcript. Broker wake-ups are notifications, not execution authority.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Run lifecycle and execution ownership](runs.md)
- [Event transcript and model input](transcript.md)
- [Durable Session actions](actions.md)
- [Subagent hierarchy and coordination](subagents.md)
- [Conversations and events](../domain/conversation.md)

## Input envelopes, admission and promotion

Chat route and collaboration inputs are prepared before model-call boundaries. The supported
Mailbox kinds are `user_message`, `goal_continuation`, `turn_action_continuation`,
`external_channel_continuation`, `scheduled_task_trigger`, `scheduled_task_continuation`,
`routine_trigger`, `routine_continuation`,
`action_message`, `agent_message`, and `external_channel_message`. Every mailbox envelope carries explicit scheduling intent and an
immutable typed payload whose ordered items use stable `(mailbox_item_id, item_key)` identity.
Broker wake-ups are payload-free signals and never carry model input.

Idle continuation envelopes require their completed source Run identity independently
of model-visible text. Durable-action continuation retains its exact predecessor.
Promotion merges validated source [logical work context](runs.md#logical-work-context)
into the consuming Run in the same transaction as Event append and mailbox removal.
It does not assign a new current host to domain work, infer work from Session
membership, or parse a summary to recover authority.

Mailbox items are session-bound. The `mailbox_items` table stores `session_id`, not
`agent_runtime_id`. Every row also stores required scheduling intent as `queue_only` or
`wake_session`. Inference-producing items store optional requested target label and nullable
reasoning effort. If the head has no explicit profile, preparation uses the current Session requested
profile, then the Agent default when the Session has no snapshot.

Mailbox repositories own durable reads, writes, and promotion transactions;
`MailboxService` sequences completed operations with external preparation and delivery.
INPUT and Chat writes compose attachment claims, admission, and Session transitions
inside their repository-owned atomic operation. The low-level mailbox insert writes the pending row;
admission compositions also persist the matching Session running transition for
`wake_session` inputs, including idempotent replay. Producers deliver the routing-only broker
notification after commit. User, Goal, action, spawn, and follow-up inputs use
`wake_session`; ordinary `send_message` and terminal `agent_message` inputs with
`message_kind = agent_result` use `queue_only` and do not
mark or wake the target session. Queue-only rows remain in FIFO order and are promoted with a later
wake-producing input, but they do not count as follow-up work and do not prevent a session with no
active Run from becoming idle. An External Channel message is ordinary FIFO input after its
ingress finalization transaction commits the conversation-position advance, mailbox rows, and Session
running transition. Preparation handles exactly one FIFO head per transaction. The worker
first reads the head's identity and inference requirement, performs detached preparation, then
locks the Session and the same FIFO head. When an input already carries FileParts, attachment
preflight reuses those parts without downloading again. When parts
are absent, the admitted-attachment path validates current Session/Run authority and the original
root claim, then may download eligible Exchange attachments and create ModelFiles outside the
promotion transaction. Partial materialization is cleaned up on failure or cancellation.
See [admitted attachment materialization](../../../../python/apps/azents/src/azents/engine/run/resolve.py)
and [Mailbox preflight](../../../../python/apps/azents/src/azents/services/mailbox.py).
If the identity changed while external preparation ran, the worker discards the stale result
and starts again. The final promotion transaction applies Goal/Skill state changes, appends
canonical events, associates input events with the active run, and deletes the source mailbox item.
Fresh model-operation preparation separately resolves and commits the complete Session inference
snapshot. See
[model selection and operation snapshots](../models/selection.md).
After one row
commits, the same leased runner reads the next FIFO head without rebuilding canonical execution
authority. Concurrent appends are consumed by a later loop iteration or wake-up.

Canonical outcomes are:

| Mailbox kind              | Preparation result                                                                                                     |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `user_message`            | Durable `user_message` event.                                                                                          |
| `goal_continuation`       | Durable `goal_continuation` event.                                                                                     |
| `external_channel_continuation` | Durable `external_channel_continuation` event.                                                                    |
| `scheduled_task_trigger` / `scheduled_task_continuation` | Matching typed Scheduled Task event after exact cycle binding; see [Scheduled Tasks](../domain/scheduled-task.md). |
| `routine_trigger` / `routine_continuation` | Matching typed Routine event after current occurrence binding; see [Routines](../domain/routine.md). |
| `agent_message`           | Durable `agent_message` event.                                                                                         |
| `external_channel_message` | One source-attributed `external_channel_message` event.                                                           |
| `turn_action_continuation` | Invisible deterministic `system_reminder` after its same-Session predecessor Run completed; validated work context is carried and the turn becomes inference-eligible. |
| Goal `action_message`     | Goal side effect plus canonical goal/user events; no `action_message` event.                                           |
| Skill `action_message`    | `skill_loaded` plus optional `user_message`; no `action_message` event.                                                |
| Worktree `action_message` | Mailbox-item-keyed live `ActionExecution` claim with action payload and current owner generation; no `action_message` event. |

A handled preparation failure consumes only the failing head, appends a deterministic `system_error`,
preserves the previous Session inference snapshot, and is never retried. FIFO draining may continue
when a later input makes the next turn eligible. Operation failure is likewise terminal and does not
require a separate session-initialization gate or retry/discard action.
An external preparation exception is different: it propagates before promotion, leaves the pending
input durable, and may be retried by later execution. It is not converted into a consumed
handled-failure event. This includes a transient attachment download exception; unavailable
attachment results may instead be represented without a FilePart.

Web chat message/edit/command writes use REST commit endpoints instead of WebSocket write payloads.
`GET /chat/v1/agents/{agent_id}/team-primary-session` resolves or creates the agent's team
primary session and returns its `session_id`.
`GET /chat/v1/agents/{agent_id}/sessions/{session_id}` validates that a URL-selected session belongs
to the path agent and is visible to the requester; session missing, agent/session mismatch, and access
denied all return 404. The response includes the root `product_mode` (`team` or `user`, or null for
subagent rows) so clients can resolve Team/My navigation scope from an authorized detail response.
Child subagent sessions are directly readable through this route and through history/live routes, but
they are read-only for human chat writes. Before returning an authorized active Session detail or
list/sidebar projection, the service compiles a detached fallback for any applied
model label absent from the current Agent option list, selecting the Agent main
option and clearing fallback-incompatible intent in the response. The read does
not replace stored applied intent, increment `applied_profile_generation`, or
alter a prepared current-turn snapshot. Mutation admission remains the authority
for a persisted profile replacement and its real generation.
`POST /chat/v1/sessions/{session_id}/inputs` accepts one composer input for an existing root
Session. An input without an action appends a user message, a command action creates an idle-only
pending command, and other typed actions enter the turn-action flow. The route rejects
`session_kind = subagent` before creating a chat write request, mailbox item, pending command, live
projection, or broker wake-up.
`PUT /chat/v1/sessions/{session_id}/model-profile` is the transcript-free full replacement for the
applied Session profile. It validates the label, effort, and enabled execution-option IDs against
exact current compiled capabilities for the configured Agent choices and the implemented option
registry while holding the Session write lock,
records the required client idempotency key, and returns the accepted `session_id`, label, effort,
and enabled execution-option list. A matching replay returns the original accepted result
before revalidating mutable Agent options; reusing the key with a different payload is a conflict.
Success changes only the durable applied Session intent: it creates no mailbox item, transcript
event, pending command, Run, wake-up, provider call, or prepared-turn snapshot. The current
prepared snapshot remains authoritative for an already-started provider call, while future implicit
turn boundaries resolve the newly applied intent against the current Agent option mapping. The
repository-owned replacement operation preserves this web contract and the matching-replay result.
Every newly accepted replacement through web, input preparation, edited input, or subagent setup
increments `applied_profile_generation`, including an equal-value replacement. A matching web
idempotency replay does not invoke the setter and does not increment the generation.

New Human input, Team/User root creation, message edit, and web profile replacement
share the exact-current capability admission boundary. The first repository phase
authorizes and checks idempotent replay before capturing local declarations; pure
compilation completes outside the database transaction. The write phase repeats
authorization and replay checks, fences the captured option identity/order/settings,
requested profile and local metadata, then validates the compiled profile before any
input, idempotency record, Session or history mutation. Changed inputs reject the
new write rather than silently adopting another choice. Saved Agent configuration
and captured prices are unchanged; accepted replays and failed-run retries do not
recompile their frozen work.

Composer execution-option controls are separate from static model capabilities and built-in tools.
Fast and Ultrafast share the registry-owned `processing_speed` exclusive group. Supported saved
model snapshots may advertise both IDs, while enabled preferences select at most one. Normal is
the empty group selection, not a persisted option ID. Both desktop and mobile model pickers use
one single-choice control offering Normal and the selected model's supported members. Processing
speed uses the same text-row and right-side check-mark presentation as model and effort choices:
a labeled list card on mobile and a summary row with a flyout on desktop. Choices show concise
labels; descriptions and qualitative cost hints remain available in the returned definitions for
other consumers. Single-choice semantics and arrow-key selection remain accessible. Group selection
replaces only that group's enabled member; group-less boolean controls remain independent.
Selection edits the shared draft profile without a network write or save loading state. The existing
pending-profile highlight and Send/Confirm flow apply the complete displayed profile. New-session
composers retain the choice locally until first input admission. Switching the draft model retains
only enabled options supported by the new model without choosing another premium member.
Message editing preserves the original message's inference profile, disables execution-option
changes, and does not offer or execute a transcript-free model-only Apply, including when the
edited text is cleared. Read-only composers do not expose writable options. Unknown, duplicate, unsupported, or
conflicting explicit enabled lists are rejected before persistence or provider invocation.

Applied Session intent, mailbox-requested intent, original Run intent, and prepared inference state
retain enabled IDs independently. Requested/applied provenance survives REST, live events, history,
and reload. Input admission rejects a label that is already absent from the current Agent options. If
an accepted label becomes unavailable before preparation because the Agent options changed, the
worker falls back to the current Agent main label, replaces the active Session intent, and clears
fallback-incompatible effort and execution-option intent. Authorized active Session detail, list,
and sidebar reads project the same fallback without a hidden setter or ownership
gate. Directory, unread and Workspace views use the same detached compilation;
the stored profile and its persisted generation remain unchanged. A read
projection is not a new accepted profile or compaction authority and never
changes `current_*` inference state or an active Run's prepared snapshot. A failed model-call attempt
retains its original selection, while its next automatic retry attempt freshly resolves the latest
Session-applied model, effort, and execution-option intent after backoff. Historical missing option
state is all-off, and non-empty persisted option intent requires a corresponding model target.

`POST /chat/v1/sessions/{session_id}/edit-message`,
`POST /chat/v1/sessions/{session_id}/retry-failed-run`, and command actions submitted through the
input route are idle-only control boundaries. Message, edit, command, and failed-run retry write paths
reject `session_kind = subagent` before write side effects; new subagent instructions must enter
through parent-agent collaboration tools as `agent_message` input. All REST write
requests require `client_request_id`; accepted writes are recorded in `chat_write_requests` so
retries with the same key return the same accepted target instead of creating duplicate side effects.
REST write idempotency is scoped to `(session_id, requester_user_id, client_request_id)`. The same
`client_request_id` may be reused independently for different explicit session routes because the URL
session is the write boundary. New-session messages, normal messages, and edits require `inference_profile = { model_target_label, reasoning_effort, enabled_execution_options }`; the label is client-visible Agent intent. Effort is concrete in normal user input whenever the selected target advertises explicit levels, while models with an empty explicit-level list use nullable provider/model default internally and show no effort control. Commands require `inference_profile = null`, and failed-run retry accepts no profile override. Message writes commit a `user_message` mailbox envelope
to the explicit path session only after the admission transaction locks and reauthorizes the current
requester against the active Session, Agent, Workspace, root lineage, idempotency record, and any
claimed ExchangeFiles. The new Human mailbox envelope records the authenticated `sender_user_id`; command and
stop rows retain requester audit separately and do not become a sender or execution identity. The
transaction marks the same session running before commit. After commit, the producer may send only
`SessionWakeUp(session_id)`; a notification failure delays delivery but does not revoke, delete, or
recreate accepted work. The message path must not
resolve runtime current/active session state to replace the requested `session_id`. Edit writes
rewrite durable history state, clear pending mailbox items, commit a
`user_message` mailbox envelope, mark the session running in the producer transaction, and send a
wake-up for the explicit path session. Command writes do not enter the mailbox; they store a
single pending command on `agent_sessions`, mark the explicit path session running, and send a wake-up
for that session. Failed-run retry writes target the latest visible failed-run `system_error`; they
are rejected with `409 Conflict` if any newer visible durable event exists, if the session is running,
or if pending mailbox item/command state exists. Accepted retry writes soft-revert the failed event and later
visible events, mark the session running, send a normal wake-up, return accepted type
`failed_run_retry`, and set `history_reload_required = true`. Signal delivery is not the persistence source of truth.
The complete database-only failed-run retry operation recovers PostgreSQL-confirmed
deadlock or serialization aborts only after its session scope has closed and rolled
back. Every attempt retains the original request identity and freshly reauthorizes
the requester and target. Cancellation, stale authority, uncertain commit, and
other errors propagate; post-commit wake-up delivery is outside this recovery boundary.
REST write
responses include `session_id`, `client_request_id`, an accepted target, an authoritative live
snapshot, and `history_reload_required` for writes such as edit/command that require durable history
reload.

WebSocket chat connections are existing-session live subscription channels. They publish
subscription/history/live event actions and accept only the `subscription_health_check` control
message for subscription reconcile. Chat input, edit, command, and stop payloads are not accepted on
WebSocket. Stop is a REST control boundary: `POST /chat/v1/sessions/{session_id}/stop`.
Stop records a durable `agent_sessions.stop_requested_at` intent and sends a best-effort broker stop
signal so an active runner can cancel immediately. If the stopped session is linked to a
`SessionAgent`, stop applies to that participant subtree: a root session stop records stop intents for
running descendants, while a child detail stop records stop intents for that child subtree. Runner
polling of the DB intent covers broker signal loss. Model-visible `interrupt_agent` remains
target-scoped and does not automatically stop descendants.
`/chat/v1/sessions/new` is not a WebSocket write or subscription route. Web clients first resolve
the team primary session through `GET /chat/v1/agents/{agent_id}/team-primary-session`, navigate to
`/w/{handle}/agents/{agent_id}/sessions/{session_id}`, and then write through
`POST /chat/v1/sessions/{session_id}/inputs`. Legacy message/edit/command/stop
WebSocket compatibility paths are not part of the public contract and must not create mailbox items, edits, commands, stop requests, or compatibility error responses.

User messages preserve durable `content`, payload-specific `attachments`, and `metadata` in event
`user_message` payloads. Adapter lowerers may render headers or attachment context into model input,
but that model-visible rendering is not stored by mutating the event content text.

## Scheduling and detached admission

Mailbox scheduling mode owns the durable run-state transition. Admission of any `wake_session`
item changes the active Session to `running` in the same transaction, including idempotent replay;
`queue_only` admission leaves the current state unchanged. After acquiring the Session lease, a
Worker reads the Session without a row lock and refuses to inspect mailbox or recoverable execution
work unless that durable state is `running`.

Mailbox admission inputs and results have canonical detached definitions in
`repos/mailbox/admission_data.py`. Database-only admission composes through
`MailboxAdmissionRepository`; normal batch admission applies distinct wakes in
Session-ID order, whereas idle-continuation composition retains its no-wake
semantics. Larger input-acceptance atomic groups retain the shared in-session
primitive until their complete owning compositions are migrated.

## API route entrypoints

- `/chat/v1/sessions/{session_id}/mailbox-items/{mailbox_item_id}`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/mailbox`](../../../../python/apps/azents/src/azents/repos/mailbox)
- [`python/apps/azents/src/azents/repos/agent_session_input_operations.py`](../../../../python/apps/azents/src/azents/repos/agent_session_input_operations.py)
- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
