---
title: "Adopt Tool Output Context-pressure Filter"
created: 2026-06-04
tags: [architecture, backend, engine, runtime, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: output-260604
historical_reconstruction: true
migration_source: "docs/azents/adr/0048-tool-output-context-pressure-filter.md"
---
# output-260604/ADR: Adopt Tool Output Context-pressure Filter

## Context

Azents removed the existing `CanonicalObservationMaskingFilter`. That filter directly stored shortened old `ClientToolResultPayload` output in canonical DB payload. This meant model input optimization could cause durable history loss, and compaction summary could see already degraded tool output.

Codex benchmarking showed that tool/function output context trimming is better treated as model-facing input shaping, not raw/canonical history mutation. In particular, under context pressure, tool output body is replaced by a placeholder while preserving call id, status, and metadata.

Azents already has abnormal output defenses per tool: bash stdout/stderr truncation, grep match limit, Discord output limit, AGENTS content truncation, and post-lower `NativeRequestSizeGuard`. Therefore, this decision is not about introducing a new per-output cap; it is about handling context pressure when an otherwise normal transcript accumulates and exceeds the overall model input context budget.

## Decision

Azents adds a tool output context-pressure filter inside the existing `CanonicalPreLowerFilterPipeline`.

Decisions:

1. Use the existing filter system rather than defining a new projection pipeline/type.
2. The new filter operates only when context pressure exists.
3. Target payloads are model-visible tool result types aligned with Codex: `ClientToolResultPayload` and `ProviderToolResultPayload`.
4. Context pressure is judged by rough token estimate and main model context window.
5. When context pressure occurs, replace output body with a short placeholder.
6. Preserve call id, tool name, status, attachments, and provider native artifact.
7. Do not change canonical DB payload.
8. Place the new filter after `CanonicalAutoCompactionFilter`.
9. Replace older eligible tool results with placeholders first, and stop once input fits within budget.
10. Do not add hard protection for recent N runs.
11. Keep post-lower `NativeRequestSizeGuard` as the final safety net.

## Considered Options

### Keep existing durable masking

Rejected. Directly changing canonical DB payload and shortening old output regardless of context pressure can cause durable history loss and degraded compaction input.

### Introduce separate model input projection pipeline

Rejected. Azents already has a pre-lower filter system, and whether a filter mutates DB or only in-memory transcript is each filter implementation's responsibility. Adding a separate pipeline/type would make the concept unnecessarily heavy.

### Introduce new per-output cap

Rejected. Azents already has tool-specific abnormal output guards. This decision addresses overall model input context pressure, not single-output explosion defense.

### Apply middle truncation by default

Rejected. Codex's context-pressure path is closer to placeholder replacement, and this filter's goal is to reliably fit within context budget. Middle truncation is better handled when organizing tool-specific abnormal output policy.

### Trim at post-lower native request stage

Rejected. At native request stage, it is hard to map back and handle canonical tool result units, and logic becomes tightly coupled to provider-specific native shapes.

### Hard-protect recent N runs

Rejected. This risks returning to age-based masking heuristics. Under severe context pressure, even recent output may need reduction. Replacing older results first is sufficient ordering.

## Consequences

Positive outcomes:

- Canonical history is not lost because of model input optimization.
- If there is no context pressure, old tool output remains preserved.
- Client/provider tool results are handled by the same policy.
- Compaction summary does not see transcript degraded by placeholders.
- Responsibilities of existing tool-specific abnormal output guards and final native request guard remain intact.

Trade-offs:

- Rough token estimate can differ from actual provider tokenization.
- Placeholder replacement is a strong compression; under severe context pressure, some old tool output bodies disappear entirely from model input.
- Context overflow in compaction request itself is not solved by this decision.
- Response reservation and safety margin constants must be tuned during implementation.

## Follow-up

- Design compaction-input context-pressure shaping applied only to compaction request clone.
- If needed, organize tool-specific abnormal output guard as separate policy.
- After implementation, update related spec to match current behavior.

## Migration provenance

- Historical source filename: `0048-tool-output-context-pressure-filter.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
