---
title: "Run-Scoped Azents Virtual Filesystem Historical Requirements Reconstruction"
created: 2026-07-19
implemented: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: azents-260719
historical_reconstruction: true
migration_source: "docs/azents/design/run-scoped-azents-vfs.md"
---

# Run-Scoped Azents Virtual Filesystem Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `azents-260719`
- Source: `docs/azents/design/azents-260719-azents-vfs.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently discovers Skills only from the Agent Runtime filesystem. Release-bundled and Toolkit Provider-owned Skills need stable model-visible locators, adjacent package resources, deterministic authorization, and recovery-safe content without copying every package into every Runtime.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Provide a general-purpose read-only `azents://` virtual filesystem.
- Freeze one immutable VFS projection for every AgentRun before SkillAction input promotion.
- Load managed Skills directly from `azents://skills/{namespace}/{skill}/SKILL.md`.
- Materialize adjacent managed resources into Runtime only through `import_file`.
- Preserve all existing filesystem Skill paths, discovery, active/latest adoption, and resource behavior.
- Support global release bundles and Toolkit Provider-owned release bundles.
- Keep retries, worker takeover, and run resume on the exact same projected bytes.

## Non-goals

- Writable VFS operations.
- Runtime mounting or transparent VFS access through ordinary file tools.
- Catalog publishing and Workspace/Agent package assignment APIs in the first implementation.
- Large binary package storage or object-store-backed VFS blobs in the first implementation.
- Replacing filesystem Skill projection state.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
