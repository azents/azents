---
title: "Adopt Toolkit Hooks and Toolkit State Historical Requirements Reconstruction"
created: 2026-05-14
implemented: 2026-05-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260514
historical_reconstruction: true
migration_source: "docs/azents/adr/0032-toolkit-hooks-for-agents-md.md"
---

# Adopt Toolkit Hooks and Toolkit State Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `toolkit-260514`
- Source: `docs/azents/adr/toolkit-260514-toolkit-hooks-for-agents-md.md`
- Historical source date basis: `2026-05-14`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The Session Workspace Project contract keeps `/home/sandbox` as the Agent's long-lived workspace and limits project-scoped active configuration discovery to registered Projects. `AGENTS.md` instruction loading must handle both root workspace instructions and Project-scoped instructions, and the system prompt for later turns must change depending on paths targeted by file tools.

The initial design considered creating a dedicated persistent store for AGENTS.md as S3 objects. However, AGENTS.md is only the first example of long-lived state storage needs required by Toolkit runtime. Future memory, policy, audit, and tool-specific caches will have the same lifecycle and identity problems. If we create an AGENTS.md-only store, runtime state source of truth becomes unclear across `runtime_state` blob, S3 objects, and Toolkit internal memory.

Also, in the current nointern runtime, Toolkit is already the execution boundary for tool bundle, prompt, credential, and runtime context. Introducing a separate arbitrary plugin runtime would require designing capability, isolation, versioning, and multi-tenant security together, which is too broad for the current need.

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
