---
title: "Codex-like Compaction Checkpoints"
created: 2026-05-30
updated: 2026-05-30
implemented: 2026-05-30
tags: [backend, engine]
---

# Codex-like Compaction Checkpoints

## Source Documents

- [ADR-0042: Model input after compaction is rearranged in logical event order](../adr/0042-compaction-logical-event-ordering.md)
- [ADR-0043: Generate compaction summary as Codex-like handoff checkpoint](../adr/0043-codex-like-compaction-checkpoints.md)
- [Context Compaction spec](../spec/flow/context-compaction.md)

## Problem Background

Azents canonical runtime replaces old canonical transcript with `compaction_summary` to support long-running agent session. After ADR-0042, auto compaction keeps preserved tail as raw canonical events and summary replaces only compacted older range.

Remaining problem is quality and size control of summary itself. Existing compaction prompt is strongly conversation-summary shaped. Long-running coding agent structurally needs branch, PR, file, command, verification, decision, pending work, and blocker information so next agent/model step can continue without rereading compacted transcript.

Also, current OpenAI/ChatGPT OAuth Responses compaction call uses streaming path and omits `max_output_tokens`. It is hard to prevent summary output explosion at model call level, and there is no char guard before storage.

## Goals

- Make compaction summary a Codex-like durable handoff checkpoint.
- Remove streaming from compaction summary generation and pass `max_output_tokens`.
- Dynamically calculate summary output budget based on model context window.
- Limit stored summary size with runtime char guard.
- Integrate/update previous summary as existing checkpoint.
- Make auto/manual/fallback compaction share same prompt and budget policy.

## Non-goals

- Do not change compaction trigger threshold.
- Do not change auto compaction preserved tail ordering policy.
- Do not include section-aware truncation or LLM re-summary retry in first implementation.
- Do not give manual compaction separately larger budget.
- Do not change FE/history ordering.

## Current State

- `engine/compaction.py` owns summary prompt and LiteLLM Responses call.
- OpenAI/ChatGPT OAuth provider uses Responses streaming path.
- In OpenAI/ChatGPT OAuth provider, `max_output_tokens` is intentionally treated as `None`.
- `CanonicalCompactor` has default `summary_max_tokens=4_000`.
- Auto compaction separates compacted older range and preserved tail.
- Preserved tail is excluded from summary input and kept as raw events after summary.

## Target State

### Summary generation call

Compaction summary generation uses non-stream Responses call.

```python
stream = False
max_output_tokens = budget.max_output_tokens
```

Streaming response extraction may remain in normal agent response path, but is not used in compaction summary generation path.

### Summary budget

Budget is calculated based on model context window.

```text
target_chars = round_to_1000(context_window_tokens * 0.03 * 4)
limit_chars = round_to_1000(context_window_tokens * 0.05 * 4)

target_chars = clamp(target_chars, 12_000, 24_000)
limit_chars = clamp(limit_chars, 16_000, 32_000)

max_output_tokens = limit_chars // 4
truncate_chars = ceil_to_1000(limit_chars * 1.1)
```

If context window is unknown, use 128k tokens as fallback.

### Runtime truncation

If summary is at or below `truncate_chars`, store as-is. If it exceeds `truncate_chars`, simply truncate and append this note.

```text
[Truncated by Azents compaction guard.]
```

Do not perform section-aware truncate or retry.

### Prompt shape

Prompt asks for durable handoff checkpoint instead of conversation summary.

Required sections:

```md
## Goal
## Durable Instructions
## Current State
## Completed Work
## Pending Work
## Decisions and Rationale
## Relevant Files and Symbols
## Verification
## External References
## Notes for Next Agent
```

Prompt explicitly states:

- Do not create user-facing answer.
- Do not continue the task.
- Do not fill budget unnecessarily.
- Prefer concise bullets.
- Do not guess.
- Mark uncertain items as `Needs verification`.
- Do not include full logs.
- For tool result, keep only command, outcome, error, path, ID, conclusion needed for handoff.
- Preserved tail can remain separately as raw events, so do not duplicate it.
- Do not omit durable state from compacted transcript just because tail exists.

### Previous checkpoint handling

Compaction summary event is shown as existing checkpoint when rendering. Prompt instructs not to verbatim copy previous summary, but integrate/update it into latest checkpoint.

If latest transcript and previous summary conflict, prioritize latest transcript evidence.

## User-visible Behavior

This change does not aim to directly change UI text. User-visible effect is that after compaction in long-running session, agent more reliably continues previous work state.

## Data/State/API Impact

- No DB schema change.
- Text format stored in `compaction_summary.content` changes to Codex-like checkpoint.
- `compaction_summary` payload structure is preserved.
- Summary generation logging may include budget values and truncation status.

## Operational Prerequisite

- OpenAI/ChatGPT OAuth provider must work with non-stream Responses call plus `max_output_tokens` combination.
- If provider compatibility problem is found, use existing compaction failure path. First implementation does not add provider-specific retry fallback.

## Rollout / Failure Modes

- If non-stream call fails on provider, compaction summary generation fails. Follows existing compaction failure handling.
- If model returns summary longer than limit, runtime guard truncates.
- Truncated summary includes note so next agent can recognize potential incompleteness.
- Include instruction “do not fill the budget unnecessarily” to avoid prompting overly long output.

## Test Strategy

### Unit / component checks

- Verify budget calculation function returns expected values for 32k, 128k, 200k, and unknown context window.
- Verify 1000-unit rounding and clamp are applied.
- Verify `truncate_chars` is `limit_chars * 1.1` rounded up to 1000-unit.
- Verify summary exceeding `truncate_chars` is simply truncated with note.
- Verify summary slightly exceeding `limit_chars` but below `truncate_chars` is not truncated.
- Verify summary call passes `stream=False` and `max_output_tokens`.
- Verify prompt includes Codex-like checkpoint instructions and required sections.
- Verify previous summary rendering label means existing checkpoint.

### E2E primary verification

This feature spans model summary quality and provider compatibility. In deterministic E2E, rather than verifying actual LLM quality, verify compaction path uses calculated budget and non-stream summary call, and summary event is created.

- In canonical runtime compaction scenario, use summary generator spy/fake to verify `max_output_tokens`, target/limit/truncate chars delivery.
- After auto compaction, confirm preserved tail is excluded from summary input and existing regression that raw tail remains in model input after summary event.
- Verify manual/fallback compaction uses same budget/prompt policy at unit/component level.

### testenv fixture/prerequisite support

No new external credential fixture is required. Provider live compatibility is not required CI condition; fake/spy-based deterministic verification is primary.

## Acceptance Criteria

- Compaction summary call is called non-stream.
- `max_output_tokens` uses `max_output_tokens` from dynamic budget.
- Budget is calculated based on model context window, with 1000-unit rounding, clamp, and truncate tolerance applied.
- Unknown context window uses 128k fallback.
- If summary output exceeds truncate threshold, it is simply truncated with note.
- Prompt requires Codex-like handoff checkpoint format.
- Previous summary is instructed to be integrated/updated as existing checkpoint.
- Auto/manual/fallback use same prompt and budget policy.
- Related spec is updated to current behavior after implementation.

## QA Checklist

### QA 1: Budget calculation

- What to check: target/limit/max output/truncate values per context window are calculated as designed.
- Why it matters: summary output size must scale with model size and recurring context cost must not explode.
- How to check: run budget calculation unit test.
- Expected result: 32k, 128k, 200k, unknown context window cases all return expected values.
- Execution result: PASS — `cd python/apps/azents && uv run pytest src/azents/engine/compaction_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` (32 passed, 3 deprecation warnings from testcontainers).
- Fixes applied: None.

### QA 2: Non-stream summary call

- What to check: compaction summary generation passes `stream=False` and `max_output_tokens`.
- Why it matters: API-level output cap works and compaction output guard becomes simpler.
- How to check: run summary model call spy/fake test.
- Expected result: compaction call kwargs follow non-stream policy for providers including OpenAI/ChatGPT OAuth.
- Execution result: PASS — `cd python/apps/azents && uv run pytest src/azents/engine/compaction_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` (32 passed, 3 deprecation warnings from testcontainers).
- Fixes applied: None.

### QA 3: Runtime char guard

- What to check: if summary output exceeds truncate threshold, it is simply truncated with note.
- Why it matters: Even with provider/tokenization difference, excessive summary must not be stored in DB and future model input.
- How to check: run unit test returning long fake summary.
- Expected result: output below threshold is kept, output above threshold is stored within threshold including note.
- Execution result: PASS — `cd python/apps/azents && uv run pytest src/azents/engine/compaction_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` (32 passed, 3 deprecation warnings from testcontainers).
- Fixes applied: None.

### QA 4: Codex-like prompt

- What to check: prompt requires durable handoff checkpoint format and required sections.
- Why it matters: long-running agent must be able to continue work without compacted transcript.
- How to check: inspect prompt constant/unit test and representative generated prompt.
- Expected result: prompt includes no user answer, no task continuation, concise durable state, previous checkpoint integration, tail duplication guard.
- Execution result: PASS — `cd python/apps/azents && uv run pytest src/azents/engine/compaction_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` (32 passed, 3 deprecation warnings from testcontainers).
- Fixes applied: None.

### QA 5: Compaction regression

- What to check: auto compaction excludes preserved tail from summary input, and model input keeps summary followed by raw tail.
- Why it matters: previous compaction ordering fix must not regress due to prompt/limit improvement.
- How to check: run canonical compaction tests.
- Expected result: existing preserved tail regression test continues to pass.
- Execution result: PASS — `cd python/apps/azents && uv run pytest src/azents/engine/compaction_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` (32 passed, 3 deprecation warnings from testcontainers).
- Fixes applied: None.
