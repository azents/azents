---
title: "ADR-0043: Generate Compaction Summary as Codex-like Handoff Checkpoint"
created: 2026-05-30
tags: [architecture, backend, engine]
---

# ADR-0043: Generate Compaction Summary as Codex-like Handoff Checkpoint

## Status

Accepted.

## Context

Azents canonical runtime replaces old model input with `compaction_summary` in long-running sessions. After ADR-0042, auto compaction preserves tail as raw events, and summary replaces only the compacted range.

Next, summary quality and size control become important. Existing prompt is closer to a conversation summary, and in OpenAI/ChatGPT OAuth Responses calls, `max_output_tokens` is omitted due to streaming path. In this state, summary can become too long, or branch/PR/file/test/error/current-state information needed for the next agent to continue may not be preserved structurally.

The user wants a Codex-like strategy. The core idea is to treat compaction summary not as a user-visible answer or conversation narrative, but as a durable handoff checkpoint that lets the next agent/model step continue work without rereading the compacted transcript.

## Decision

Compaction summary generation follows these policies.

1. Summary model call does not stream.
   - Compaction is internal checkpoint generation, not a user-facing response.
   - Use a non-stream call, receive the full output, then apply token/char guard.
2. Pass `max_output_tokens` to Responses API/LiteLLM calls.
   - Apply API-level cap that was omitted in the existing OpenAI/ChatGPT OAuth streaming path.
3. Summary output budget is dynamically calculated from model context window.
   - `target_chars = context_window_tokens * 0.03 * 4`
   - `limit_chars = context_window_tokens * 0.05 * 4`
   - Apply nearest rounding to 1000.
   - Clamp `target_chars` to 12k~24k chars.
   - Clamp `limit_chars` to 16k~32k chars.
   - Calculate `max_output_tokens = limit_chars // 4`.
   - If context window is unknown, fallback to 128k tokens.
4. Runtime char guard does not use `limit_chars` as immediate hard cut.
   - Allow up to `truncate_chars = ceil_to_1000(limit_chars * 1.1)`.
   - Output beyond `truncate_chars` is simply truncated and gets a truncation note.
   - Section-aware truncation and resummarization retry are not included in the initial implementation.
5. Prompt switches to Codex-like durable handoff checkpoint format.
   - Generate future agent continuation state, not conversation summary.
   - Prefer concise bullets and do not unnecessarily fill budget.
   - Do not generate user-facing answer or continue the task.
   - Do not guess; mark uncertain content as `Needs verification`.
   - Do not preserve full logs; keep only command, result, error, path, ID, and conclusion needed for handoff.
6. Previous summaries are treated as existing checkpoints.
   - New summary integrates previous checkpoints and compacted transcript into one latest checkpoint.
   - Do not copy previous summary verbatim.
   - Remove obsolete detail and prioritize latest transcript evidence.
7. Auto/manual/fallback compaction use the same prompt and budget policy.
   - Only input range and whether preserved tail exists remain different.

## Considered Options

### Keep streaming

Existing OpenAI/ChatGPT OAuth Responses path uses streaming. Keeping it reduces changes, but compaction is not user-facing streaming, and the compatibility workaround that omitted `max_output_tokens` would remain. Non-stream is also simpler for validating the whole summary and applying char guard. Rejected.

### Fixed output size

Fixed values such as `target=16k`, `limit=24k` are simple, but treat small-context and large-context models with the same recurring summary cost. The user chose dynamic calculation. Fixed values remain only as fallback/clamp outcome.

### Base calculation on effective input budget

We could calculate from the input budget actually used by Azents runtime in one turn. However, for first implementation, model context window is simpler and directly tied to model capability. Effective input budget calculation remains future optimization.

### Section-aware truncation or resummarization retry

Section-aware truncation preserves structure better, and retry can improve quality. But initial implementation uses API token cap plus generous 10% char tolerance, so simple truncate is sufficient. Rejected to avoid adding cost, latency, and failure paths.

### Separate budgets for auto/manual/fallback

Manual compaction could be a larger handoff, or fallback could be smaller. But branching prompt/budget policy in first implementation increases test and operation surface. Keep only input range and preserved tail policy different; unify prompt/budget.

## Consequences

- Summary generation has deterministic guards suited for internal checkpoint creation.
- API-level output cap can be used in OpenAI/ChatGPT OAuth compaction too.
- Summary has enough room to be useful, while context-window-based clamp and truncate guard limit recurring context cost.
- Summary format changes from narrative summary to structured checkpoint.
- Repeated compaction integrates previous summaries into one latest checkpoint rather than accumulating verbatim copies.
- Non-stream Responses compatibility must be verified mainly on OpenAI/ChatGPT OAuth path during implementation.
