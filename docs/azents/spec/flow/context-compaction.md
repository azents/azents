---
title: "Context Compaction"
created: 2026-05-10
tags: [backend, engine]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
code_paths:
  - python/apps/azents/src/azents/engine/context/compaction.py
  - python/apps/azents/src/azents/engine/context/window.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/hooks/**
  - python/apps/azents/src/azents/engine/run/commands.py
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/agent.py
last_verified_at: 2026-07-16
spec_version: 23
---

# Context Compaction

Context compaction keeps long session history within model input limits without deleting audit/UI
history. The event runtime uses append-only compaction.

Automatic compaction effective context window is computed by
`engine/context/window.py:compute_effective_context_window_tokens()`. For each prepared inference-bearing input, runtime takes the prompt-selected foreground option's capability-clamped context cap and the Agent lightweight option's capability-clamped context cap, then uses the smaller value as `effective_max_input_tokens`.
An option context cap is stored as intent and may be larger than its current model limit; the model
limit still wins. Effective lightweight resolution uses the Agent's stored lightweight option model
snapshot and settings. Workspace defaults are copied into the Agent only at create time and are not read
by runtime compaction. Automatic compaction threshold is then computed by
`compute_auto_compaction_threshold_tokens()` as `int(effective_max_input_tokens * 0.9)`. Both values are stored in the current `AgentSession` inference snapshot and remain fixed for that prepared turn, automatic retry, and recovery. A later prepared profile may replace them at the next turn boundary, including within the same active run. The event runtime uses this Session-owned calculation as the compaction trigger source of truth and compares the threshold against the latest turn marker `usage.prompt_tokens` plus the
model-visible token estimate for events appended after that marker. If no turn marker exists, it falls
back to estimating the full selected transcript.

## Behavior

When compaction is required:

1. Select the full model-input transcript slice and fixed cutoff that will be summarized.
2. In a short database session, append `compaction_marker` with a new `compaction_id` and a durable reason (`auto_threshold_exceeded` for automatic compaction, `manual_command` for explicit `/compact`). Commit the marker and reserve the immediately adjacent logical order for the summary.
3. Close the marker persistence session before dispatching the compaction-start lifecycle hook or generating and enriching the summary. The external model and hook calls run outside compactor-owned database sessions and hold no active transaction or session-row lock used for event ordering.
4. Render bounded continuity history from the selected transcript, but keep it separate from the generated summary.
5. Dispatch the compaction summary enrichment hook pipeline with the generated summary and rendered continuity history.
6. Append the continuity history after the enriched summary.
7. In another short database session, append `compaction_summary` at the reserved logical order with the same `compaction_id` and reason. The payload content contains the enriched checkpoint followed by bounded `Recent User Messages` and `Recent Transcript` sections.
8. Move `agent_sessions.model_input_head_event_id` and `agent_sessions.model_input_head_model_order` to the summary event and commit that transaction.
9. If summary generation or enrichment fails or is cancelled, append and commit a terminal failed/cancelled marker in a separate short database session without moving the model-input head.

Old events remain queryable. The head pointer and event model order only change which
event range and ordering are used for future model input. Sequential appends leave gaps in
`model_order` so compaction can reserve the summary immediately after its marker without renumbering
the whole session transcript. Input appended while summary generation is running receives a later
logical order, remains outside the fixed summary cutoff, and stays visible after the summary head.

## Summary Model

Summary generation is routed by provider from `engine/context/compaction.py`. OpenAI API-key and
ChatGPT OAuth use an operation-scoped official OpenAI SDK client; other providers use the shared
LiteLLM Responses helper. The compaction model is resolved from the Agent lightweight option
snapshot. Its model-scoped context cap participates in the effective input window, while its
model-scoped `max_output_tokens` and built-in tools do not replace internal compaction request policy.

Compaction summary generation is not user-facing streaming output, although the transport uses a
stream so the common watchdog can enforce parsed-event idle and absolute attempt deadlines. The
standard OpenAI-compatible helper sends ordinary user input plus top-level instructions and omits
`max_output_tokens`; it does not use sampling continuation or Responses Lite. ChatGPT OAuth also
uses complete input, `store=false`, encrypted reasoning inclusion, and no `previous_response_id`.
Non-migrated providers receive `max_output_tokens` from the dynamic summary budget through the
LiteLLM helper. The summary budget is based on the model context window:

- target summary chars: 3% of context window tokens, converted with 1 token ≈ 4 chars;
- limit summary chars: 5% of context window tokens, converted with 1 token ≈ 4 chars;
- target chars are nearest-rounded to 1000 chars and clamped to 12k–24k chars;
- limit chars are nearest-rounded to 1000 chars and clamped to 16k–32k chars;
- `max_output_tokens = limit_chars // 4`;
- unknown context windows use a 128k token fallback.

The runtime char guard allows a 10% tolerance over `limit_chars`. It computes
`truncate_chars = ceil_to_1000(limit_chars * 1.1)`. If a model returns more than `truncate_chars`, the
runtime performs a simple deterministic truncate and appends `[Truncated by Azents compaction guard.]`.
The runtime does not perform section-aware truncation or retry-based re-summarization.

The summary prompt asks for a Codex-like durable handoff checkpoint, not a narrative conversation
summary. It requires structured sections for goal, durable instructions, current state, completed
work, pending work, decisions, relevant files/symbols, verification, external references, and notes
for the next agent. The prompt also tells the model not to answer the user, not to continue the task,
not to fill the budget unnecessarily, not to invent details, and to mark uncertain items as
`Needs verification`.

Auto and manual compaction include the full selected transcript in the summary request. The summary
prompt asks for durable state from the whole compacted transcript and warns that no raw event should
be assumed to remain available outside the checkpoint. After the model returns the checkpoint, the
runtime renders bounded continuity history separately, dispatches compaction summary enrichment hooks,
and then appends the continuity history to the stored summary content.

Previous compaction summaries are rendered as existing checkpoints and are integrated into one updated
checkpoint. The prompt tells the model not to copy previous checkpoints verbatim, to drop obsolete
details unless needed to continue, and to prefer the latest transcript evidence on conflict.

Manual compaction uses the same prompt, budget policy, continuity event policy, and summary
enrichment pipeline as automatic compaction. Manual compaction runs inside a `RunContext`, dispatches
`on_session_compact` with that run id, and passes the same run id to `on_compaction_summary`. If
summary generation fails, the runtime records the failure path and keeps recent context under the
fallback budget rather than deleting prior events.

## Token Estimation and Filters

Automatic compaction does not re-estimate the full event transcript when provider usage is
available. It uses the latest turn marker usage as the accounted prefix and estimates only the event
delta after that marker. The estimator computes model-visible byte cost first and converts it with
`ceil(bytes / 4)`. It excludes storage metadata, native artifacts, event IDs, timestamps, and schema
fields, and counts only user/assistant text, tool call name/arguments, tool result text, compaction
summary text, and bounded file/attachment/artifact metadata that can reach model input.

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

## Continuity Events

After summary enrichment completes, the event compactor appends bounded continuity excerpts to the
summary payload content. This is not a separate raw tail in the event transcript. Future model input
starts at the summary event, and the continuity excerpts are part of that summary event's
model-visible text.

The `Recent User Messages` section contains the last five real `user_message` events
from the selected transcript. It is selected independently from recent model-turn boundaries so a long
tool-heavy request can still surface the user's latest requests even when the recent transcript window
contains no user messages. Items are numbered without repeating a per-item user-message label.

The `Recent Transcript` section uses `turn_marker` events as completed model-turn
boundaries. It includes events after the marker preceding the last five completed turns. If five or
fewer completed turns exist, or if no turn marker exists, it falls back to all selected events. Each
excerpt is rendered as concise, readable model-visible transcript text rather than event storage JSON.
Transcript labels stay short (`User`, `Assistant`, `Tool call`, `Tool result`), and client tool
results render only their model-visible output rather than wrapper fields such as `function_call_output`,
`call_id`, or `output`. The projection family matches token estimation: user/assistant text, tool call
name/arguments, tool result text, compaction summary reminders, system reminders, and bounded
file/attachment/artifact metadata. Event IDs, timestamps, native artifacts, event kind, model order,
and storage-only metadata are not included.

Each user-message or transcript excerpt is truncated independently to 2,000 estimated tokens.
Truncation is marked inline with `[Event truncated by Azents continuity guard.]`. This prevents a
single large tool output from surviving compaction as an unbounded raw event while still preserving
the immediate shape of the recent interaction.

## Invariants

- Compaction is append-only.
- External summary generation and enrichment run after the started-marker session closes and before the summary transaction opens; they do not hold the session-row event-ordering lock.
- Events appended during external summary work retain a later logical order than the reserved summary order and remain visible after the model-input head moves.
- Summary failure or cancellation records a committed terminal marker without moving the model-input head.
- Successful compaction writes the trigger reason to both `compaction_marker.payload.reason` and `compaction_summary.payload.reason` so context/debug views can explain why the checkpoint was created.
- `model_input_head_event_id` points at the event summary event after successful compaction, and `model_input_head_model_order` stores the same head event model order for scheduler GC cursor comparisons.
- Future model input is selected and sorted by event model order, not by physical append id.
- Auto and manual compaction present future model input as one `compaction_summary` head event.
- The summary model receives the full selected model-input transcript, not a transcript with a
  protected tail removed.
- Compaction summary hooks may replace only the summary portion; continuity history is appended after
  hook dispatch completes.
- Todo summary enrichment appends a `Todo Snapshot` section only when Todo state is non-empty.
- Goal summary enrichment appends a `Goal Snapshot` section only for unfinished non-empty Goal state.
- The stored summary content includes a bounded `Recent User Messages` section from
  the last five user messages and a bounded `Recent Transcript` section from the last
  five completed model turns, using `turn_marker` boundaries.
- Continuity sections are always the last sections in the stored compaction summary content.
- Each continuity excerpt is rendered as readable model-visible transcript text, not event storage JSON.
- Each continuity excerpt is independently truncated before it is embedded in the summary.
- Auto, manual, and fallback compaction share the same summary prompt and budget policy.
- Manual compaction uses the command run context when dispatching session compaction and summary enrichment hooks.
- Summary model calls use watched streaming transport without publishing user-facing deltas. OpenAI
  API-key and ChatGPT OAuth omit API-level `max_output_tokens`; non-migrated providers receive the
  dynamic summary budget through the LiteLLM helper.
- Summary content is bounded by the runtime char guard after the model returns.
- UI/audit history continues to include pre-compaction events. ModelFile GC may later delete unpinned ModelFile blobs whose single FilePart event is behind the head cursor, but it does not delete events or history metadata.
- Legacy SDK compaction packages are not part of production compaction.
