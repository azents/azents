---
title: "Complete Specialized Presentation Coverage for Builtin Tools Historical Requirements Reconstruction"
created: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: builtin-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0177-complete-builtin-tool-presentations.md"
---

# Complete Specialized Presentation Coverage for Builtin Tools Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `builtin-260721`
- Source: `docs/azents/adr/builtin-260721-builtin-presentations.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[known-260720/ADR](../adr/known-260720-known-tools-through-validated-frontend-adapters.md) established validated, source-aware frontend adapters, one shared disclosure shell, closed presentation families, privacy-reviewed summary prominence, and permanent Generic fallback. The first implementation slice specialized ten stable Runtime tools, while nineteen source-less builtin tools still use Generic argument/output presentation.

The remaining tools span file delivery, persistent Memory, Goal and Todo state, filesystem Skills, subagent collaboration, and deferred Tool Search. Several already project a separate product surface such as attachments, Goal/Todo state, Skill activity, or the Subagent tree. Specialized tool presentation must explain the invocation and result without duplicating or taking ownership from those surfaces.

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

- Preserve the canonical identity and Generic fallback rules from [known-260720/ADR](../adr/known-260720-known-tools-through-validated-frontend-adapters.md).
- Do not specialize Toolkit-owned calls from visible-name collisions.
- Keep attachment ownership and Activity boundaries unchanged.
- Keep Goal, Todo, Skill, and Subagent state surfaces authoritative for their domain state.
- Keep memory content, Goal/Todo text, Skill bodies, inter-agent messages, search queries, file URIs, and arbitrary result text out of collapsed summaries.
- Prefer existing result contracts and frontend projection data; do not require a backend or public API contract change merely to activate a presentation.
- Use the existing shared disclosure shell and closed presentation families rather than one bespoke outer component per tool.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
