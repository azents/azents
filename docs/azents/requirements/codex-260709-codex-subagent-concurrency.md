---
title: "Codex-Compatible Subagent Concurrency Historical Requirements Reconstruction"
created: 2026-07-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: codex-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0099-codex-compatible-subagent-concurrency.md"
---

# Codex-Compatible Subagent Concurrency Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `codex-260709`
- Source: `docs/azents/adr/codex-260709-codex-subagent-concurrency.md`
- Historical source date basis: `2026-07-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents adopted a Codex-first subagent model and completed the first hardening pass for prompt wording, `fork_turns`, parent/child write boundaries, and subagent tree projection. The next phase needs to enable model-visible concurrency semantics before Azents can safely reintroduce Codex-style concurrency-slot prompt text and proactive delegation guidance.

Codex multi-agent v2 exposes a configured maximum concurrent thread count to the model with this wording:

```text
There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
```

In Codex, the configured default is `max_concurrent_threads_per_session = 4`. The value includes the root/parent agent, so the effective active subagent capacity is `max_concurrent_threads_per_session - 1`, which is `3` by default. Codex also has a configurable agent nesting depth with default `max_depth = 1`, allowing root-to-child spawning by default while requiring configuration for deeper nesting.

Codex normal `spawn_agent` behavior applies backpressure by failing when the active subagent limit is exhausted. It does not queue normal spawn requests. Separate job-style schedulers may keep work pending and retry later, but that is a scheduler concern rather than the normal collaboration-tool spawn semantic.

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
