---
title: "Generalize Client Tool Wire Variant Selection Historical Requirements Reconstruction"
created: 2026-07-21
implemented: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: client-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0181-generalize-client-tool-wire-variants.md"
---

# Generalize Client Tool Wire Variant Selection Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source documents. Unknown intent remains explicitly unknown.

- Snapshot: `client-260721`
- Source: `docs/azents/adr/0181-generalize-client-tool-wire-variants.md` and `docs/azents/design/generic-client-tool-wire-variants.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Client-tool preparation coupled model eligibility, provider-adapter wire support, and selected tool declarations under one profile and a literal `apply_patch` check. A future multi-variant client tool would otherwise require another tool-name-specific exception.

## Primary Actor

Unknown — the historical sources do not state this explicitly.

## Primary Scenario

Unknown — the historical sources do not state this explicitly.

## Supporting Scenarios

Unknown — the historical sources do not state this explicitly.

## Goals

- Preserve existing `apply_patch` semantic eligibility and exposure behavior.
- Select the compatible provider wire variant without branching on a model-visible tool name.
- Freeze the selected declaration, guidance, handler route, and durable dialect before provider dispatch.

## Non-goals

- Changing durable call/result dialect fields or Runtime apply-patch semantics.
- Adding providers, dialects, model eligibility, configuration flags, or fallback retries.
- Generalizing provider event normalization beyond the existing dialect representation.

## Requirements

- Model profiles determine semantic eligibility independently of wire-format selection.
- Adapter profiles provide ordinary-tool and semantic-profile-specific dialect preferences.
- Client tools declare their supported variants; ordinary tools remain JSON-function tools by default.
- A prepared catalog exposes exactly one compatible variant, or omits the tool when none is supported.
- Selection and execution fail closed on missing profiles, unsupported variants, duplicate declarations, or missing handler protocols.

## Fixed Constraints

- Existing `apply_patch` behavior and durable history semantics remain unchanged.
- Variant selection is deterministic and occurs before provider I/O.
- No database or public API migration is required.

## Open Assumptions

Unknown — the historical sources do not state additional assumptions.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
