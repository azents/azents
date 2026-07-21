---
title: "Claude Rules Loader Historical Requirements Reconstruction"
created: 2026-07-02
implemented: 2026-07-02
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: rules-260702
historical_reconstruction: true
migration_source: "docs/azents/design/claude-rules-loader.md"
---

# Claude Rules Loader Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `rules-260702`
- Source: `docs/azents/design/rules-260702-claude-rules-loader.md`
- Historical source date basis: `2026-07-02`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents already appends applicable `AGENTS.md` files to successful runtime `read` tool results so agents receive path-relevant repository instructions without injecting mutable filesystem state into the stable system prompt. Many repositories also keep Claude Code style rules under `.claude/rules/`. Those rules currently work in Claude Code and repo-local hooks, but Azents does not load them as runtime instructions.

The goal is to support `.claude/rules/**/*.md` in Azents with the same runtime instruction boundary as `AGENTS.md`: load from filesystem only after successful file reads, keep source of truth in the runtime filesystem, avoid prompt-prefix churn, and keep repo configuration issues from disrupting user tasks.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Load applicable Claude Code style rules from `.claude/rules/**/*.md` for files read through the runtime `read` tool.
- Keep the rule source of truth in the runtime filesystem; do not copy rule bodies into durable Toolkit State.
- Preserve the AGENTS.md instruction-loading policy: successful `read` output appendix, not Toolkit/system prompt injection.
- Implement the loader as a separate auto-bound runtime Toolkit so runtime hook provider order naturally controls output order.
- Support path-scoped rules through `paths` frontmatter using the same glob semantics as the repo-local Codex Claude-rules hook.
- Keep repo/config-level rule issues quiet: skip malformed or unsupported rule files without user-facing warnings or server log noise.
- Record system/runtime communication failures as errors instead of silently hiding infrastructure problems.

## Non-goals

- Support `.opencode/rules` in the initial product runtime feature.
- Support nested `.claude/rules` below arbitrary subdirectories inside a project.
- Inject Claude rules into the system prompt, Toolkit prompts, or turn-start user prompts.
- Block `write`/`edit` when a matching rule has not yet been loaded.
- Add user-facing settings or per-agent opt-in/out controls for Claude rules.
- Implement an external repo-local hook mechanism in Azents. The Codex hook remains reference behavior only.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
