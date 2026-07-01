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
  - python/apps/azents/src/azents/engine/run/resolve.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/agent.py
last_verified_at: 2026-06-30
spec_version: 14
---

# Context Compaction

Context compaction keeps long session history within model input limits without deleting audit/UI
history. The event runtime uses append-only compaction.

Automatic compaction effective context window is computed by
`engine/context/window.py:compute_effective_context_window_tokens()`. The function takes the main model
input window and the effective lightweight/compaction model input window and uses the smaller value as
`effective_max_input_tokens`. Effective lightweight resolution uses the agent's stored `lightweight_model_selection`
snapshot. Workspace default is copied into the Agent only at create/update time and is not read by
runtime compaction. Automatic compaction threshold is then computed by
`compute_auto_compaction_threshold_tokens()` as `int(effective_max_input_tokens * 0.9)`. The event
runtime and API-facing token usage UI use this shared backend calculation as the source of truth, so
the displayed effective context window and percentage match the runtime trigger basis. The event
runtime compares that threshold against the latest turn marker `usage.prompt_tokens` plus the
model-visible token estimate for events appended after that marker. If no turn marker exists, it falls
back to estimating the full selected transcript.

## Behavior

When compaction is required:

1. Append `compaction_marker` with a new `compaction_id` and a durable reason (`auto_threshold_exceeded` for automatic compaction, `manual_command` for explicit `/compact`).
2. Select the full model-input transcript slice that will be summarized.
3. Generate the summary from the full selected transcript slice.
4. Select continuity excerpts from the last five completed model turns in the same selected transcript.
5. Truncate each continuity event excerpt independently before embedding it in the summary payload.
6. Append `compaction_summary` with the same `compaction_id` and reason. The payload content contains
   the generated checkpoint followed by a `Recent Events for Continuity` section.
7. Move `agent_sessions.model_input_head_event_id` and `agent_sessions.model_input_head_model_order` to the summary event.

Old events remain queryable. The head pointer and event model order only change which
event range and ordering are used for future model input. Sequential appends leave gaps in
`model_order` so compaction can assign intermediate logical positions without renumbering the whole
session transcript.

## Summary Model

Summary generation uses LiteLLM Responses API from `engine/context/compaction.py`. The compaction model is
resolved from the Agent `lightweight_model_selection` snapshot.

Compaction summary generation is not user-facing streaming output. The runtime calls the summary
model with `stream=False` and passes `max_output_tokens` from the dynamic summary budget. The summary
budget is based on the model context window:

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
runtime appends bounded `Recent User Messages for Continuity` and `Recent Transcript for Continuity`
sections to the stored summary content.

Previous compaction summaries are rendered as existing checkpoints and are integrated into one updated
checkpoint. The prompt tells the model not to copy previous checkpoints verbatim, to drop obsolete
details unless needed to continue, and to prefer the latest transcript evidence on conflict.

Manual compaction uses the same prompt, budget policy, and continuity event policy as automatic
compaction. If summary generation fails, the runtime records the failure path and keeps recent context
under the fallback budget rather than deleting prior events.

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

## Continuity Events

After summary generation succeeds, the event compactor appends bounded continuity excerpts to the
summary payload content. This is not a separate raw tail in the event transcript. Future model input
starts at the summary event, and the continuity excerpts are part of that summary event's
model-visible text.

The `Recent User Messages for Continuity` section contains the last five real `user_message` events
from the selected transcript. It is selected independently from recent model-turn boundaries so a long
tool-heavy request can still surface the user's latest requests even when the recent transcript window
contains no user messages.

The `Recent Transcript for Continuity` section uses `turn_marker` events as completed model-turn
boundaries. It includes events after the marker preceding the last five completed turns. If five or
fewer completed turns exist, or if no turn marker exists, it falls back to all selected events. Each
excerpt is rendered as readable model-visible transcript text rather than event storage JSON. The
projection family matches token estimation: user/assistant text, tool call name/arguments, tool
output text, compaction summary reminders, system reminders, and bounded file/attachment/artifact
metadata. Event IDs, timestamps, native artifacts, event kind, model order, and storage-only metadata
are not included.

Each user-message or transcript excerpt is truncated independently to 2,000 estimated tokens.
Truncation is marked inline with `[Event truncated by Azents continuity guard.]`. This prevents a
single large tool output from surviving compaction as an unbounded raw event while still preserving
the immediate shape of the recent interaction.

## Invariants

- Compaction is append-only.
- Successful compaction writes the trigger reason to both `compaction_marker.payload.reason` and `compaction_summary.payload.reason` so context/debug views can explain why the checkpoint was created.
- `model_input_head_event_id` points at the event summary event after successful compaction, and `model_input_head_model_order` stores the same head event model order for scheduler GC cursor comparisons.
- Future model input is selected and sorted by event model order, not by physical append id.
- Auto and manual compaction present future model input as one `compaction_summary` head event.
- The summary model receives the full selected model-input transcript, not a transcript with a
  protected tail removed.
- The stored summary content includes a bounded `Recent User Messages for Continuity` section from
  the last five user messages and a bounded `Recent Transcript for Continuity` section from the last
  five completed model turns, using `turn_marker` boundaries.
- Each continuity excerpt is rendered as readable model-visible transcript text, not event storage JSON.
- Each continuity excerpt is independently truncated before it is embedded in the summary.
- Auto, manual, and fallback compaction share the same summary prompt and budget policy.
- Summary model calls are non-streaming and carry API-level `max_output_tokens`.
- Summary content is bounded by the runtime char guard after the model returns.
- UI/audit history continues to include pre-compaction events. ModelFile GC may later delete unpinned ModelFile blobs whose single FilePart event is behind the head cursor, but it does not delete events or history metadata.
- Legacy SDK compaction packages are not part of production compaction.
