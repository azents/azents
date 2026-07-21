---
title: "Separate Input Payload and Control Action with DB Source of Truth"
created: 2026-06-15
tags: [architecture, backend, engine, api, chat, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: input-260615
historical_reconstruction: true
migration_source: "docs/azents/adr/0061-input-control-plane-clean-migration.md"
---

# input-260615/ADR: Separate Input Payload and Control Action with DB Source of Truth

## Context

[chat-260519/ADR](./chat-260519-chat-input-buffer.md) decided to store user chat input in the `input_buffers` table and promote it to durable event at model-call boundary. [rest-260605/ADR](./rest-260605-rest-chat-write-boundary.md) moved Web chat writes to REST commit boundary and defined REST success as input buffer commit.

However, several payload carriers still remain in current engine ingress.

- `SessionMessage.messages` directly carries user input in broker payload.
- `SessionEditMessage` returns edited input through `SessionMessage.messages` again after history rewrite.
- `BackgroundCompletionMessage` carries background operation result as broker message and then lowers it to user-role model input.
- Slash command has executor lifecycle separate from input buffer, creating resolve/state handling paths duplicated with session runner lifecycle.
- If user stop is delivered only through broker signal, it can be lost in the very situations where users most often press stop: stuck/broker/runner abnormal states.

This structure turns Redis broker into a durable queue and distributes source of truth for input and control action. This change assumes production clean state and simplifies ingress model without intermediate compatibility layer.

## Decision

### input-260615/ADR-D1. `input_buffers` is the source of truth for session runner input payload

All model-visible payload processed by session runner is stored in `input_buffers`. This includes REST user messages, edited user messages, and background completion.

Broker message does not carry payload. Redis broker is responsible only for session wake-up and fast-path interrupt signal.

### input-260615/ADR-D2. Input buffer item has promotion/rendering taxonomy through `kind`

Add `input_buffers.kind` and adopt these kinds in first scope:

- `user_message`
- `edited_user_message`
- `background_completion`

Each kind decides durable event kind and UI rendering taxonomy. Model input role remains user role for all of them in first scope.

### input-260615/ADR-D3. Edit is idle-only history rewrite command

Edit is not input inserted during a run. Edit request locks session/runtime state inside DB transaction and is allowed only in idle state. If running, reject with 409 without sending to broker.

An accepted edit reverts transcript after target, deletes pending input buffers, creates `kind=edited_user_message` buffer, and transitions session to running in the same transaction.

### input-260615/ADR-D4. Background completion is stored as separate event kind and uses user role for model input

Background operation result is stored as `kind=background_completion` buffer. Promotion appends durable `background_completion` event and delivers it to model as user-role input as before. UI renders it as background/task result, not user bubble.

### input-260615/ADR-D5. Command is idle-only pending command, not input buffer

Slash command is a control action executed inside session lifecycle, not model input payload. Command request checks idle state and absence of pending command inside DB transaction, stores a single pending command, and transitions session to running. Reject with 409 if running, if pending command already exists, or if pending input remains in abnormal idle state.

Session runner handles pending command on loop tick if it exists; otherwise it handles input buffer.

### input-260615/ADR-D6. Stop is DB-backed running-only interrupt intent

Stop is neither input buffer nor command. Stop request first records durable stop intent in DB and sends broker stop signal as fast path. When runner receives broker signal, it sets in-memory stop event and immediately cancels active run. At the same time, runner/recovery checks DB stop intent to compensate for lost broker signal.

User stop must immediately interrupt even during LLM call, streaming, or foreground tool call. DB stop intent does not replace this fast path; it acts as fallback against signal loss.

### input-260615/ADR-D7. Broker ingress keeps only wake-up and stop signal

Remove broker payload carriers such as `SessionMessage.messages`, `SessionMessageKind.USER`, `SessionCommand`, `SessionEditMessage`, and `BackgroundCompletionMessage`. Final broker ingress has only session wake-up envelope and stop fast-path signal.

## Consequences

### Positive

- Source of truth for model input payload converges to `input_buffers`.
- Redis broker memory usage and retention risk decrease.
- State transitions for edit/command/stop are explained through DB transaction and runner lifecycle.
- Background completion has a UI taxonomy distinct from user message.
- Broker signal loss does not cause input/stop intent loss.

### Negative / Trade-offs

- `input_buffers` and `agent_runtimes` schema changes are needed.
- Event kind and frontend rendering taxonomy expand.
- Command and stop must implement idempotency/recovery clearly in DB state.
- This is a clean migration, so no intermediate compatibility with old broker payload during deploy.

## Alternatives

### Keep broker payload compatibility

Rejected. The goal of this change is separating payload source of truth, so supporting both `SessionMessage.messages` and buffer path keeps design confusion.

### Put command into input buffer

Rejected. Command is control action, not model input payload. Mixing it with user message makes ordering semantics unnecessarily complex. Idle-only pending command makes lifecycle clearer.

### Keep stop as broker signal only

Rejected. Stop is often used when runner/broker is unhealthy. Broker-only stop can be lost, so DB-backed intent is needed.

### Store background completion as `user_message` event

Rejected. Even if model input role remains user, durable transcript and UI must distinguish it from messages directly entered by user.

## Related Documents

- [chat-260519/ADR: Split chat input buffer into separate RDB table](./chat-260519-chat-input-buffer.md)
- [rest-260605/ADR: Chat writes use REST commit boundary](./rest-260605-rest-chat-write-boundary.md)
- [preemptive-260607/ADR: User stop uses preemptive interrupt and REST control boundary](./preemptive-260607-preemptive-stop.md)

## Migration provenance

- Historical source filename: `0061-input-control-plane-clean-migration.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
