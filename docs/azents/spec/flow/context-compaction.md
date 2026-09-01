---
title: "Context Compaction"
created: 2026-05-10
tags: [backend, engine]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation, external-channel]
code_paths:
  - python/apps/azents/src/azents/engine/context/compaction.py
  - python/apps/azents/src/azents/engine/context/window.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/hooks/**
  - python/apps/azents/src/azents/engine/tooling/tool_search.py
  - python/apps/azents/src/azents/engine/tooling/toolkit_state.py
  - python/apps/azents/src/azents/engine/tools/scheduled.py
  - python/apps/azents/src/azents/repos/scheduled_task_cycle/**
  - python/apps/azents/src/azents/services/scheduled_task/rendering.py
  - python/apps/azents/src/azents/engine/run/commands.py
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/agent.py
last_verified_at: 2026-09-01
spec_version: 38
---

# Context Compaction

Context compaction keeps long session history within model input limits without deleting audit/UI
history. The event runtime uses append-only compaction.

Automatic compaction effective context window is computed by
`engine/context/window.py`. Each option first resolves a default input window and
maximum input window from its normalized capability, using the maximum as the
default when the distinct default is absent. LiteLLM metadata and the 128,000-token
fallback fill missing limits. An unset option cap uses that resolved default; an
explicit option cap is clamped to the resolved maximum.

For each prepared inference-bearing input, runtime then takes the prompt-selected
foreground option's resolved effective window and the Agent lightweight option's
resolved effective window and uses the smaller value as
`effective_max_input_tokens`. An option context cap is stored as intent and may be
larger than its current model maximum; the maximum still wins. Effective
lightweight resolution uses the Agent's stored lightweight option model
snapshot and settings. Workspace defaults are copied into the Agent only at create time and are not read
by runtime compaction. Automatic compaction threshold is then computed by
`compute_auto_compaction_threshold_tokens()` as `int(effective_max_input_tokens * 0.9)`. Both values are stored in the current `AgentSession` inference snapshot and remain fixed for that prepared turn, automatic retry, and recovery. A later prepared profile may replace them at the next turn boundary, including within the same active run. The event runtime uses this Session-owned calculation as the compaction trigger source of truth and compares the threshold against the latest turn marker `usage.prompt_tokens` plus the
model-visible token estimate for events appended after that marker. If no turn marker exists, it falls
back to estimating the full selected transcript.

## Behavior

When compaction is required:

1. Select the full ID-ordered model-input transcript and capture its current head and tail event IDs.
2. Publish the Run-scoped live operation `preparing_context` and dispatch the compaction-start lifecycle hook. The external model and hook calls run outside compactor-owned database sessions and hold no active transaction or session-row lock used for event ordering.
3. Generate the summary through the provider-specific adapter. Provider failures propagate through the common bounded `ModelProviderFailure` contract to the owning Run controller.
4. Render bounded continuity history from the selected transcript, but keep it separate from the generated summary.
5. Dispatch the compaction summary enrichment hook pipeline with the generated summary and rendered continuity history.
6. Append the continuity history after the enriched summary.
7. In one short database transaction, lock the Session and revalidate both captured boundaries. A changed head or latest non-reverted event ID makes the plan stale and writes no compaction event.
8. For a current plan, append adjacent `compaction_marker(status=started)` and `compaction_summary` events with the same `compaction_id` and reason at the physical transcript tail. The summary payload contains the enriched checkpoint followed by bounded `Recent User Messages` and `Recent Transcript` sections.
9. Move `agent_sessions.model_input_head_event_id` to the summary event, replace the Session's `tool_search/working_set.tool_names` with an empty list, and commit the same transaction. The Tool Search reset applies even when the Agent currently has Tool Search disabled; other Toolkit State identities are unchanged.
10. Remove the live operation after success, Stop, cancellation, or terminal failure. A skipped, failed, cancelled, or stale attempt appends no compaction marker or summary, does not move the model-input head, and does not reset the Tool Search working set.

Old events remain queryable. The head pointer changes which ascending event-ID range is used for
future model input. Input appended while summary generation is running invalidates the fixed plan;
the completed summary is discarded without a marker or head change, and a later attempt rebuilds
from current durable history.

## Summary Model

Summary generation is routed by provider from `engine/context/compaction.py`. OpenAI API-key and
ChatGPT OAuth use an operation-scoped official OpenAI SDK client; other providers use the shared
LiteLLM Responses helper. The compaction model is resolved from the Agent lightweight option
snapshot. Its model-scoped context cap participates in the effective input window, while its
model-scoped `max_output_tokens` and built-in tools do not replace internal compaction request policy.

Compaction summary generation is not user-facing streaming output, although the transport uses a
stream so the common watchdog can enforce parsed-event idle and absolute attempt deadlines. The
standard OpenAI-compatible helper sends ordinary user input plus top-level instructions and omits
`max_output_tokens`; it does not use sampling continuation. ChatGPT OAuth also uses complete input,
`store=false`, encrypted reasoning inclusion, and no `previous_response_id`.
Non-migrated providers receive `max_output_tokens` from the dynamic summary budget through the
LiteLLM helper. Both adapter families preserve only a bounded redacted provider message and typed safe
diagnostics for classified provider failures. An automatic classified compaction provider failure
consumes the active model turn's standard full retry budget regardless of category; the next attempt
rebuilds from current durable history. An unclassified provider outcome bypasses compaction provider
retry state and follows the ordinary internal-error path. Manual compaction uses its command Run's same
failed-run controller and fresh budget. Provider retry hints are diagnostic and do not replace the
standard backoff schedule.

The summary budget is based on the model context window:

- target summary chars: 3% of context window tokens, converted with 1 token ≈ 4 chars;
- limit summary chars: 8% of context window tokens, converted with 1 token ≈ 4 chars;
- target chars are nearest-rounded to 1000 chars and clamped to 12k–24k chars;
- limit chars are nearest-rounded to 1000 chars and clamped to 16k–50k chars;
- `max_output_tokens = limit_chars // 4`;
- unknown context windows use a 128k token fallback.

The runtime char guard allows a 10% tolerance over `limit_chars`. It computes
`truncate_chars = ceil_to_1000(limit_chars * 1.1)`. If a model returns more than `truncate_chars`, the
runtime performs a simple deterministic truncate and appends `[Truncated by Azents compaction guard.]`.
The runtime does not perform section-aware truncation or retry-based re-summarization.

The summary prompt asks for an execution-ready handoff checkpoint. It applies the transcript
chronologically as task-state transitions, identifies the active objective and current execution
state, preserves the furthest verified progress, and produces ordered next actions. Its structured
sections cover the active objective, current execution state, completed work, next actions, active
constraints and decisions, relevant files and identifiers, verification, and references. It uses
`Needs verification` only for uncertainty that materially affects a next action.

Checkpoint detail scales with task complexity rather than a fixed target length. Concise structure
removes repetition and conversational narration while retaining continuation-relevant state and
evidence. Complex or multi-stage work preserves the details needed to continue directly from the
checkpoint, including evidence of completed work and conclusions from resolved questions. Simple
work remains brief, and task complexity determines checkpoint length.

Auto and manual compaction include the full supported summary projection of the
selected transcript in the summary request. External Channel projection includes
only invocation-role messages; context-role messages remain available only through
bounded Recent Transcript continuity. The summary prompt asks for durable state from
the projected compacted transcript and warns that no raw event should be assumed to
remain available outside the checkpoint. After the model returns the checkpoint,
the runtime renders bounded continuity history separately, dispatches compaction
summary enrichment hooks, and then appends the continuity history to the stored
summary content.

Previous compaction summaries are rendered as existing checkpoints and treated as the previous state
to update. Later user direction updates the active objective, completed actions update the execution
state, and later tool or repository observations update earlier assumptions. Replaced approaches
remain only when they explain an active constraint or prevent duplicated investigation.

Manual compaction uses the same prompt, budget policy, continuity event policy, and summary
enrichment pipeline as automatic compaction. Manual compaction runs inside a `RunContext`, dispatches
`on_session_compact` with that run id, and passes the same run id to `on_compaction_summary`. It
publishes the same `preparing_context` live operation. A failed attempt leaves prior events and the
model-input head unchanged, then flows through the command Run's retry/finalization boundary without
writing a per-attempt compaction marker.

## Token Estimation and Filters

Automatic compaction does not re-estimate the full event transcript when provider usage is
available. It uses the latest turn marker usage as the accounted prefix and estimates only the event
delta after that marker. The estimator computes model-visible byte cost first and converts it with
`ceil(bytes / 4)`. It excludes storage metadata, native artifacts, event IDs, timestamps, and schema
fields, and counts only user/assistant text, client tool call name plus its model-visible argument
projection, client tool result text, provider-tool semantic transcripts, compaction summary text, and
bounded file/attachment/artifact metadata that can reach model input. JSON-function calls contribute
their arguments. Plaintext-custom calls contribute a fixed omission marker instead of their custom
input, so that input neither affects automatic-compaction accounting nor enters the summary-model input,
generated checkpoint, or continuity projection. Provider call events use the same deterministic semantic renderer
as model lowering, including input, textual output, typed references, optional excerpts, canonical
file/attachment metadata, and stable sorted metadata; native artifact JSON is never counted.

Before lowering model input, event pre-lower filters may update attachment/file availability projections and
run automatic compaction. They do not run Artifact, ExchangeFile, or ModelFile cleanup; file cleanup is
scheduler-owned. They do not omit old tool outputs for context pressure. Adapter-native request guards
run after lowering and do not mutate DB state.

## Summary Enrichment Hooks

After summary generation succeeds, the runtime dispatches the `on_compaction_summary` hook pipeline
to active toolkit providers. The hook context receives the current summary and the rendered continuity
history as separate strings, plus compaction/session/run metadata. Hook results may replace the current
summary. Providers that want additive behavior append to `context.summary` and return the full
replacement summary. Hook exceptions fail open: the runtime records hook failure telemetry and keeps
the current summary so compaction can continue. Toolkit implementations are not required to register
this hook.

The hook pipeline may only replace the summary portion. The runtime always appends continuity history
after the pipeline completes, so toolkit enrichment can be inserted between the model-generated
checkpoint and continuity, while continuity remains last in the stored `compaction_summary` content.
Todo Toolkit uses this hook to append a readable `Todo Snapshot` section when the session Todo list is
non-empty; it does not render a Todo section for empty state. Goal Toolkit uses the same hook to
append a readable `Goal Snapshot` section when the session Goal is unfinished and non-empty; it does
not render a Goal section for empty or completed state.

When the completed summary is lowered for the next model turn, its compaction reminder directs the
agent to combine the latest user messages and Goal Snapshot into the current objective, and current
repository/tool observations, recent tool results, and Todo Snapshot into the execution stage. The
agent starts from the furthest completed and verified progress and continues with the next unfinished
action.

## Continuity Events

After summary enrichment completes, the event compactor appends bounded continuity excerpts to the
summary payload content. This is not a separate raw tail in the event transcript. Future model input
starts at the summary event, and the continuity excerpts are part of that summary event's
model-visible text.

The `Recent User Messages` section contains the last five direct user-input events
from the selected transcript: ordinary `user_message` events and External Channel
messages whose `prompt_role` is `invocation`. External Channel context messages do
not enter this section. Selection is independent from recent model-turn boundaries
so a long tool-heavy request can still surface the user's latest requests even when
the recent transcript window contains no user messages. Items are numbered without
repeating a per-item user-message label.

The `Recent Transcript` section uses `turn_marker` events as completed model-turn
boundaries. It includes events after the marker preceding the last five completed turns. If five or
fewer completed turns exist, or if no turn marker exists, it falls back to all selected events. Each
excerpt is rendered as concise, readable model-visible transcript text rather than event storage JSON.
Transcript labels stay short (`User`, `Assistant`, `Tool call`, `Tool result`), and client tool
results render only their model-visible output rather than wrapper fields such as
`function_call_output`, `call_id`, or `output`. Provider-tool calls render their canonical semantic input, output, and typed references through the
shared deterministic renderer; output parts contribute bounded file/attachment/artifact metadata
through that rendering. The projection family matches token
estimation: user/assistant text, client tool call name/arguments, client tool result text,
provider-tool semantic transcripts, compaction summary reminders, system reminders, and bounded
file/attachment/artifact metadata. Event IDs, timestamps, native artifacts, event kind, and
storage-only metadata are not included.

For plaintext-custom client calls, the continuity call-argument slot is the same fixed omission marker
used by token estimation. The corresponding result remains ordinary bounded model-visible result text.
Compaction does not rewrite durable call events, select a different dialect, or make a custom call
executable on a later incompatible route.

Each user-message or transcript excerpt is truncated independently to 2,000 estimated tokens.
Truncation is marked inline with `[Event truncated by Azents continuity guard.]`. This prevents a
single large tool output from surviving compaction as an unbounded raw event while still preserving
the immediate shape of the recent interaction.

## Invariants

- Compaction is append-only: success atomically appends one adjacent marker/summary pair; failure or cancellation appends no compaction lifecycle event.
- Successful compaction resets only the Session's `tool_search/working_set` in the marker/summary/head transaction. A skipped or unsuccessful attempt preserves that working set, and all other Toolkit State remains unchanged.
- External summary generation and enrichment run before the successful commit transaction opens and do not hold a Session row lock.
- Events appended during external summary work make the plan stale; the attempt writes no marker or summary and leaves the model-input head unchanged.
- Summary failure or cancellation leaves the model-input head unchanged.
- Successful compaction writes the trigger reason to both `compaction_marker.payload.reason` and `compaction_summary.payload.reason` so context/debug views can explain why the checkpoint was created.
- `model_input_head_event_id` points at the summary event after successful compaction.
- Future model input is selected and sorted by event ID.
- Auto and manual compaction present future model input as one `compaction_summary` head event.
- The summary model receives the full supported summary projection of the selected
  transcript, without a protected tail; External Channel projection includes only
  invocation-role messages.
- Compaction summary hooks may replace only the summary portion; continuity history is appended after
  hook dispatch completes.
- Todo summary enrichment appends a `Todo Snapshot` section only when Todo state is non-empty.
- Goal summary enrichment appends a `Goal Snapshot` section only for unfinished non-empty Goal state.
- Scheduled summary enrichment replaces one bounded Scheduled Task section with
  sanitized current started-cycle snapshots in deterministic order. It omits
  admitted and terminalized cycles and does not mutate Toolkit State.
- The stored summary content includes a bounded `Recent User Messages` section from
  the last five ordinary user messages or External Channel invocations and a bounded
  `Recent Transcript` section from the last five completed model turns, using
  `turn_marker` boundaries.
- Continuity sections are always the last sections in the stored compaction summary content.
- Each continuity excerpt is rendered as readable model-visible transcript text, not event storage JSON.
- Provider-tool call continuity and token estimates use the same canonical semantic renderer and never parse native artifacts.
- Each continuity excerpt is independently truncated before it is embedded in the summary.
- Auto, manual, and fallback compaction share the same summary prompt and budget policy.
- Manual compaction uses the command run context when dispatching session compaction and summary enrichment hooks.
- Automatic and manual compaction expose one Run-scoped `preparing_context` live operation whose identity remains stable across retry and is removed at every terminal boundary.
- Every classified provider-attributed compaction failure uses the common bounded failure contract and the owning Run's full retry budget; unclassified provider outcomes are internal errors and do not enter provider retry state.
- Summary model calls use watched streaming transport without publishing user-facing deltas. OpenAI
  API-key and ChatGPT OAuth omit API-level `max_output_tokens`; non-migrated providers receive the
  dynamic summary budget through the LiteLLM helper.
- Summary content is bounded by the runtime char guard after the model returns.
- UI/audit history continues to include pre-compaction events. ModelFile GC may later delete unpinned ModelFile blobs whose single FilePart event is behind the head cursor, but it does not delete events or history metadata.
- Legacy SDK compaction packages are not part of production compaction.

## External Channel Continuity

All External Channel messages participate in model-visible token estimation and
bounded Recent Transcript continuity through their explicit source rendering.
Only messages whose `prompt_role` is `invocation` participate in summary-model
input and the bounded Recent User Messages section. Source rendering retains
provider, resource, sender, prompt role, and safe body instead of converting the
item to a direct Web-user message. Provider credentials, raw envelopes, and
arbitrary permalink Markdown are never included.

The immutable revision projected into a run remains the compaction input even
when provider-current state later changes. Corrections appear only when a later
authorized batch appends the corresponding revision event.

## Scheduled Task Continuity

Scheduled Toolkit enriches the generated summary before continuity history is
appended. It removes any stale Scheduled Task section and inserts current started
cycles ordered by their stable cycle state. Each entry retains only the title,
objective, schedule, scheduled instant, progress title, and ordered work items
needed to continue autonomously. Internal Task, cycle, Run, lease, Binding, and
provider-message identities are omitted.

The enricher reads the current Session-scoped cycle Toolkit State and creates no
new durable authority. Task deletion, Session archive, or Binding disconnect does
not remove a preserved started cycle from the summary until that cycle
terminalizes.

## Changelog

- **2026-09-01** (spec_version 38) — Removed the deleted event model-order field
  from the continuity projection metadata exclusions.
- **2026-09-01** (spec_version 37) — Included External Channel invocation-role
  messages in compaction summary input and the mixed-source last-five Recent User
  Messages continuity selection while keeping context-role messages out of both.
- **2026-08-31** (spec_version 36) — Made event ID the only compaction order and
  replaced logical summary insertion with head-and-tail stale-plan validation.
- **2026-08-27** (spec_version 35) — Added distinct model default and maximum input
  windows, maximum-only fallback, and centralized per-option user-cap resolution
  before the smaller main/lightweight compaction calculation.
- **2026-08-16** (spec_version 34) — Added deterministic sanitized Scheduled Task
  started-cycle summary replacement before bounded continuity history.

- **2026-08-03** (spec_version 33) — Increased dynamic summary output headroom to 8% with a 50k-character limit and made checkpoint detail scale with task complexity without imposing a fixed target length.
- **2026-08-03** (spec_version 32) — Reframed compaction output as an execution-ready general-agent checkpoint that reconstructs the current objective and furthest verified execution state.
- **2026-07-22** (spec_version 31) — Added source-attributed External Channel compaction input, token estimation, continuity rendering, and immutable revision semantics.

- **2026-07-21** (spec_version 30) — Omitted plaintext-custom client-tool input from compaction accounting and continuity while retaining bounded result continuity.
- **2026-07-20** (spec_version 29) — Reset the Session Tool Search working set in the successful compaction transaction while preserving it on skipped or unsuccessful attempts.
- **2026-07-19** (spec_version 28) — Updated compaction rendering and token estimation for one durable provider call with canonical output-part metadata.

- **2026-07-18** (spec_version 27) — Added provider-tool semantic input, output, and reference rendering
  to summary input, bounded continuity, and model-visible token estimation without native-artifact
  parsing.
- **2026-07-18** (spec_version 26) — Routed unclassified compaction provider outcomes through
  internal-error handling instead of provider retry state.
- **2026-07-18** (spec_version 25) — Deferred the adjacent compaction marker/summary pair until one
  successful commit, projected one stable context-preparation operation, and routed every
  provider-attributed automatic or manual compaction failure through the owning Run's full retry budget.
