---
title: "ADR-0179 Implementation Audit - 2026-07-21"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [backend, engine, frontend, verification]
---

# ADR-0179 Implementation Audit - 2026-07-21

## Scope

This audit compares the implemented apply-patch provider-tool dialect behavior with
[ADR-0179](../adr/0179-apply-patch-provider-tool-dialects.md). It records current implementation and
test evidence only. Current behavior is specified in [Agent Execution Loop](../spec/flow/agent-execution-loop.md),
[Toolkit](../spec/domain/toolkit.md), [Conversation & Events](../spec/domain/conversation.md),
[Context Compaction](../spec/flow/context-compaction.md), and [Run Resume](../spec/flow/run-resume.md).

## Decision Evidence

| ADR-0179 decision | Implemented behavior | Code evidence | Test evidence |
| --- | --- | --- | --- |
| D1: verified custom transport while retaining one Runtime operation | The catalog can declare `apply_patch` as plaintext custom; normalization waits for completed custom input, the handler validates the envelope before the existing Runtime operation, and results lower as custom output. | `engine/events/tools.py`, `engine/events/openai_responses.py`, `engine/events/responses_output.py`, `engine/tools/apply_patch.py` | `engine/events/openai_responses_test.py`, `engine/events/tools_test.py`, `engine/tools/apply_patch_test.py` |
| D2: independent semantic and route transport eligibility | Profile resolution distinguishes V4A semantic eligibility from route-specific custom and JSON-function transport. Unknown or unsupported routes omit the tool. | `engine/run/client_tool_compatibility.py`, `engine/events/engine_adapter.py` | `engine/run/client_tool_compatibility_test.py`, `engine/events/engine_adapter_test.py` |
| D3: closed durable dialect and safe replay | Calls, results, and active calls carry the closed dialect. Same-native replay requires an exact compatibility key and matching item type; incompatible completed custom history becomes bounded non-executable context. | `engine/events/types.py`, `engine/events/tool_calls.py`, `engine/events/responses_lowering.py`, `engine/events/responses_continuation.py` | `engine/events/types_test.py`, `engine/events/openai_responses_test.py`, `engine/events/litellm_responses_test.py`, `engine/events/responses_continuation_test.py` |
| D4: exact custom envelope with Runner-owned V4A semantics | The custom parser accepts only the bounded transport envelope, preserves the body for Runner validation, and fails before Runner invocation for malformed or oversized input. | `engine/tools/apply_patch.py` | `engine/tools/apply_patch_test.py` |
| D5: exact official route and disable-only rollout | Custom selection requires the official OpenAI Responses API-key route, exact reviewed model, and deterministic cohort. The adapter configuration defaults to `apply_patch_custom_rollout_percent = 0`. | `engine/run/client_tool_compatibility.py`, `engine/events/engine_adapter.py` | `engine/run/client_tool_compatibility_test.py`, `engine/events/engine_adapter_test.py` |
| D6: full lifecycle compatibility before exposure | Execution, persistence, continuation, recovery, cancellation, compaction, history/live projection, and frontend presentation retain the selected dialect. Custom input is omitted from compaction token accounting and continuity excerpts. | `engine/events/execution.py`, `engine/events/filters.py`, `engine/events/responses_lowering.py`, `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts`, `typescript/apps/azents-web/src/features/chat/knownToolPresentation.ts` | `engine/events/execution_test.py`, `engine/events/filters_test.py`, `engine/events/engine_adapter_test.py`, `typescript/apps/azents-web/src/features/chat/knownToolPresentation.test.mts` |

## Validation Evidence

The stacked implementation is represented by PRs #689 through #699. The validation-hardening PR
#699 was checked on 2026-07-21: all required CI checks completed successfully; intentionally
non-applicable routing lanes were skipped by CI rather than failed. Its final commit is
`154c801c` and its base is the custom transport PR #695.

Focused deterministic coverage covers JSON-function preservation, custom declaration and completed
normalization, malformed and oversized custom input rejection, same-dialect continuation, orphan
output removal, recovery/cancellation result dialect copying, compaction omission, and frontend
specialized-versus-Generic presentation. The evidence paths listed above intentionally avoid storing
or reproducing raw custom input.

## Operational Enablement Status

The source implementation is selection-disabled by default. No source or CI step authorizes a
nonzero custom cohort. Before any operational enablement, every worker and service process that can
read, execute, recover, continue, compact, export, or present durable client-tool events must meet the
dual-dialect compatibility floor, and delayed or leased work must be drained or fenced to that floor.
Disabling future custom selection must not alter lifecycle handling for an already durable custom
event.

## Result

No ADR-0179 implementation contradiction was found in the audited code paths. This audit does not
amend ADR-0179; it records the implementation evidence and the remaining operational rollout gate.
