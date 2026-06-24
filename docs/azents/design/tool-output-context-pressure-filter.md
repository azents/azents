---
title: "Tool Output Context-Pressure Filter Design"
created: 2026-06-04
implemented: 2026-06-04
tags: [backend, engine, runtime]
---
# Tool Output Context-Pressure Filter Design

Related decision record: [ADR-0048: Adopt tool output context-pressure filter](../adr/0048-tool-output-context-pressure-filter.md)

## Overview

Azents removed existing `CanonicalObservationMaskingFilter`. That filter directly stored abbreviated old tool result output in canonical DB payload, so model input optimization could lead to durable history loss.

Based on Codex benchmarking, this design defines a method that preserves canonical history and replaces tool result output body with placeholder only in lowerer input transcript when model input exceeds context budget.

Core point is not a feature that always shrinks tool output. Abnormal output defenses already exist per tool. This feature is context-pressure filter that activates only when normal transcript accumulates and entire model input exceeds context budget.

## Problem Background

Problems with existing durable observation masking method were as follows.

1. It shrank old output regardless of context pressure.
2. It stored abbreviated result in canonical DB payload.
3. Compaction summary could see already degraded tool output.
4. It only targeted client tool result, so policy was inconsistent with provider-hosted tool output.
5. Responsibilities of per-tool abnormal output guard and model input context shaping were mixed.

Codex's important difference is separation of raw/canonical history and model-facing input. What is reduced to fit context window is model-facing input, not durable history. Also, in context pressure situation, only tool/function output body is replaced with placeholder while call id, status, and metadata are preserved.

## Goals

- Do not change canonical DB payload.
- Use existing `CanonicalPreLowerFilterPipeline`.
- Do not reduce tool output when there is no context pressure.
- When context pressure exists, replace only eligible tool result output body with placeholder.
- Handle `ClientToolResultPayload` and `ProviderToolResultPayload` together.
- Preserve structural metadata such as call id, tool name, status, attachments, provider native artifact.
- Run after auto compaction so compaction summary does not see placeholder transcript.
- Keep existing per-tool abnormal output defenses and `NativeRequestSizeGuard`.
- Use rough token estimate and model context window to determine context pressure.

## Non-goals

- Do not unify or redesign existing per-tool output limits.
- Do not add new per-output cap.
- Do not introduce tokenizer-based precise token counting.
- Do not trim user message, assistant message, reasoning, summary, system event.
- Do not solve context overflow of compaction request itself in this scope.
- Do not change AGENTS.md, skill, instruction promotion policy.
- Do not change history endpoint or live state API contract.

## Current State

Current canonical runtime already has pre-lower filter pipeline.

- `CanonicalPreLowerFilterPipeline` applies filters to canonical transcript in order before lowerer.
- Whether filter modifies DB or only in-memory transcript is responsibility of each filter implementation.
- Current pre-lower filters include attachment availability update, unavailable file part placeholder, auto compaction.
- After lowerer, post-lower filter and `NativeRequestSizeGuard` exist.
- `RunRequest` has `max_input_tokens` based on main model input and `effective_max_input_tokens` for compaction threshold calculation.
- `ClientToolResultPayload` and `ProviderToolResultPayload` both have `call_id`, `name`, `status`, `output`, `attachments`.
- `ProviderToolResultPayload` additionally has `native_artifact`.

After removing existing `CanonicalObservationMaskingFilter`, there is no path that durably stores abbreviated old tool output.

## Target State

Add new filter to `CanonicalPreLowerFilterPipeline`. Do not introduce new concept or separate projection pipeline.

Filter responsibilities are as follows.

- Calculate rough token estimate of lowerer input transcript.
- Calculate usable input budget by subtracting response reservation and safety margin from main model context window.
- If estimate is at or below budget, no-op.
- If estimate exceeds budget, replace output body of old eligible tool results with placeholder first.
- Stop immediately when replacement brings transcript within budget.
- Do not depend on canonical repository and do not modify canonical DB payload.
- If budget overflow still not resolved, return transcript shaped as much as possible, and let existing `NativeRequestSizeGuard` handle final hard failure.

## Execution Order

Pre-lower filter order has following target state.

1. `CanonicalAttachmentAvailabilityFilter`
2. `CanonicalFilePartPlaceholderFilter`
3. `CanonicalAutoCompactionFilter`
4. New tool output context-pressure filter

New filter is placed after auto compaction so compaction summary does not see transcript replaced with placeholder. Problem where compaction input itself overflows context is handled by follow-up design that applies this only to compaction request clone.

## Context Pressure Decision

Context pressure decision uses rough token estimate and model context window.

- Do not introduce tokenizer.
- Event token estimate uses char-based rough estimate in same family as existing canonical compaction.
- Since filter shapes main model lowerer input, use `RunRequest.max_input_tokens` first as budget source.
- `RunRequest.effective_max_input_tokens` returns smaller of compaction model and main model for compaction threshold, so do not use it as default budget for model-call context-pressure filter.
- Apply response reservation and safety margin.
- If model context window is unreliable, prefer no-op.

Response reservation policy final number is fixed in implementation feasibility. Principles are as follows.

- If `request.max_tokens` exists, use it as response reservation.
- If `request.max_tokens` absent, use context window ratio or bounded default.
- Keep separate safety margin considering rough estimate error.

## Applicable Targets

Context pressure trim target is model-visible tool result output family.

Included targets:

- `ClientToolResultPayload`
- `ProviderToolResultPayload`

Excluded targets:

- `UserMessagePayload`
- `AssistantMessagePayload`
- `ReasoningPayload`
- `ClientToolCallPayload`
- `ProviderToolCallPayload`
- `CompactionSummaryPayload`
- `CompactionMarkerPayload`
- `RunMarkerPayload`
- `TurnMarkerPayload`
- `SubagentStartPayload`
- `SubagentEndPayload`
- `SystemReminderPayload`
- `SystemErrorPayload`
- `UnknownAdapterOutputPayload`

This decision matches Codex and handles semantic unit of tool output, not client/provider distinction.

## Placeholder Replacement Policy

When context pressure occurs, replace eligible tool result output body with short model-facing placeholder.

Placeholder wording is in English.

`Tool output omitted from this model input because the available context budget was exceeded.`

This text goes into model input. Do not include explanation in default wording that original is preserved in canonical history. It can confuse model if it has no actual path to re-read original.

Replacement method:

- If output is string, replace entire output string with placeholder.
- If output is list, reduce text part to one placeholder.
- If list output has non-text part, preserve it by default.
- If output has no text part, do not change.

Payload fields to preserve:

- `call_id`
- `name`
- `status`
- `attachments`
- `native_artifact` for provider tool result

Event fields to preserve:

- `id`
- `session_id`
- `kind`
- `model_order`
- `external_id`
- `adapter`
- `provider`
- `model`
- `native_format`
- `schema_version`
- `created_at`

## Trim ordering

When context pressure occurs, replace placeholder from oldest eligible tool result in lowerer input transcript.

Rules:

- Oldest tool result by transcript order or `model_order` is targeted first.
- Stop immediately when within context budget.
- Do not add hard protection for recent N runs.
- Do not introduce large-output-first, composite score, or tool-specific ordering in first implementation.

This differs from existing masking. Existing masking reduced old output regardless of context pressure. New filter reduces old eligible output only when context pressure exists.

## Relationship with Existing Output Guard

Azents already has per-tool abnormal output defenses.

Examples:

- bash stdout/stderr tail truncate
- grep match limit
- Discord output limit
- AGENTS content truncation
- compaction summary char budget
- post-lower `NativeRequestSizeGuard`

New filter does not replace or integrate this layer. Existing per-tool guard prevents abnormal explosion before tool execution result enters transcript or during tool output formatting. New filter shapes lowerer input transcript only when normal transcript accumulates and entire model input exceeds context budget.

## Relationship with Compaction

New filter is placed after `CanonicalAutoCompactionFilter`. Therefore placeholder replacement is not applied to compaction summary generation input.

Problems not solved in this scope:

- compaction request itself exceeding compaction model context window

Follow-up design direction:

- Apply context-pressure shaping only to compaction request clone.
- Do not change canonical DB payload.
- Model-call input shaping and compaction-input shaping can share some primitive, but execution location and budget are separate.

## Failure mode

New filter does not directly raise hard failure.

- If no context pressure, no-op.
- If no eligible output, no-op.
- If placeholder replacement can fit budget, return shaped transcript.
- If still cannot fit budget after placeholder replacement, return transcript shaped as much as possible.
- Existing `NativeRequestSizeGuard` fails final request size overflow.

This responsibility split preserves existing guard role and lets new filter focus on best-effort model input shaping.

## User-visible behavior

General users do not configure this feature directly. In most runs without context pressure, behavior does not change.

In runs with context pressure, old tool result output body may be replaced with placeholder in model input. Original payload in canonical history and history API does not change.

Model can see placeholder and know that corresponding tool output body was omitted from this model input. call id, tool name, status are kept, so tool call/result structure is preserved.

## Data, API, Permission, Infrastructure Impact

No data model change.

No API contract change.

No permission change.

No infrastructure change.

No DB migration.

## Operational Prerequisite

No separate operational prerequisite.

However, model context window source must be accurate for context pressure decision to be meaningful. Feasibility check must confirm whether `RunRequest.max_input_tokens` is filled from model catalog/capabilities in resolve path.

## Feasibility Verification Result

After writing design draft, verified following items against code.

1. `PreLowerFilter` protocol requirements
   - Requires only `was_compacted: bool` and `apply(session, transcript)`.
   - New filter can set `was_compacted = False` and directly enter existing pipeline.

2. model input transcript ordering
   - `CanonicalTranscriptRepository.list_for_model_input()` returns by `model_order asc, id asc`.
   - If head event exists, returns events whose `model_order` is greater or equal to head event.
   - Fits policy of replacing oldest eligible output based on lowerer input transcript.

3. context window source
   - Resolve path fills main model `max_input_tokens` with `get_max_input_tokens()`.
   - Source order is capability contract → LiteLLM model info → `128_000` fallback.
   - `RunRequest.max_input_tokens` can be used as main model input budget.
   - `RunRequest.effective_max_input_tokens` is for compaction threshold, so do not use as new model-call filter budget.

4. response reservation
   - `RunRequest.max_tokens` is filled from model parameter.
   - When value absent, bounded default or context ratio is needed.
   - Constants are finalized in implementation plan stage.

5. output shape
   - `ClientToolResultPayload` and `ProviderToolResultPayload` have same `output` shape, so common helper can handle both.
   - `ProviderToolResultPayload.native_artifact` only needs preservation as payload field.

6. provider native replay path
   - `LiteLLMResponsesLowerer` checks compatible native artifact first.
   - However, current `_is_replayable_input_item()` allows only `type == "function_call"`.
   - Provider tool result goes through canonical output lowering path, so output placeholder replacement can be reflected in model input.

7. non-text part preservation
   - `FileOutputPart` lowers to rich input or placeholder content in lowerer.
   - `AttachmentOutputPart`, `ArtifactOutputPart` lower to bounded metadata text through `lower_output_to_text()`.
   - Preserving non-text part after text body replacement is compatible with current lowerer.

8. connection with existing guard
   - `NativeRequestSizeGuard` is in post-lower pipeline and can remain final request size guard.

Conclusion: no blocker in current code structure. Remaining detailed values are response reservation default and safety margin constants, which can be finalized with phase scope in implementation plan.

## Test Strategy

Product behavior verification is E2E/testenv primary. unit test, static check, type check are supporting implementation verification only and are not used alone as PASS evidence for QA Checklist.

E2E/testenv verification must use actual canonical runtime path.

Required evidence:

- execution command
- working directory
- fixture/seed description
- model context budget premise
- lowerer or model adapter input evidence
- canonical history payload evidence
- PASS judgment basis

CI policy:

- deterministic E2E/testenv path must be runnable in CI.
- live path requiring external provider credential is separated as optional/live.
- optional/live path can SKIP when credential absent, but is not used as core QA PASS evidence.

Supporting quality checks:

- targeted pytest for canonical filters and engine adapter wiring
- lowerer-related regression tests
- ruff check
- ruff format check
- pyright

## QA Checklist

### QA-1. Preserve tool output when no context pressure

#### What to check

Verify tool result output is not changed to placeholder under sufficiently large context budget. Also verify canonical DB payload remains original.

#### Why it matters

This is core guarantee preventing recurrence of goldfish behavior from existing age-based durable masking.

#### How to check

Create transcript fixture containing tool result in E2E/testenv and run agent with sufficiently large `max_input_tokens` setting. Confirm original output appears in lowerer or model adapter input evidence, and confirm canonical history payload remains original.

#### Expected result

Model input includes original tool output. canonical history payload also remains original. Placeholder wording does not appear.

#### Execution result

PASS — Ran `uv run pytest src/azents/runtime/canonical/execution_test.py src/azents/runtime/canonical/filters_test.py src/azents/runtime/canonical/engine_adapter_test.py` from `python/apps/azents` working directory. `test_tool_output_pressure_product_path_noops_without_pressure` fixture ran with `CanonicalToolOutputContextPressureFilter(max_input_tokens=10_000, reserved_response_tokens=100, safety_margin_tokens=100)` and confirmed lowerer input and canonical history payload both preserved original `small output` in `AgentRunExecution` product path.

#### Fixes applied

None.

### QA-2. Replace oldest tool result first when context pressure exists

#### What to check

With transcript containing multiple tool results and small context budget, verify oldest eligible tool result output is replaced by placeholder first. Also verify later tool results are preserved once within budget.

#### Why it matters

Context pressure response must be predictable and naturally preserve recent work context longer.

#### How to check

Compose transcript fixture with old tool result and recent tool result in E2E/testenv. Run agent with small `max_input_tokens` setting and inspect lowerer or model adapter input evidence to confirm old output is replaced first.

#### Expected result

Oldest eligible tool result output is replaced first with placeholder. Recent tool result output is preserved as long as context budget allows. canonical DB payload remains original.

#### Execution result

PASS — In same pytest execution, verified `test_tool_output_pressure_product_path_trims_oldest_result` fixture. Old tool result was `x * 10_000`, recent tool result was `recent output`, and `CanonicalToolOutputContextPressureFilter(max_input_tokens=1_000, reserved_response_tokens=0, safety_margin_tokens=0)` was applied. In lowerer input, only old output was replaced with `[Tool output omitted due to context pressure. Original output remains in canonical history.]`, and recent output was preserved. In canonical history payload, old output remained original `x * 10_000`.

#### Fixes applied

None.

### QA-3. Provider tool result follows same policy as client tool result

#### What to check

Verify `ProviderToolResultPayload` output is also context pressure target. Confirm `native_artifact`, `call_id`, `name`, `status`, `attachments` are preserved.

#### Why it matters

Must handle model-visible tool output family in alignment with Codex, and context pressure guard must not be missed due to client/provider difference.

#### How to check

Compose canonical transcript fixture containing provider tool result in E2E/testenv. Run agent with small context budget and inspect lowerer or model adapter input evidence. Also inspect canonical history payload.

#### Expected result

Only provider result output body is replaced with placeholder. provider native artifact and metadata are preserved. canonical DB payload remains original.

#### Execution result

PASS — In same pytest execution, verified `test_tool_output_pressure_product_path_trims_provider_result` fixture. `ProviderToolResultPayload` output was replaced with placeholder, and `native_artifact` was preserved in lowerer input identical to original artifact. canonical history payload kept provider output original `x * 10_000`.

#### Fixes applied

None.

### QA-4. Compaction summary does not see placeholder transcript

#### What to check

Verify context-pressure placeholder is not included in auto compaction summary input. Also verify placeholder is applied in lowerer input when context pressure exists.

#### Why it matters

This prevents repeating existing durable masking problem. Compaction summary must be generated from canonical transcript, not placeholder-degraded transcript.

#### How to check

Create transcript fixture exceeding compaction threshold in E2E/testenv or engine-level testenv. Capture summary input with summary model call spy or equivalent evidence and compare with lowerer/model adapter input evidence.

#### Expected result

Summary input has no placeholder wording. Lowerer input has placeholder according to context pressure. canonical DB payload remains original.

#### Execution result

PASS — In same pytest execution, verified `test_tool_output_pressure_product_path_keeps_compaction_summary_text` fixture. Reproduced order of compaction-after transcript and pressure filter with `CanonicalPreLowerFilterPipeline([_PreFilter([summary_event, tool_event]), pressure_filter])`. `CompactionSummaryPayload.content` in lowerer input preserved original `summary from original tool output` and did not include placeholder wording. Tool result output in same lowerer input was replaced with context pressure placeholder.

#### Fixes applied

None.

### QA-5. `NativeRequestSizeGuard` remains final safety net

#### What to check

Verify request passes guard if placeholder replacement resolves context pressure, and existing guard fails if request remains too large after replacement.

#### Why it matters

New filter is best-effort shaping, and existing post-lower guard must keep responsibility for final hard failure.

#### How to check

Run two fixtures in E2E/testenv. One case passes guard after placeholder replacement; another exceeds guard even after placeholder replacement.

#### Expected result

First case proceeds to model call. Second case fails on existing guard error path.

#### Execution result

PASS — In same pytest execution, verified `test_tool_output_pressure_product_path_keeps_native_size_guard` fixture. First fixture passed `NativeRequestSizeGuard(max_input_chars=1_000)` after placeholder replacement and proceeded to model call. Second fixture had large user message, so native input still exceeded `max_input_chars=1_000` after placeholder replacement and failed through existing `Native model request input exceeds size guard` error path.

#### Fixes applied

None.

## Acceptance Criteria

- New filter works inside existing pre-lower filter system.
- If no context pressure, transcript is unchanged.
- If context pressure exists, placeholder replacement starts from oldest eligible tool result output body.
- Handles both `ClientToolResultPayload` and `ProviderToolResultPayload`.
- Preserves call id, name, status, attachments, provider native artifact.
- Does not change canonical DB payload.
- Auto compaction summary input does not include placeholder.
- Final native request guard remains.
- Every QA Checklist item is filled with PASS evidence in E2E/testenv verification phase.

## Alternatives Considered

### Introduce separate projection pipeline

Rejected. Existing filter system already exists, and whether filter modifies DB or in-memory transcript is responsibility of each filter implementation. Creating new pipeline/type concept would unnecessarily complicate design.

### Introduce new per-output cap

Rejected. Azents already has per-tool abnormal output defense. This feature handles context pressure, not per-output explosion defense.

### Middle truncation

Rejected. This path is context pressure trim, and Codex context pressure path is closer to placeholder replacement. Middle truncation is better handled in per-tool abnormal output policy cleanup.

### Trim in post-lower native request

Rejected. At native request stage, it is hard to map back to canonical tool result unit, and it becomes strongly tied to provider-specific shape.

### Recent N run hard protection

Rejected. Risk of returning to existing age-based masking heuristic. If context pressure is severe, latest output may also need reduction; ordering oldest-first is sufficient.

## Open Questions

1. Which follow-up feature should handle context overflow of compaction request itself?

## Implementation Notes

- If `request.max_tokens` exists, use it as response reservation.
- If `request.max_tokens` absent, use `min(4096, max_input_tokens // 8)` as response reservation.
- rough estimate safety margin uses `max(1024, max_input_tokens // 20)`.
