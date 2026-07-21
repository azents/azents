---
title: "Separate Input Acceptance and Processing Idempotency"
created: 2026-07-12
tags: [architecture, api, backend, database, idempotency, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: input-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0138-separate-input-acceptance-and-processing-idempotency.md"
---

# input-260712/ADR: Separate Input Acceptance and Processing Idempotency

## Context

The current input-buffer table accepts an optional idempotency key scoped to `(session_id, kind, idempotency_key)`. REST writes also carry `client_request_id`, and some control operations use `chat_write_requests`. Splitting one user-write contract across these mechanisms allows the same request id to create different buffer kinds and lets a same-kind retry return an existing buffer without validating the full payload.

Input acceptance and processor retry are separate idempotency problems. The producer knows whether two requests represent the same intent, while the processor knows which semantic events and side effects belong to one accepted buffer.

## Decision

Separate producer acceptance idempotency from buffer processing idempotency.

### Producer acceptance

Each input producer owns its domain-specific duplicate contract before appending a buffer.

REST user messages and TurnActions use `chat_write_requests` scoped to `(session_id, user_id, client_request_id)`. Reuse of the same key must validate the accepted write type and the full normalized payload, including message content, action payload, inference overrides, and attachment references. A matching retry returns the same accepted target and current authoritative snapshot. A conflicting retry fails without creating another buffer.

Edit uses the same REST acceptance mechanism but follows [handle-260712/ADR](./handle-260712-handle-message-edits-as-transactional-preparation.md) and directly commits its durable replacement event rather than creating a buffer.

Internal producers define idempotency from their own source identity when required. Goal continuation and Agent mailbox producers do not inherit a generic REST-style key merely because they use the same storage primitive.

The low-level InputBuffer writer appends the producer's already-accepted input. It does not interpret a generic idempotency key, compare source payloads, choose wake behavior, or own producer-specific duplicate policy. Remove the generic `(session_id, kind, idempotency_key)` contract and related service validation when producer migrations are complete.

### Processing outcome

The immutable InputBuffer id is the source identity for processor results. Each concrete processor derives deterministic identifiers for its semantic outputs, for example:

- `<buffer-id>:user_message`;
- `<buffer-id>:goal_updated`;
- `<buffer-id>:skill_loaded`;
- `<buffer-id>:action_execution_result`.

Atomic processors commit their domain-state changes, semantic events, session inference update, and source-buffer deletion together. A rollback leaves none of those results committed.

Long-running multi-transaction processors use the Buffer id as their durable action-execution source/claim identity. Recovery resumes or observes that same execution instead of starting another external side effect. Their terminal commit appends deterministic result events and consumes the source buffer exactly once.

## Rejected Alternatives

### Keep only generic InputBuffer idempotency

The buffer layer cannot validate producer-specific payload meaning and its kind-scoped key permits one client request id to create multiple side effects.

### Keep both generic buffer and producer acceptance idempotency

Overlapping uniqueness rules create ambiguous conflict behavior and duplicate lookup paths without adding protection once producer acceptance and deterministic processor outcomes are correct.

### Let processors use random event or execution ids on every attempt

Recovery after a partial long-running operation could repeat external work or append duplicate semantic results.

## Consequences

- REST input acceptance becomes consistent across messages, TurnActions, and edits.
- Low-level buffer storage has a smaller responsibility and no source-specific duplicate semantics.
- Internal producers must explicitly document their own source identity and duplicate behavior where needed.
- Every processor output requires a deterministic Buffer-derived identity.
- InputBuffer schema and repository APIs lose the generic idempotency-key constraint after migration.
- Concurrency tests must cover identical retries, conflicting retries, cross-kind key reuse, transaction rollback, and worktree recovery.

## References

- [rest-260605/ADR: Move Chat Writes to a REST Commit Boundary](./rest-260605-rest-chat-write-boundary.md)
- [codex-260706/ADR: Redesign Subagents Around the Codex Model](./codex-260706-codex-subagent-redesign.md)
- [handle-260712/ADR: Handle Message Edits as Transactional Preparation](./handle-260712-handle-message-edits-as-transactional-preparation.md)
- [polymorphic-260712/ADR: Use Polymorphic Input Buffer Processors](./polymorphic-260712-polymorphic-input-buffer-processors.md)
- [linearize-260712/ADR: Linearize Input Buffer Boundaries on the Session Row Lock](./linearize-260712-linearize-input-buffer-boundaries-on-row-lock.md)

## Migration provenance

- Historical source filename: `0138-separate-input-acceptance-and-processing-idempotency.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
