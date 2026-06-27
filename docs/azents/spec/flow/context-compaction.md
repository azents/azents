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
last_verified_at: 2026-06-27
spec_version: 12
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
2. Select the transcript slice that will be summarized.
3. For automatic compaction, split the slice into:
   - older events that are summarized; and
   - preserved tail turns that must remain raw in the next model input.
4. Generate the summary from only the summarized older events.
5. Append `compaction_summary` with the same `compaction_id` and reason.
6. Move `agent_sessions.model_input_head_event_id` and `agent_sessions.model_input_head_model_order` to the summary event.
7. For automatic compaction, assign the summary an intermediate model order before the preserved tail
   so the future model input reads as `compaction_summary` followed by the preserved raw tail. The
   preserved tail keeps its existing model order when a gap is available.

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

Automatic compaction does not include preserved tail turns in the summary request. The preserved tail
remains available as raw events after the summary in model order, which prevents duplicate
knowledge between summary text and raw tail events. The prompt explicitly tells the model not to
duplicate preserved tail content, while still preserving durable state from the compacted transcript.

Previous compaction summaries are rendered as existing checkpoints and are integrated into one updated
checkpoint. The prompt tells the model not to copy previous checkpoints verbatim, to drop obsolete
details unless needed to continue, and to prefer the latest transcript evidence on conflict.

Manual compaction and fallback compaction use the same prompt and budget policy as automatic
compaction. They keep the full selected compaction slice behavior and do not preserve a separate raw
tail. If summary generation fails, the runtime records the failure path and keeps recent context under
the fallback budget rather than deleting prior events.

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

## Invariants

- Compaction is append-only.
- Successful compaction writes the trigger reason to both `compaction_marker.payload.reason` and `compaction_summary.payload.reason` so context/debug views can explain why the checkpoint was created.
- `model_input_head_event_id` points at the event summary event after successful compaction, and `model_input_head_model_order` stores the same head event model order for scheduler GC cursor comparisons.
- Future model input is selected and sorted by event model order, not by physical append id.
- Automatic compaction presents model input as `compaction_summary` followed by preserved raw tail
  turns.
- Preserved tail turns are excluded from automatic compaction summaries.
- Manual compaction and fallback compaction do not preserve a separate raw tail.
- Auto, manual, and fallback compaction share the same summary prompt and budget policy.
- Summary model calls are non-streaming and carry API-level `max_output_tokens`.
- Summary content is bounded by the runtime char guard after the model returns.
- UI/audit history continues to include pre-compaction events. ModelFile GC may later delete unpinned ModelFile blobs whose single FilePart event is behind the head cursor, but it does not delete events or history metadata.
- Legacy SDK compaction packages are not part of production compaction.
