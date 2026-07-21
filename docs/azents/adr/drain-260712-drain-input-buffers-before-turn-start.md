---
title: "Drain Input Buffers Sequentially Before Turn Start"
created: 2026-07-12
tags: [architecture, agent, backend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: drain-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0125-drain-input-buffers-before-turn-start.md"
---

# drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start

## Context

The current input-buffer path treats pending inputs as chunks that may be promoted together according to action and requested-profile boundaries. It may also inject matching pending input at a later model-call boundary inside an active run. This makes buffer draining, run selection, and turn execution part of one combined operation.

That coupling complicates ordering and message-type semantics. Different buffer kinds need different preparation effects, but chunk promotion requires deciding their shared run behavior before each item has been handled independently.

## Decision

Input-buffer processing is a preparation stage for the next turn, separate from turn execution.

A session processes pending input buffers one item at a time in durable FIFO order. It does not start the next turn while any pending input buffer remains. After one item has been processed, the session checks the next item and continues until the buffer is empty. Only then may the session evaluate the prepared durable state and start the next turn.

This decision replaces chunk-oriented promotion and active-run join behavior. In particular, consecutive buffers are not claimed as one profile-based chunk, and pending input is not injected into an already-started turn merely because its requested profile matches the active run.

Message-kind-specific preparation behavior, turn eligibility, requested-profile selection, failure handling, and the atomic boundary between observing an empty buffer and starting a turn are defined by the follow-up feature design. This ADR establishes only the lifecycle boundary and sequential-drain invariant.

The one-`AgentRun`/one-resolved-main-model invariant from [prompt-260710/ADR](./prompt-260710-prompt-fifo-boundaries.md) remains. This ADR supersedes [prompt-260710/ADR](./prompt-260710-prompt-fifo-boundaries.md) only where [prompt-260710/ADR](./prompt-260710-prompt-fifo-boundaries.md) allows multiple pending inputs to be promoted as one FIFO profile segment or joined into an active run.

## Rejected Alternative

### Promote the largest currently compatible buffer chunk

This reduces the number of flush operations, but makes chunk compatibility part of input semantics and couples requested-profile boundaries to buffer storage. Message kinds with preparation side effects must then participate in chunk construction even when they do not have the same turn behavior.

### Start a turn as soon as the first actionable buffer is processed

This minimizes latency for the head item, but leaves later accepted inputs pending while the turn is already active. The resulting behavior depends on model-call polling and active-run join rules rather than on a single deterministic preparation boundary.

## Consequences

- Input-buffer order becomes an item-level processing order rather than a chunk-construction order.
- The session must reach an empty-buffer boundary before starting a turn.
- A burst of pending inputs is prepared sequentially and can normally be drained quickly before model execution begins.
- Each buffer kind can define its own durable preparation effect without changing the queue-drain algorithm.
- Turn creation, inference-profile selection, and model dispatch move after buffer draining.
- The empty-buffer check and turn-start claim require an explicit concurrency design so a newly accepted input cannot be skipped across the boundary.
- Existing profile-prefix flush logic and active-run boundary polling must be replaced during implementation.

## References

- [chat-260519/ADR: Split Chat Input Buffer into Separate RDB Table](./chat-260519-chat-input-buffer.md)
- [prompt-260710/ADR: Per-Prompt Models Form FIFO Run Boundaries](./prompt-260710-prompt-fifo-boundaries.md)

## Migration provenance

- Historical source filename: `0125-drain-input-buffers-before-turn-start.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
