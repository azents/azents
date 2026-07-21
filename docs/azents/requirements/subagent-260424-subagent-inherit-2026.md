---
title: "Subagent Toolkit/Model Inherit Historical Requirements Reconstruction"
created: 2026-04-24
implemented: 2026-04-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260424
historical_reconstruction: true
migration_source: "docs/azents/design/subagent-inherit-2026-04-24.md"
---

# Subagent Toolkit/Model Inherit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260424`
- Source: `docs/azents/design/subagent-260424-subagent-inherit-2026.md`
- Historical source date basis: `2026-04-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Current nointern subagent has independent **LLM model**, **toolkit bindings**, and **system prompt** from the parent agent. This independence fits the "specialist subagent" pattern (DB analyst, code reviewer, etc.), but makes it hard to create a "**general subagent** — a subagent that inherits the parent's tools and model as-is and only performs a specific role."

This design adds options for subagent to selectively **inherit** parent's toolkit and model. At the same time, tools that must remain parent-only (`memory`, `schedule`, `subagent` itself, etc.) are explicitly separated.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

> Workspace owner creates a subagent named "Code Explorer". Only the system prompt is set to "codebase investigation expert", and options **inherit parent's toolkit and model** are enabled. Whichever parent it is attached to, it runs with the parent tools/model at call time. The same subagent can be reused across multiple parents.

## Supporting Scenarios

> Workspace owner creates a subagent named "Code Explorer". Only the system prompt is set to "codebase investigation expert", and options **inherit parent's toolkit and model** are enabled. Whichever parent it is attached to, it runs with the parent tools/model at call time. The same subagent can be reused across multiple parents.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Existing `[integration-same-workspace]` rule: subagent and parent are in same workspace. Inherit happens only within same workspace, so there is no scope validation problem.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
