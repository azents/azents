---
title: "Handle Message Edits as Transactional Preparation"
created: 2026-07-12
tags: [architecture, api, backend, database, engine, session, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: handle-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0127-handle-message-edits-as-transactional-preparation.md"
---

# handle-260712/ADR: Handle Message Edits as Transactional Preparation

## Context

The current edit path rewrites durable history and then creates an `edited_user_message` input buffer. The worker later promotes that buffer into a replacement `user_message` event. This splits one edit operation across the REST transaction and the input-buffer preparation loop, exposes the replacement as pending UI state, and adds a buffer kind whose behavior is not normal FIFO input preparation.

[drain-260712/ADR](./drain-260712-drain-input-buffers-before-turn-start.md) makes input-buffer processing a sequential preparation stage before turn start. An edit already requires an idle-only lock, durable history rewrite, and immediate history reload, so routing its replacement message through the buffer adds an unnecessary intermediate state.

## Decision

Remove `edited_user_message` from the input-buffer taxonomy. Handle an accepted message edit as one transactional REST preparation operation.

The edit transaction must:

1. Lock the target AgentSession row for update.
2. Verify that the session is idle, has no pending command, and has no pending input buffer.
3. Verify that the target is a visible editable `user_message` in the same session.
4. Resolve the edit's effective model and effort configuration using the same semantics as normal user-message preparation.
5. Soft-revert the target event and later visible history.
6. Append one immutable replacement `user_message` event, including edit lineage and the resolved inference configuration applied by the edit.
7. Update the AgentSession's current resolved inference configuration.
8. Transition the AgentSession to running and record its recovery heartbeat.
9. Record or validate REST write idempotency in the same transaction.

After commit, the API sends a payload-free session wake-up and returns `history_reload_required = true`. The replacement message is durable history immediately and is never exposed as a pending input-buffer projection.

Edit acceptance rejects the request instead of deleting accepted pending work when any of the following is true:

- the session is running;
- a pending command exists;
- any pending input buffer exists;
- the target is missing, reverted, not editable, or belongs to another session.

All session input writers must participate in the same AgentSession row-lock protocol before validating state and committing new pending input. The edit lock is not a complete concurrency boundary if another writer can read the old idle state and insert an input buffer without first acquiring that lock.

A wake-up no longer implies that an input buffer must exist. After draining pending buffers, SessionRunner checks durable prepared state for an unprocessed actionable event. The directly appended replacement event can therefore start the next turn using the final resolved session inference configuration.

## Rejected Alternatives

### Keep `edited_user_message` as a special input-buffer kind

This preserves the current worker promotion path but makes a durable history rewrite wait on a second state machine and shows an unnecessary pending replacement in the UI.

### Rewrite history in REST and enqueue a normal `user_message`

This removes the special kind but still splits one edit across durable rewrite and pending preparation. A failure or delay leaves the edit accepted while its replacement remains pending.

### Delete pending buffers when accepting an edit

Pending buffers represent already accepted user or system work. Deleting them silently to make an edit admissible loses accepted intent. The edit must be rejected until the queue is empty.

## Consequences

- `InputBufferKind.EDITED_USER_MESSAGE` and its promotion branch are removed rather than retained as compatibility behavior.
- Edit replacement events are complete and immutable when the REST transaction commits.
- The frontend reloads durable history after edit and does not render a pending edit bubble.
- Edit resolution, event append, session inference update, run-state transition, and idempotency acceptance share one transaction.
- SessionRunner must start work from prepared actionable durable state even when the input buffer is empty.
- Session row locking becomes a shared protocol for edit and normal input acceptance.
- Stale idle sessions with pending buffers reject edits and must be recovered instead of being repaired by destructive buffer deletion.

## References

- [rest-260605/ADR: Move Chat Writes to a REST Commit Boundary](./rest-260605-rest-chat-write-boundary.md)
- [input-260615/ADR: Migrate Chat Input and Control to a Clean Control Plane](./input-260615-input-control-plane-clean-migration.md)
- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [message-260712/ADR: Resolve User Message Profiles During Buffer Preparation](./message-260712-message-profile-during-buffer-preparation.md)

## Migration provenance

- Historical source filename: `0127-handle-message-edits-as-transactional-preparation.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
