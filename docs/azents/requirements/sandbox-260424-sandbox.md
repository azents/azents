---
title: "Move Sandbox Scope from Agent to Session Historical Requirements Reconstruction"
created: 2026-04-24
implemented: 2026-04-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260424
historical_reconstruction: true
migration_source: "docs/azents/adr/0001-per-session-sandbox.md"
---

# Move Sandbox Scope from Agent to Session Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260424`
- Source: `docs/azents/adr/sandbox-260424-sandbox.md`
- Historical source date basis: `2026-04-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current nointern sandbox uses a **per-agent** model: one `RDBAgent` maps to one persistent container shared by multiple sessions. This design was chosen for the product value of "the whole team talks to one agent," and lifecycle, hibernation, and snapshot infrastructure was built across Phases 1-3 (`docs/nointern/design/agent-home.md`, `phase3-snapshot-hibernation.md`).

However, the following problems became clear:

1. **Contention between sessions**: Multiple sessions can send exec calls into one container at the same time, causing possible file conflicts and process interference. The allocation step in `agent_home_manager.py` has a lock, but the execution step is not serialized.
2. **No failure isolation**: A runaway process in one session can break the entire agent container.
3. **Billing unit mismatch**: An agent-level container remains alive even when idle, which does not align with usage-based billing.
4. **Poor coding UX**: The rootfs of a long-running coding session can be disturbed by another session.

Meanwhile, the industry—Devin, OpenAI Codex cloud, OpenHands, Cursor Background Agents, E2B, and Modal—has converged on the pattern of **session/task-scoped ephemeral sandboxes plus agent-level snapshots**. Research: Discussion [#2968](https://github.com/azents/azents/discussions/2968).

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
