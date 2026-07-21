---
title: "Adopt Claude Rules Loader as a Separate Runtime Toolkit Historical Requirements Reconstruction"
created: 2026-07-02
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: claude-260702
historical_reconstruction: true
migration_source: "docs/azents/adr/0088-claude-rules-loader.md"
---

# Adopt Claude Rules Loader as a Separate Runtime Toolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `claude-260702`
- Source: `docs/azents/adr/claude-260702-claude-rules-loader.md`
- Historical source date basis: `2026-07-02`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents already supports repository instructions through `AGENTS.md` read-result appendices. [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) decided that `AGENTS.md` should not be injected through Toolkit prompt fragments. Instead, applicable instruction files are appended to successful `read` results, deduped by path in session Toolkit State, and reloaded from the runtime filesystem when needed.

Many repositories also use Claude Code style `.claude/rules/**/*.md` files for modular coding rules. These rules may include YAML frontmatter with `paths` globs. Repo-local Codex/OpenCode hooks can emulate this behavior outside Azents, but Azents itself needs product-runtime support so agents receive the same repository rules when working through Azents runtime file tools.

The key design tension is whether Claude rules should behave like Claude Code's prompt-level active rules or like Azents' existing AGENTS.md runtime instruction model. Prompt-level injection would make rules feel more always-on, but it would reintroduce mutable filesystem content into stable prompt construction and conflict with the current prompt-cache and runtime-touch policy.

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
