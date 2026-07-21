---
title: "User Stop Uses Preemptive Interrupt and REST Control Boundary"
created: 2026-06-07
tags: [architecture, backend, frontend, api, chat, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: preemptive-260607
historical_reconstruction: true
migration_source: "docs/azents/adr/0052-preemptive-user-stop.md"
---

# preemptive-260607/ADR: User Stop Uses Preemptive Interrupt and REST Control Boundary

## Status

Accepted.

User stop is an explicit control action where the user wants to stop the current assistant run. Existing implementation delivered stop request as a broker queue message, and runner/engine detected it through a combination of queue drain, `check_stop`, and task cancellation. Some paths use task cancellation, but the design basis was still closer to waiting until execution flow observes stop or current process cleans up.

This decision defines user stop as a preemptive interrupt that takes priority over current run, and moves the last remaining WebSocket input, stop request, to REST control boundary.

## Background

[rest-260605/ADR](./rest-260605-rest-chat-write-boundary.md) moved chat message/edit/command writes to REST commit boundary and left only stop request as WebSocket control. As a result, WebSocket handled both live subscription and stop input. Moving stop to REST makes WebSocket a server-to-client live projection-only channel.

User stop and shutdown/handover stop have different durable meanings. User stop is a terminal interrupt where the user intentionally stops the current run. Shutdown/handover stop interrupts execution for process or execution-owner transition, and should remain a continuation/recovery target rather than terminal.

The core of stop handling is clarifying meaning by current engine state.

- In idle state, stop is a durable no-op because there is no active run to stop.
- During LLM call or streaming, stop immediately cancels provider call/stream, promotes only savable live assistant text to durable history, and closes run as `interrupted`.
- During tool calling, stop sends cancel signal to active foreground tools fire-and-forget, fills active tool calls without results with cancelled results, and closes run as `interrupted`.

## Decisions

### preemptive-260607/ADR-D1. User stop is a preemptive interrupt over current run

User stop takes priority over current run's model call, streaming, and foreground tool execution. When stop request applies to an active run, engine switches immediately to cancellation path instead of waiting for current work to finish naturally.

Cooperative boundaries such as `check_stop` may remain as fallback or safety net, but primary user stop path is immediate interrupt of active execution handle.

### preemptive-260607/ADR-D2. User stop in idle state is durable no-op without ack

If user stop arrives when there is no active run, do not create durable history, run marker, or terminal status. Do not deliver separate semantic ack/result.

Idle stop must not latch into the next run. A stop flag received while idle must not immediately interrupt a future run.

### preemptive-260607/ADR-D3. User stop during LLM call/streaming cancels immediately and durably stores only assistant text

If user stop arrives during LLM call or streaming, immediately cancel provider call/stream and close underlying HTTP response/body stream. Among live state at stop time, only non-empty assistant text is promoted to durable history. Source of this assistant text is engine streaming accumulator, not Redis/live projection.

The following live state is excluded from stop-time promotion:

- reasoning live state
- partial tool/function call delta
- usage or token accounting live state
- provider raw/native chunk

If assistant text exists, store it as durable assistant message and close current run as `interrupted` terminal. If no assistant text exists, leave only `interrupted` terminal without assistant message.

### preemptive-260607/ADR-D4. User stop during tool calling sends cancel signal fire-and-forget

If user stop arrives during tool calling, send cancel signal to active foreground tool calls. Engine does not wait until the tool actually terminates.

Tool cancel capability is provided as optional cancellation hook. Normal callable tools receive only coroutine task cancellation. Tools with subprocesses, such as shell/bash, call TERM signal or runtime cancel API in optional hook and then forget. Follow-up KILL, process reap, sandbox cleanup, and similar work are tool/runtime cleanup responsibility and do not delay current run terminal handling.

### preemptive-260607/ADR-D5. Tool calling stop fills unresolved active tool calls with cancelled results

On stop during tool calling, keep completed tool results already in durable history. Active foreground tool calls without result are filled with durable `client_tool_result` in cancelled state.

Overall run terminal is `interrupted`. Tool-level status expresses cancellation, while run-level status expresses interruption by user stop.

Stop handling first terminates active tool result collection loop. If a tool finishes later, current run append path is already closed, so completed result is not appended to durable history.

### preemptive-260607/ADR-D6. Streaming tool partial persistence is out of scope

This decision assumes completed-result-centered tool execution. If future tools provide streaming output, separate design will decide which tool live state should be promoted to durable history.

In this scope, stop during tool calling does not persist partial tool output.

### preemptive-260607/ADR-D7. Separate terminal meaning of user stop and shutdown/handover stop

User stop closes current run as `interrupted` terminal.

Stop for shutdown or handover is a non-terminal stop that interrupts current execution for worker shutdown, process restart, execution owner change, or recovery/resume. This path is a continuation/recovery target and does not leave the same interrupted marker or model-visible user interruption marker as user stop.

### preemptive-260607/ADR-D8. User stop interruption is delivered to model input as user-role synthetic control event

The fact that a run was interrupted by user stop is delivered to the next model input. However, do not use system role. Some providers aggregate system prompt into one unit and do not guarantee message ordering.

Do not use assistant role either. Assistant-role marker risks the model repeating the same marker in the next assistant output.

Therefore, model lowering inserts interruption fact as a user-role synthetic XML control event. Control event type is `run_interrupted`, and content is `The previous assistant run was interrupted by the user.` This control event is not stored as canonical user message and is not rendered in UI as a normal user message.

### preemptive-260607/ADR-D9. Stop button uses REST endpoint

Chat stop control does not use WebSocket input. Stop button sends user stop request through REST endpoint.

REST stop does not require semantic result. It is designed around the assumption that after success response, state will eventually converge to stopped without a separate status result.

### preemptive-260607/ADR-D10. Chat WebSocket becomes live subscription-only channel

After stop input moves to REST, WebSocket no longer receives client-to-server chat input. Chat WebSocket works only as a subscription channel delivering history/live projection server-to-client.

Remove existing WebSocket `{ "type": "stop" }` input path and message/edit/command write compatibility path. WebSocket endpoint does not process client payload or return compatibility responses.

## Rejected Directions

### Return semantic ack for idle stop

Rejected. Stop is not designed as a structure where UI judges state from a separate result; once processed, it eventually converges to stop state. Idle stop is durable no-op and does not create semantic result such as `already_idle`.

### Persist all live state during LLM streaming stop

Rejected. Reasoning, partial tool call, usage, and provider raw chunk cannot be guaranteed as valid canonical payload at stop time. Reasoning in particular can be encrypted or opaque fragments per provider, and partial tool call has no executable meaning.

### Wait for tool cancellation to finish before closing run

Rejected. The purpose of tool stop is to preempt current run. Waiting for tool termination ties stop again to long-running process or stuck subprocess. Engine sends cancel signal, fills unresolved tool calls with cancelled results, and closes run.

### Insert user stop marker into model input as system role or assistant role

Rejected. System role has weak ordering guarantee because providers aggregate it differently. Assistant role risks the model repeating marker as assistant output. User-role synthetic control event better balances ordering guarantee and risk of re-output.

### Keep WebSocket stop input

Rejected. If only stop remains as WebSocket input after message/edit/command move to REST, WebSocket handler still owns bidirectional write/control responsibility. Move stop to REST too, simplifying WebSocket to live subscription only.

## Consequences

### Expected Benefits

- User stop interrupts current run without waiting for current model call or tool execution to finish.
- Durable meanings of user stop and shutdown/handover stop are separated.
- LLM streaming stop preserves assistant text the user saw where possible, while avoiding risky partial reasoning/tool/usage state.
- Tool stop quickly closes run through fire-and-forget cancel signal, not tied to long-running process.
- Model receives conversation state that previous assistant run was interrupted by the user through order-preserving user-role synthetic control event.
- Chat WebSocket becomes live subscription-only channel.

### Cost and Risks

- `RunStopController` must clearly own active run handle, stop reason, duplicate stop idempotency, and idle no-op.
- Cancellation reason must distinguish user stop, shutdown/handover stop, and similar cases.
- Engine streaming accumulator assistant text must be safely materialized as canonical assistant message during stop cleanup.
- Since tool cancel signal is fire-and-forget, active result collection loop termination and unresolved result filling are needed.
- REST stop endpoint and frontend generated client migration are needed.
- Deployment order and old frontend compatibility must be checked after removing WebSocket receive path.

## Related Documents

- [chat-260519/ADR: Split chat input buffer into separate RDB table](./chat-260519-chat-input-buffer.md)
- [chat-260604/ADR: Chat protocol uses canonical event history/live API](./chat-260604-chat-protocol-history-live.md)
- [live-260604/ADR: Define chat live/history handoff and streaming partial batching](./live-260604-live-history-projection-handoff-and-stream-batching.md)
- [rest-260605/ADR: Chat writes use REST commit boundary](./rest-260605-rest-chat-write-boundary.md)

## Migration provenance

- Historical source filename: `0052-preemptive-user-stop.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
