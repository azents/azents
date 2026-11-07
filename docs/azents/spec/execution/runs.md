---
title: "Run lifecycle and execution ownership"
created: 2026-11-04
tags: [wiki]
---

# Run lifecycle and execution ownership

Owns durable AgentRun state and execution admission, completion, stop and recovery boundaries. The model/tool algorithm links here instead of maintaining a second Run-state definition.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Agent execution](../flow/agent-execution-loop.md)
- [Run recovery](../flow/run-resume.md)
- [Session mailbox and input admission](mailbox.md)
- [Conversations and events](../domain/conversation.md)

## Durable AgentRun model

NEW foreground and compaction model operations compile current exact authorized
local declarations for the configured identities before effective-profile
normalization. Owner-locked preparation revalidates those local inputs.
Configured IDs, candidate order and settings remain user configuration. Active
Agent responses may carry newly compiled metadata, but reads and unrelated saves
do not rewrite that configuration.

Existing operations freeze final capabilities with their candidates. Automatic
retry, quota cursor progression, takeover and replay retain those snapshots and
historical fingerprints instead of consulting current metadata. Missing required
metadata at NEW preparation retains the assigned identity and yields a typed
failure; it is not a quota skip or permission to select another model.

`agent_runs` is the durable execution-state table for the event loop.

| Field                           | Type                    | Notes                                                                                                                                                        |
| ------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`                            | `str(32)`               | UUID7 hex run id                                                                                                                                             |
| `session_id`                    | FK `agent_sessions`     | Owning conversation                                                                                                                                          |
| `run_index`                     | int                     | Session-scoped monotonic run index                                                                                                                           |
| `phase`                         | enum                    | UI activity source                                                                                                                                           |
| `status`                        | enum                    | `pending`, `running`, `completed`, `stopped`, `failed`, `interrupted`, or `cancelled`                                                                        |
| `requested_model_target_label`  | string \| null          | Agent-owned target label selected for first activation; null only before activation or on historical rows.                                                   |
| `requested_reasoning_effort`    | enum \| null            | Nullable requested effort paired with the activation label; it does not store resolved physical model state.                                                 |
| `active_tool_calls`             | JSONB array             | `call_id`, `name`, redacted/summarized `arguments`, `started_at`, and `owner_generation`                                                                     |
| `retry_state`                   | JSONB \| null           | Durable current-model-turn retry state; cleared on successful model output admission or terminal transition                                                  |
| `model_operation_state`         | JSONB \| null           | Frozen foreground and compaction candidate chains, cursors, attempted identities, candidate outcomes, and transferred probe/reservation claims for recovery. |
| `vfs_projection`                | JSONB \| null           | Self-contained immutable `azents://` source and file snapshot authorized for this run. It is ensured before input promotion and reused by recovery.           |
| `parent_agent_run_id`           | FK `agent_runs` \| null | Parent run lineage for a subagent's first run                                                                                                                |
| `last_completed_event_id`       | `str(32)` \| null       | Terminal run boundary event id when available                                                                                                                |
| `terminal_result_event_id`      | `str(32)` \| null       | Terminal assistant/error event used for the terminal mailbox result and Subagent Tree preview.                                                               |
| `terminal_result_message`       | text \| null            | User-safe terminal message delivered through `agent_result` and projected in the Subagent Tree.                                                              |
| `parent_result_delivery_state`  | enum \| null            | `suppressed` for historical results or `enqueued` after durable direct-parent mailbox delivery; null means a current eligible result has not been finalized. |
| `parent_result_mailbox_item_id` | `str(32)` \| null       | Durable identity of the terminal result mailbox envelope even after promotion deletes the mailbox row.                                                        |
| `parent_result_enqueued_at`     | timestamptz \| null     | Time the terminal result and delivery marker committed atomically.                                                                                           |
| `created_at` / `updated_at`     | timestamptz             | Durable lifecycle timestamps                                                                                                                                 |

`agent_session_unread_runs` is a sparse shared review projection for active root Sessions. Its primary key is `session_id`; it records one terminal `run_id` and the monotonic session-local `run_index`. A row means the Session is unread through that terminal Run, while no row means read. Every first transition from a nonterminal Run to `completed`, `failed`, `stopped`, `interrupted`, or `cancelled` upserts the boundary in the same transaction, retaining only the greatest `run_index`. Subagent and archived Sessions do not create this projection. The public active Session list and detail responses expose nullable `unread_terminal_run_id`. `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/read` validates an observed terminal Run and conditionally clears the boundary only when its stored run index is not newer, so acknowledgement of Run N cannot clear concurrent Run N+1.

Phase values are `idle`, `preparing_input`, `waiting_for_model`, `streaming_model`,
`normalizing_output`, `executing_tools`, `appending_events`, `compacting`, and `stopping`.

`model_operation_state` contains independent foreground and compaction slots. A fresh operation
freezes the selected semantic label's ordered candidates and compatible settings. Each slot records
its current cursor, quota-attempted identities, transferred probe or Primary reservation claim, and
one bounded outcome per candidate. Recovery and Worker handover resume this state rather than
re-reading or restarting an in-flight chain. A fresh manual failed-run retry creates a new Run and
resolves the current Agent chain.

`retry_state` is the source of truth for the current physical candidate's non-quota failed-run retry
progress. While present, the run remains `running` and live run state exposes the active retry cycle
during backoff and the in-flight retry attempt. Successful model output admission clears
`retry_state` in the same transaction that appends the output, so a later model turn starts with a
fresh retry budget and REST resync cannot recover an earlier turn's error. Terminal run updates also
clear `retry_state` defensively so retry progress cannot leak into completed, stopped, failed,
interrupted, or cancelled runs. Classified provider-attributed retry state may retain only the closed
category, diagnostic retryability, bounded redacted provider message, safe code/type/status/retry
hint, internal provider/model/integration identifiers, and stable safe fingerprint. Every classified
provider category except `quota_or_billing` uses the complete failed-run budget; diagnostic
`non_retryable` does not short-circuit a typed provider failure. A normalized quota or billing
failure is recorded in the operation slot and advances immediately to the next eligible candidate
before generic retry publication. An unclassified provider outcome does not create provider retry
state and instead follows the ordinary internal-error path.

A run is precreated as `pending` and associated with its ordered durable input events through
`agent_run_input_events`. [Mailbox promotion](mailbox.md#input-envelopes-admission-and-promotion)
atomically commits canonical transcript events, run-input associations, Goal/Skill side effects,
and mailbox-item deletion. Fresh model-operation finalization separately stores the complete Session
inference snapshot under its Run, owner-generation and exact-operation fence; see
[model selection](../models/selection.md#runtime-resolve). Handled mailbox preparation failures and
external preparation exceptions follow the linked promotion contract rather than sharing one
consumption or retry boundary. Only one pending run may exist for a session. Pending and running
runs are active recovery state.

The requested label is intent, while the Session-owned current inference snapshot is the execution authority at each turn boundary and automatic retry attempt. On first activation, `AgentRun` stores only that selected requested label and nullable effort alongside lifecycle, parentage, activity, retry, terminal-result state, and its immutable managed-file projection; it does not own or restore the resolved physical model selection or effective limits. A profile change arriving during an active run is prepared for the next ordinary boundary. A model-call failure keeps the failed attempt's snapshot immutable, but after retry backoff the next attempt freshly resolves the current Session-applied profile and rebuilds the same run's physical request and effective limits. Manual retry creates a new pending run, preserves the original ordered input-event associations, copies the original run's requested intent, and re-resolves current Agent routing at activation. A subagent's first run is precreated with `parent_agent_run_id`; child creation first stores either the exact parent Session snapshot or a statically validated spawn override on the child Session. Recovery activates the child from that Session snapshot without deriving resolved model state from the parent or child run row. Each child run independently owns its VFS projection row rather than inheriting the parent run's projection.

Every current subagent Run that reaches `completed`, `failed`, `stopped`, `interrupted`, or
`cancelled` is eligible for one queue-only terminal result to its direct parent. Terminal state,
validated direct-parent ownership, the typed queue-only `agent_result:{run_id}` mailbox envelope,
and the Run delivery marker commit atomically in one transaction. If that transaction fails, the
complete terminal-and-delivery transaction is retried; no partial terminal state or mailbox side effect
is treated as authoritative. `wait` is a pure observer and later source-session reuse has no authority
to repair or complete parent delivery. Delivery failure therefore does not leave terminal state
committed without its corresponding mailbox envelope and delivery marker.

## Execution state and terminal boundaries

### Archived-session execution fence

Only `AgentSession.status = active` may admit new execution work. Archive marks the complete root
`SessionAgent` tree archived in one transaction, so every descendant can reject work from its local
session row without rediscovering the tree. Public message, command, edit, action, project, wake-up,
and retry boundaries reject an archived session before InputBuffer, action-execution, run, or broker
side effects. Worker claim and recovery queries select active sessions only, so restart and takeover
cannot revive archived work.

Durable purge adds an irreversible owner-generation fence to every archived subtree session before
requesting stop and emitting broker stop signals. Any pending or running `AgentRun` causes purge to
retain the tree and schedule retry; cleanup and database deletion proceed only after the active-run
check is clear. Restore is permitted only before this purge fence starts. A restored tree returns every
linked session to active state and may then admit work through the ordinary boundaries.

A due purge job may cross the fence only when its root archive schedule still matches the persisted
job. The root `AgentSession` is the lifecycle authority for the linked `SessionAgent` tree: a stale
child `AgentSession.status` does not independently reactivate the child or block purge after the root
is archived. Purge snapshots and revalidates the complete tree membership, fences every linked
session owner generation regardless of child status, stops active work, and deletes the complete tree.
An invalid pending or retry-wait job is cancelled only when the root archive schedule no longer
matches and `fencing_started_at` is still null.

`agent_runs` replaces SDK `RunState`. Run phase is also the UI activity source.

Phase enum:

- `idle`
- `preparing_input`
- `waiting_for_model`
- `streaming_model`
- `normalizing_output`
- `executing_tools`
- `appending_events`
- `compacting`
- `stopping`

`active_tool_calls` contains `call_id`, `name`, redacted/summarized `arguments`, `started_at`,
and the admitting `owner_generation`. PostgreSQL is the execution and live-state authority for this set. The shared UI Run indicator renders once at the live timeline tail for the full lifetime of a live Run, rather than inside the active Activity summary or only while a model call is in flight. `agent_runs.model_call_started_at` remains the model-call duration source: it is set when each model turn enters `waiting_for_model`, preserved through `streaming_model`, and cleared when the Run leaves the model-call phases or enters failed-attempt retry backoff. REST and WebSocket live Run projections expose this timestamp as `model_call_started_at` and expose `using_fallback`, which is true only when the current foreground route uses a fallback candidate. After ten elapsed seconds, the indicator displays the client-calculated whole-second duration immediately beside its model dots with no label and refreshes it once per second while that timestamp is present. The active Activity summary keeps its elapsed duration without parentheses and has no model-wait subtitle or model-dots icon. When it contains activity events, its circular progress indicator replaces the completed-summary check icon in the header; an empty live group renders neither a summary spinner nor a standalone indicator. When the Run closes, the Activity changes to its completed check state. Tool activity uses `executing_tools` and `active_tool_calls`. Specialized client-tool rows select locale-owned action text by lifecycle: `running` uses an in-progress expression, while terminal statuses use the completed expression.

`action_executions` and `action_execution_events` are likewise live execution state, not a second
terminal history store. Each active operation stores its admitting Session `owner_generation` and
remains `pending` or `running` in those tables. Completed, failed, and cancelled shapes exist only in
the final durable snapshot. A terminal transaction locks the live row, appends the deterministic
`action_execution_result:{execution_id}` event, and deletes the execution with its progress rows.

A newly selected run begins as `pending`. Normal buffered input follows the
[Mailbox promotion boundary](mailbox.md#input-envelopes-admission-and-promotion), followed by
[fresh model-operation preparation](../models/selection.md#runtime-resolve) before dispatch.
A canonical human `user_message` stores the immutable requested target label and raw nullable
requested effort accepted with that input. It does not copy the resolved physical selection or the
applied model display name from the prepared Session snapshot. Exact applied public provenance belongs
to the `turn_marker` for each provider call, so requested intent remains stable after reload while
applied provenance can differ at later turn boundaries. If an accepted Session or pending/retry
profile label is absent from the current Agent option list, the worker replaces it with the Agent
main option, persists the fallback Session intent when it owns that intent, and clears
fallback-incompatible effort and execution-option settings. Rejection at input admission precedes
mailbox creation. After admission, handled mailbox failure and transient external-preparation
exceptions follow the linked promotion contract; later model-resolution failure belongs to fresh
Run preparation and does not consume a second FIFO head.

Requested profile selection precedence for implicit execution is the Session applied profile then
Agent `main_model_label`; explicit human input wins over both. The applied profile contains only
Agent-owned label and nullable effort. A fresh foreground or compaction operation freezes that
label's ordered candidate chain in `agent_runs.model_operation_state`. The complete prepared Session
snapshot contains the current candidate's resolved physical selection, candidate-scoped
context/output/tool settings, effective limits, and resolution time. Inputs accepted during a
model/tool turn are applied only at the next fresh operation boundary. Commands use the implicit
selection but have no client-submitted profile.

Model-call preparation carries that exact turn-local Session snapshot through `RunRequest` and
`PreparedModelCall`. When provider usage is appended, the `turn_marker` copies the snapshot's public
applied profile and effective limits. A multi-turn run can therefore contain different immutable
marker snapshots after a boundary profile change; it never stamps all turns with one run-start
selection or queries a later Session value while appending an earlier turn.

The foreground `RunRequest` uses the current candidate's selected Session settings:
`max_output_tokens` is clamped against the selected model capability, enabled
built-in tools are lowered only from that candidate, and the effective input window
combines the selected foreground candidate with the Agent lightweight Primary. Each
candidate uses its normalized default input window when its cap is unset, treats a
maximum-only snapshot as having that same default, and clamps an explicit cap to
the normalized maximum before the smaller-window calculation. An explicit empty
built-in tool list remains all-off. Ordinary same-candidate retry rebuilds from the
Session-owned selection and settings snapshot. Quota progression advances the frozen
operation cursor and prepares the next assigned model. A reasoning or execution-option
mismatch never skips or drops an otherwise available model. Actual controls are
adapted to that model: preserve a supported reasoning effort, otherwise use the
greatest supported lower level, otherwise the smallest supported level, or null
without explicit levels; an explicit no-override null stays null. Unsupported
execution options are removed while supported options remain. The operation keeps
original requested intent, and the prepared Session/turn snapshot records the
effective controls actually sent. This adaptation is not configuration drift.
Frozen-model validation uses effective reasoning before checking the request,
instead of reapplying an incompatible Agent-global effort. Recovery and Worker takeover preserve the
frozen chain, cursor, attempted identities, and transferred probe/reservation claims
rather than rematching the mutable Agent option list.

`terminal_result_event_id` and `terminal_result_message` store the user-safe terminal output projection for a completed, failed, stopped, interrupted, or cancelled run. The Subagent Tree reads this projection instead of scanning child transcript history. A subagent Run also stores its durable direct-parent delivery state, terminal-result InputBuffer identity, and enqueue time so terminal mailbox delivery remains idempotent after the buffer is promoted and deleted.

`retry_state` is nullable durable JSON on `agent_runs`. When present, it records the active model
turn's failed-run retry progress and includes the provider/runtime presentation kind, latest user-safe
error message, failed attempt count, max retries, backoff seconds, `next_retry_at`, error type/source,
retryability, failure code, and a bounded `attempts` list. Provider failures additionally retain only
the bounded typed contract needed for handover, finalization, and structured telemetry. Each attempt
summary contains attempt number, user-safe message, error type/source, failed timestamp,
retryability, failure code, truncation flag, backoff seconds, and the next retry timestamp. `/live`
exposes this as the optional `run.retry` projection so retry UI can restore the current turn's live
retry card and attempt history without durable transcript retry-attempt events.

Failed-run retry is owned by the worker run boundary, not by the event execution core. User-visible
model/runtime errors that stop a run attempt propagate out of `AgentRunExecution` without appending a
durable `system_error`, without appending a failed `run_marker`, and without marking the run
terminal. `RunExecutor` converts the propagated failure into `FailedRunAttempt`, persists
`agent_runs.retry_state`, waits until `next_retry_at` while observing stop/shutdown, and retries the
same model turn and `run_id`. The failed attempt retains its immutable prepared snapshot. After
backoff and immediately before the next attempt, `RunExecutor` freshly resolves the current
Session-applied profile against the current Agent option mapping, replaces the Session inference
snapshot, rebuilds the model request, and publishes the refreshed live profile. Recovered persisted
retry state follows the same refresh boundary after its remaining backoff. Commands keep their
existing request because this refresh applies only to model execution. This keeps the run `running`
and prevents durable failed history until retry is finalized. `max_retries` counts retries after the
initial attempt, so a budget of three permits four total attempts and terminal attempt numbers remain
one-based within each model turn.

For xAI API-key and OAuth calls, HTTP 403 with a sanitized scalar provider message beginning
`You have run out of credits or need a Grok subscription.` normalizes to `quota_or_billing`,
even when the SDK reports `PermissionDeniedError`. Other 403 permission failures and ordinary
429 rate limits keep their existing classifications.

Normalized `quota_or_billing` bypasses same-candidate retry publication. `RunExecutor` records the
candidate outcome, renews the Workspace cooldown generation, advances the frozen operation cursor,
and dispatches the next compatible candidate immediately. Ordinary `rate_limit` and other classified
provider failures retain the failed-run retry controller. One logical operation never re-enters an
identity already recorded as quota-attempted. If no eligible candidate remains, the operation
finalizes with bounded chain-exhaustion diagnostics and the existing manual failed-run retry action
starts a fresh Run with a newly resolved chain.

Before a non-Stop model failure is recorded or its retry state is published, `RunExecutor` asks the
live projector to discard that attempt's assistant, reasoning, and provider-tool projections. The
partial batcher serializes append, timer flush, durable replacement, and discard per Session so an
in-flight flush cannot recreate an older prefix after removal. Cleanup targets only `azents-live`
assistant, reasoning, and provider-tool events; user inputs and PostgreSQL-backed active client tools
are not part of this attempt-local model cleanup. Redis/WebSocket cleanup is best-effort, but the
cleanup attempt always precedes retry-state publication. A retry therefore starts from canonical durable history rather than concatenating the
failed prefix with the next attempt. User Stop bypasses this discard because its interruption path
may durably retain valid assistant text.

The retry state remains durable during backoff and the in-flight retry so worker takeover preserves
the current turn's count and does not bypass backoff. The transaction that admits successful model
output also clears `agent_runs.retry_state`, independent of whether provider usage produced a
`turn_marker`. The first durable model-output emit resets the executor-local count and attempt
history; for client-tool output, the committed `executing_tools` phase may perform the same reset
first. A later model turn, including tool-less `end_turn = false` continuation, starts at failed
attempt 1 with a fresh retry budget. WebSocket and REST live projections keep `run.retry` while the
retry is active and remove it after successful output admission or terminal transition.
Known non-provider deterministic failures, including fixture strict-mode `no_fixture_match`, may
retain `retryability = non_retryable`, receive `backoff_seconds = 0`, and finalize on the first failed
attempt. Native-size and sampling context-limit recovery first follow
[bounded input-limit compaction](../flow/context-compaction.md#input-limit-recovery);
persistent overflow is a non-provider deterministic failure.
Other classified provider failures consume the standard backoff and complete configured
retry budget even when its diagnostic retryability is `non_retryable` or `user_action_required`.
Unclassified provider outcomes follow internal-error handling rather than provider retry handling. When
retry is exhausted, or when a non-provider non-retryable failure is observed, `FailedRunErrorFinalizer`
promotes the latest attempt to durable failed-run output by delegating durable append and terminal run
updates to the engine failed-run event store. That boundary appends the terminal `system_error` with
failed-run metadata, appends the failed run marker, and marks the run `failed` while clearing retry
state. The worker finalizer then emits `RunComplete` and clears live activity.

User Stop has priority before failed-attempt persistence, after retry-state publication, during
backoff, and during a retry attempt. Stop uses the ordinary terminal interruption path, clears retry
and context-preparation live state, appends no provider `system_error`, exposes no failed-run Retry
action, and never creates stopped-Run recovery or replay state. Terminal failed-run finalization
holds the Session ownership lock and refuses the failed transition when durable Stop intent is
already present, closing the race between `interrupt_agent` and a concurrently failing tool or
model attempt.

Command wake-ups execute through the same `RunExecutor` boundary as normal model runs. A pending
command is resolved before the `agent_runs` row is created; unknown-command or pre-run resolve
failures remain direct message-processing failures. Once a command run exists, command failures use
the same failed-run retry/finalizer boundary as normal runs. `SessionRunner` top-level
message-processing errors also remain outside the failed-run scope unless they are already inside the
concrete `RunExecutor` boundary.

Failed-run terminal `system_error` events carry a user-safe `failure` payload with `kind =
failed_run`. The payload includes finalization reason, failed attempt count, retry budget, latest
retryability/failure code, optional `action_hint`, and the same bounded user-safe attempt history
shape used by `run.retry.attempts`. Frontend history/live mapping must preserve this metadata on the
rendered error message. The terminal failed-run error card shows the safe error message inside the
card, exposes the attempt history as expandable detail, and shows a manual retry action only when the
failed-run error event is the latest visible durable event and the session is idle. It must not render
internal messages, stack traces, raw provider responses, or any observability-only diagnostics.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/session_execution`](../../../../python/apps/azents/src/azents/repos/session_execution)
- [`python/apps/azents/src/azents/worker`](../../../../python/apps/azents/src/azents/worker)
- [`python/apps/azents/src/azents/engine`](../../../../python/apps/azents/src/azents/engine)
