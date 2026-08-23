---
title: "Codex-like Compaction Checkpoints Implementation Plan"
created: 2026-05-30
tags: [backend, engine, plan]
---

# Codex-like Compaction Checkpoints Implementation Plan

## Source of Truth

- Design: `docs/azents/design/codex-like-compaction-checkpoints.md`
- ADR: `docs/azents/adr/codex-260530-codex-compaction-checkpoints.md`
- Existing spec: `docs/azents/spec/flow/context-compaction.md`

## Stack Shape

```text
main
← azents-codex-compaction-design
← azents-codex-compaction-plan
← azents-codex-compaction-runtime-budget
← azents-codex-compaction-prompt
← azents-codex-compaction-spec-promotion
```

## Phase 1 — Design Document

- Branch: `azents-codex-compaction-design`
- PR: design/ADR only
- Output for next phase:
  - [codex-260530/ADR](../adr/codex-260530-codex-compaction-checkpoints.md) with accepted decisions
  - Design document with acceptance criteria and QA checklist

## Phase 2 — Multi-phase Implementation Plan

- Branch: `azents-codex-compaction-plan`
- Scope:
  - Define implementation phases and verification responsibilities.
  - Do not change runtime behavior.
- Output for next phase:
  - This plan document.

## Phase 3 — Runtime Budget and Non-stream Call

- Branch: `azents-codex-compaction-runtime-budget`
- Purpose:
  - Implement output size control and non-stream summary model call.
- Boundary:
  - No Codex-like prompt rewrite except budget placeholders needed by current prompt call.
  - No spec promotion beyond phase-local docs if required.
- Expected changes:
  - Add `CompactionSummaryBudget` or equivalent budget value object.
  - Add context-window based budget computation.
  - Use 1000-unit nearest rounding for target/limit chars.
  - Clamp target chars to 12k~24k and limit chars to 16k~32k.
  - Compute `max_output_tokens = limit_chars // 4`.
  - Compute truncate threshold with 10% tolerance and 1000-unit ceiling.
  - Change compaction summary LiteLLM Responses call to `stream=False`.
  - Pass `max_output_tokens` for OpenAI/ChatGPT OAuth and other providers.
  - Apply runtime truncation guard with `[Truncated by Azents compaction guard.]` note.
- Verification scope:
  - Unit tests for budget calculation.
  - Unit tests for truncation threshold and note.
  - Unit/spy tests that summary call uses `stream=False` and `max_output_tokens`.
  - Existing canonical compaction tests continue to pass.
- Provides for next phase:
  - Stable budget object and summary call API for prompt to reference target/limit chars.

## Phase 4 — Codex-like Checkpoint Prompt

- Branch: `azents-codex-compaction-prompt`
- Purpose:
  - Replace narrative conversation summary prompt with durable handoff checkpoint prompt.
- Boundary:
  - Use budget behavior from phase 3.
  - Do not introduce new runtime branching by compaction mode.
- Expected changes:
  - Rewrite summary system/user prompt to checkpoint-oriented instructions.
  - Include required sections:
    - `Goal`
    - `Durable Instructions`
    - `Current State`
    - `Completed Work`
    - `Pending Work`
    - `Decisions and Rationale`
    - `Relevant Files and Symbols`
    - `Verification`
    - `External References`
    - `Notes for Next Agent`
  - Include no user answer / no task continuation instructions.
  - Include budget discipline instructions.
  - Include previous checkpoint integration instructions.
  - Include preserved tail duplication guard.
  - Render previous compaction summary as existing checkpoint.
- Verification scope:
  - Prompt constant tests for required sections/instructions.
  - Rendering test for previous summary label.
  - Existing summary generation tests continue to pass.
- Provides for next phase:
  - Implemented behavior to promote into living spec.

## Phase 5 — Spec Promotion

- Branch: `azents-codex-compaction-spec-promotion`
- Purpose:
  - Update current system spec and design implemented metadata.
- Scope:
  - Update `docs/azents/spec/flow/context-compaction.md`.
  - Update related spec if code path impact requires it.
  - Mark design implemented with current date after implementation is complete.
  - Fill QA checklist execution results based on phase verification.
  - Regenerate docs index.
- Verification scope:
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - Relevant runtime tests from phases 3 and 4.

## Acceptance Criteria Mapping

| Design acceptance criterion | Phase |
| --- | --- |
| Non-stream summary call | Phase 3 |
| `max_output_tokens` uses dynamic budget | Phase 3 |
| Dynamic budget from model context window | Phase 3 |
| 1000 rounding, clamp, truncate tolerance | Phase 3 |
| Unknown context fallback 128k | Phase 3 |
| Runtime truncate note | Phase 3 |
| Codex-like checkpoint prompt | Phase 4 |
| Previous summary as existing checkpoint | Phase 4 |
| Same prompt/budget for auto/manual/fallback | Phase 3 and 4 |
| Spec updated | Phase 5 |

## E2E Primary Matrix

| Behavior | Primary verification | Phase |
| --- | --- | --- |
| Summary call budget control | deterministic unit/spy test around summary call | Phase 3 |
| Summary output guard | deterministic unit test with oversized fake summary | Phase 3 |
| Auto compaction tail preservation regression | existing canonical compaction tests | Phase 3/4 |
| Prompt checkpoint shape | prompt constant tests | Phase 4 |
| Spec reflects implemented behavior | docs index/spec checks | Phase 5 |

## testenv Fixture/prerequisite Support

No new testenv fixture or external credential prerequisite is required. Provider live compatibility is not a mandatory CI prerequisite for this feature because deterministic fake/spy tests can verify Azents behavior without calling external LLM providers.

## Blockers / Open Prerequisites

- None known.
- If non-stream ChatGPT OAuth Responses call fails in implementation testing, stop and report the provider compatibility gap instead of silently adding fallback retry.
