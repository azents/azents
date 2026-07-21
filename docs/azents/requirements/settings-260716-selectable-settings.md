---
title: "Model-Scoped Selectable Model Settings Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: settings-260716
historical_reconstruction: true
migration_source: "docs/azents/design/model-scoped-selectable-model-settings.md"
---

# Model-Scoped Selectable Model Settings Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `settings-260716`
- Source: `docs/azents/design/settings-260716-selectable-settings.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Selectable Agent models may differ in input limits, output limits, and provider-hosted tool support.
Azents currently stores the corresponding user intent once in Agent-level `model_parameters`, so a
prompt-selected or subagent-selected model receives settings chosen for a different target. Workspace
default model options cannot carry these settings, and the Agent form renders the controls away from the
model they configure.

Adding a model also appends a row below the viewport while leaving focus on the add button. The generated
label starts with a system-selected value such as `default`, even though the user owns label semantics.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Store max context window, max output tokens, and enabled built-in tools per selectable model option.
- Apply the settings for the label-selected foreground model in all runtime paths.
- Include the same settings in Workspace default model options copied into new Agents.
- Enable every supported and implemented built-in tool by default while preserving an explicit all-off
  choice.
- Remove configurable built-in tools that do not have a complete runtime implementation.
- Put model configuration behind a row-level settings modal.
- Move the add action next to the list, create an empty label, and focus the new label input.

## Non-goals

- Moving reasoning effort into model option settings. Reasoning effort remains part of the current
  inference-profile behavior.
- Applying a model option's max output cap to internal compaction summary generation.
- Propagating later Workspace default changes into existing Agents.
- Reimplementing image generation or web fetch.
- Removing historical image-generation event parsing or attachment rendering.
- Adding provider-specific built-in tool configuration fields to the first UI version.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
