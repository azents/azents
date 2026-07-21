---
title: "Runtime Exec Process Tools Historical Requirements Reconstruction"
created: 2026-06-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: exec-260627
historical_reconstruction: true
migration_source: "docs/azents/adr/0081-runtime-exec-process.md"
---

# Runtime Exec Process Tools Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `exec-260627`
- Source: `docs/azents/adr/exec-260627-exec-process.md`
- Historical source date basis: `2026-06-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently exposes a runtime-backed `bash` tool whose runner implementation behaves like a bounded foreground command: the runner executes a shell process, collects stdout/stderr, and returns one final tool result. The runtime coordination path already has stdout/stderr reply event types, but current bash execution does not model a live process that the agent can continue to poll or write to after the first tool call.

Codex's exec design uses a small process-oriented tool surface: `exec_command` starts a process and returns either an exit result or a running session id after a yield window; `write_stdin` writes to that session and also acts as an empty-input poll. Intermediate stdout/stderr is streamed as live events, not as repeated `function_call_output` items for the same tool call.

Azents needs a similar model to replace `bash` while preserving Azents boundaries:

- Agent Engine core must remain tool-agnostic.
- Runtime Runner is the only component that can own OS process handles.
- Runner is an external component; server/runtime lifecycle must not be inferred from runner process signals alone.
- Tool errors, missing processes, and process exits are observations returned to the model, not assistant/system failures.
- Live UI output needs structured process ids and event metadata.

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
