---
title: "Keep Pending Buffer Deletion State-Neutral"
created: 2026-07-12
tags: [architecture, api, backend, concurrency, session, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: pending-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0139-keep-pending-buffer-deletion-state-neutral.md"
---

# pending-260712/ADR: Keep Pending Buffer Deletion State-Neutral

## Context

A user may delete an accepted input buffer before its processor starts. Input acceptance already marks a wake-producing session as running and schedules a payload-free wake-up. If deleting the last pending buffer also tries to infer whether the session should become idle, the API duplicates SessionRunner lifecycle logic and can race active-run, pending-command, or newly accepted input state.

Long-running processors also require a clear boundary between deleting queued work and canceling already-claimed external side effects.

## Decision

Pending-buffer deletion mutates queue state only. It does not change AgentSession run state.

The delete operation participates in the shared Session row-lock protocol:

1. lock the AgentSession row;
2. lock or locate the target pending Buffer;
3. verify that no long-running processor has claimed the item;
4. delete the still-pending row;
5. commit before publishing its live-projection removal.

Deletion and processing are serialized by the same Session row lock. If deletion commits first, the processor never observes that Buffer. If an atomic processor commits first, the Buffer is already consumed and its durable semantic result is not reverted by the delete request.

Deleting a missing or already-consumed ordinary Buffer is idempotent success. The authoritative snapshot shows whether the input is still pending or has already become durable history.

A Buffer with a durable long-running action-execution claim is no longer ordinary pending work. The pending delete endpoint rejects it as processing; action-specific cancel, retry, or discard controls own its external side-effect lifecycle.

After deletion, queued or recovery wake-up processing remains responsible for session lifecycle. SessionRunner starts its processing cycle, observes that no Buffer and no prepared actionable state remain, creates no AgentRun or Turn, transitions the AgentSession to idle, and exits. Duplicate wake-ups use the same no-op path. A lost wake-up is compensated by stale-running recovery, which eventually reaches the same empty-cycle transition.

## Rejected Alternatives

### Transition the Session to idle in the delete API

The API would need to duplicate active-run and pending-work checks owned by SessionRunner and could mark a session idle while other execution state remains active.

### Create and immediately complete an empty AgentRun

A deleted input leaves no actionable model work. Recording a no-op AgentRun would pollute run history and execution metrics without representing a model or tool lifecycle.

### Delete a Buffer after long-running action claim

Removing the queue row does not cancel external work and can orphan its durable ActionExecution. The action control plane must own that transition.

## Consequences

- Buffer delete has no direct AgentSession state side effect.
- SessionRunner is the single owner of returning an empty processing cycle to idle.
- UI may briefly observe a running session with no pending Buffer until wake-up processing or recovery completes.
- Durable results that won the processing race remain in history.
- Long-running action controls stay separate from ordinary pending-message deletion.
- Tests must cover delete-before-process, process-before-delete, claimed-worktree rejection, duplicate wake-up, and lost-wake recovery.

## References

- [polymorphic-260712/ADR: Use Polymorphic Input Buffer Processors](./polymorphic-260712-polymorphic-input-buffer-processors.md)
- [linearize-260712/ADR: Linearize Input Buffer Boundaries on the Session Row Lock](./linearize-260712-linearize-input-buffer-boundaries-on-row-lock.md)

## Migration provenance

- Historical source filename: `0139-keep-pending-buffer-deletion-state-neutral.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
