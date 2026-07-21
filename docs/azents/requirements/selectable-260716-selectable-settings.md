---
title: "Model-Scoped Selectable Model Settings Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: selectable-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0145-model-scoped-selectable-model-settings.md"
---

# Model-Scoped Selectable Model Settings Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `selectable-260716`
- Source: `docs/azents/adr/selectable-260716-selectable-settings.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

An Agent owns an ordered `selectable_model_options` list, but configurable input and output token caps
and provider-hosted built-in tools are stored once in Agent-level `model_parameters`. A prompt or
subagent may select any option by label, so the same global settings are applied after the runtime has
selected a different model. Validation is also performed against the Agent's default main model rather
than every selectable target.

Workspace model settings own the default selectable option list copied into new Agents, but cannot attach
the same settings to each default model. The frontend consequently renders token caps and built-in tool
choices outside the model list.

The normalized model capability snapshot already reports provider-hosted tools as semantic identifiers.
Only `web_search` has a complete current path from capability and validation through runtime lowering.
`web_fetch` and `image_generation` are registered as configurable built-in tools without a complete
supported runtime contract. Image-generation event parsing remains necessary for historical and
provider-originated output data and is independent of Agent built-in tool configuration.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
