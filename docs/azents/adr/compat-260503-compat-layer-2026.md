---
title: "Provider Compatibility Layer Historical Decision Reconstruction"
created: 2026-05-03
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: compat-260503
historical_reconstruction: true
migration_source: "docs/azents/design/provider-compat-layer-2026-05-03.md"
---

# Provider Compatibility Layer Historical Decision Reconstruction

- Snapshot: `compat-260503`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/provider-compat-layer-2026-05-03.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### compat-260503/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Discussion Points and Decisions

Reflects D1~D6 decisions discussed in GitHub Discussion #3314.

### Explicit source section: D3. Provider metadata preservation policy

**Decision: preserve only when same provider + same model**

- To reduce provider switch errors, metadata from other provider/model is not reused in new request.
- Same direction as OpenCode `differentModel` judgment.
- Can extend later if compatible model family policy is confirmed, but default is conservative.

### Explicit source section: D5. Unsupported media handling policy

**Decision: replace with Prompt-level error text**

- Same as OpenCode.
- image/pdf/audio/video part unsupported by model capability is replaced with text error part immediately before request.
- Original media item is preserved in DB/events.
- Run is not blocked.
- Error text includes instruction for model to explain unsupported modality to user.

### Explicit source section: Reasoning/thinking/options normalization

Convert option namespace by provider in Phase 4.

- GPT-5/OpenAI/Copilot/Azure: `reasoningEffort`, `reasoningSummary`, encrypted reasoning include
- Claude/Anthropic: `thinking`, `budgetTokens`, adaptive thinking
- Bedrock: `reasoningConfig`
- Gemini: `thinkingConfig`, `thinkingLevel`, `thinkingBudget`
- Alibaba/DashScope: `enable_thinking`

Prompt cache option is more optimization than correctness, so separate as Phase 4 sub-item or follow-up issue candidate.

### Explicit source section: Phase 2 — Responses id/metadata policy

- Generalize Responses API family `store=False` id stripping.
- Limit provider metadata preservation to same provider + same model.
- Add incompatible reasoning/provider metadata removal rule.
- Add ChatGPT OAuth/OpenAI regression test.

### Explicit source section: Phase 4 — schema/media/options normalization

- unsupported media prompt-level fallback
- Gemini schema sanitizer
- Moonshot/Kimi schema sanitizer
- reasoning/thinking option namespace transform
- separate prompt cache option as optimization sub-item or follow-up issue

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
