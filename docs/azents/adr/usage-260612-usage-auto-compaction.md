---
title: "Usage-based Auto Compaction and Removal of Tool Output Omit"
created: 2026-06-12
tags: [backend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: usage-260612
historical_reconstruction: true
migration_source: "docs/azents/adr/0056-usage-based-auto-compaction.md"
---

# usage-260612/ADR: Usage-based Auto Compaction and Removal of Tool Output Omit

## Status

Accepted. This decision supersedes [output-260604/ADR](./output-260604-output-context-pressure-filter.md)'s tool output context-pressure filter decision.

## Background

[output-260604/ADR](./output-260604-output-context-pressure-filter.md) adopted replacing old tool output with placeholders in normal model input projection under context pressure. Later operational observation and Codex/OpenCode code analysis showed that estimating the full canonical payload as `chars / 4` can significantly overestimate actual provider token usage. This error can remove old tool output even when actual context usage is low, degrading model quality without benefit.

Codex does not omit old tool output in normal turns merely due to context pressure. Auto compaction decision is centered on provider usage, with only local deltas added after provider usage estimated. Tool output rewrite is a separate preprocessing step used only when the compaction request itself does not fit the context window.

## Decision

Azents does not omit old tool output from normal model input due to context pressure.

Auto compaction decision is based on:

1. `usage.prompt_tokens` from the latest `turn_marker`
2. model-visible token estimate of canonical events after the latest turn marker

If no latest turn marker exists, calculate the whole transcript by model-visible estimate.

Token estimate first calculates model-visible byte cost, not the entire canonical storage payload, then converts with `ceil(bytes / 4)`. Exclude event id, timestamp, schema version, native artifact, and storage-only metadata. Count only user/assistant text, tool call name/arguments, tool result text, compaction summary text, and bounded metadata for file/attachment/artifact.

## Consequences

- Normal model input preserves original meaning of old tool output.
- Auto compaction does not re-estimate prefix already reflected in actual provider usage.
- `chars / 4` is limited to delta estimate after provider usage, not full canonical transcript pressure judgment.
- Final defense for oversized native requests is post-lower `NativeRequestSizeGuard`.

## Rejected Options

### Keep existing context-pressure filter

Rejected. It can remove old tool output regardless of actual usage, and the benefit is small compared with model input quality degradation.

### More precise estimation of the whole canonical payload

Rejected. No matter how much it is adjusted, re-estimating token usage already reported by provider is unnecessary. Estimation applies only to delta after provider usage.

## Migration provenance

- Historical source filename: `0056-usage-based-auto-compaction.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
