---
title: "ADR-0150: Define the OpenAI Responses WebSocket Lifecycle"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, websocket]
---

# ADR-0150: Define the OpenAI Responses WebSocket Lifecycle

## Status

Draft. Paused until the OpenAI-native HTTP lowerer and SDK HTTP migration are designed, implemented, and validated. Recorded WebSocket discussion remains provisional and must be revalidated before this ADR is accepted.

## Context

ADR-0147 establishes the OpenAI-native Responses transport family: official OpenAI SDK HTTP is migrated first, then WebSocket becomes the preferred Agent transport with the same SDK HTTP path as its physical fallback. This ADR records the WebSocket lifecycle decisions before implementation.

The OpenAI WebSocket protocol keeps one most-recent response continuation state on the active connection. A socket handles one response at a time, has a 60-minute service limit, and cannot restore `store=false` continuation state after reconnection. Connection ownership therefore determines continuation safety, worker handover behavior, and cleanup.

Codex provides a relevant but not directly identical precedent. Its `ModelClient` is conversation-session scoped, while `ModelClientSession` is turn scoped. Codex lazily opens one socket, reuses it for sequential turns, sends an incremental request only when strict request-extension checks pass, invalidates the socket on terminal stream failure, and switches the remainder of the Codex session to OpenAI HTTP after exhausting its WebSocket retry budget.

## Confirmed Constraints

- OpenAI WebSocket and HTTP use the same canonical OpenAI lowerer, official SDK, and output-normalization contract.
- LiteLLM does not send OpenAI fallback requests.
- ChatGPT OAuth remains full-context HTTP with `store=false`.
- Logical transcript lowering, compaction, file materialization, and `NativeRequestSizeGuard` remain ahead of physical transport planning.
- WebSocket continuation state is in memory, bound to one socket generation, and cleared when that socket is replaced or fails.
- Logs do not contain response IDs, request inputs, model outputs, or raw WebSocket frames.
- Compatibility modes and legacy OpenAI transport branches are not retained after migration.

## Current Azents Session Ownership Evidence

Azents already has a resident per-Session worker scope rather than assigning every follow-up input to an arbitrary worker immediately:

- Redis stores a sticky Session owner lease with a 30-minute TTL.
- A separate owner heartbeat has a 120-second TTL and is refreshed every 30 seconds while a Run is active and while its `SessionRunner` is idle.
- Follow-up wake-ups route directly to the live owner worker.
- `SessionRunner` survives across Agent Runs, processes them sequentially, and owns a Session-scoped toolkit lifecycle until idle timeout, shutdown, or handover.
- Graceful runner exit cleans Session-scoped resources and immediately releases the owner lease and heartbeat.
- Worker crash or loss permits another worker to take over after the heartbeat becomes stale; in-memory resources are not handed over.

The current implementation has two lease-timing discrepancies that must be resolved before treating the runner as a precise 30-minute inactivity scope.

First, `SessionRunner._loop()` creates `idle_started_at` once and repeatedly passes that same float into `_tick()`. `_tick()` assigns a new local value after processing a message but does not return it to `_loop()`. The effective runner timeout is therefore measured from runner-loop creation rather than reliably resetting after the most recently processed message, despite the spec defining 30 minutes of Session idle time.

Second, both active-Run and idle heartbeat loops refresh the 120-second owner-heartbeat key every 30 seconds, but they do not refresh the 30-minute owner lock. The owner lock is refreshed separately when an engine event is dispatched. A continuously active but event-silent operation can therefore lose its owner lock after 30 minutes even while its heartbeat loop remains healthy. Session-scoped transport ownership requires the active owner renewal path to keep the lock and heartbeat consistent until the Run becomes idle.

## Decision: SessionRunner Owns the WebSocket

One `SessionRunner` owns at most one active OpenAI Responses WebSocket transport context. It opens the socket lazily on the first eligible Agent model call and reuses it across sequential model calls and Agent Runs while the same runner retains sticky Session ownership.

`AgentRunExecution` borrows the Session-owned transport and does not close a healthy socket on ordinary Run completion. The `SessionRunner` closes the socket and clears its continuation state during its existing Session-resource cleanup, before releasing ownership on idle timeout, graceful shutdown, or handover. A crashed worker transfers no connection or continuation state; the takeover worker opens a new socket and begins with a full request lowered from the durable canonical transcript.

This scope does not create a worker-global or cross-Session pool. `SessionRunner` already serializes work for one Session, matching the protocol rule that one socket processes one response at a time. Independent one-shot calls outside that lifecycle, including automatic Session title generation, continue to use OpenAI SDK HTTP.

The Session idle-baseline and active owner-lock renewal discrepancies identified above must be corrected and covered by lifecycle tests before WebSocket reuse relies on this ownership boundary.

## Decision: Continuation Requires a Strict Request Extension

Azents always completes canonical transcript lowering, compaction, file materialization, and `NativeRequestSizeGuard` evaluation against the full logical OpenAI request. Only the physical WebSocket transport planner may replace that full input with an incremental request.

The Session-owned transport keeps at most one latest completed continuation boundary: socket generation, OpenAI credential and integration identity, a deep copy of the full request, the response ID, and sanitized completed output items. It sends `previous_response_id` with only new input when all of these conditions hold:

- the boundary belongs to the currently active socket generation and credential/integration identity;
- model, instructions, tools, reasoning, include, sampling, prompt-cache, and every other non-input request property match exactly;
- the current full input is a strict extension consisting of the prior full input, followed by the prior completed output items, followed by at least one new input item.

Any mismatch sends the full request on the same healthy socket. A successfully completed full or incremental response replaces the one saved boundary.

WebSocket requests use `store=false`, so continuation exists only in the active socket's server-side cache and Azents process memory. HTTP fallback and a new Session owner always send the full logical request. Azents clears the boundary on socket close, rotation, reconnect, worker handover, HTTP fallback, terminal stream error, credential/integration change, provider continuation rejection, or failure of a full request. Response IDs are never persisted or logged.

Always sending the apparent transcript tail was rejected because property changes, compaction, or native-item differences could silently change model context. Restricting continuation to one Agent Run was rejected because the selected Session-owned socket can safely reuse a strictly verified boundary across sequential Runs.

## Decision: HTTP Fallback Is Sticky for the SessionRunner Lifetime

The Session-owned transport starts in WebSocket mode. Once an eligible WebSocket failure activates HTTP fallback, the transport closes and clears the cached socket and continuation boundary, records HTTP as the active mode, and uses OpenAI SDK HTTP for every remaining model call and failed-Run retry handled by that `SessionRunner`. It does not probe or return to WebSocket after a cooldown or successful HTTP call.

WebSocket eligibility resets only when the current `SessionRunner` ends and a later owner creates a new Session transport scope. This matches Codex's session-scoped fallback state while using the Azents sticky ownership lifetime as the session boundary.

HTTP fallback is skipped when it would predictably repeat the same failure. Local lowering or validation errors, request-schema and unsupported-parameter errors, authentication and authorization failures, model or quota errors, provider-declared response failure, and other transport-independent failures propagate directly to the model-call failure boundary. WebSocket-specific upgrade, connection, framing, and network failures may activate HTTP fallback. Protocol-specific classifications and the exact relationship between transport fallback and model-call retry are defined below.

SDK automatic WebSocket reconnect remains disabled so Azents can keep retry and fallback ownership explicit.

## Proposed Azents Model-Call Retry Rules

This section is a discussion draft rather than an accepted decision.

One logical model call owns a retry loop above both physical transports. The full lowered and size-checked request remains constant for that loop. A WebSocket retry after connection loss always opens a new socket, clears continuation, and sends the full request. A successful strict continuation request remains an ordinary first attempt rather than a different retry class.

The proposed state machine is:

1. If the Session transport mode is WebSocket, attempt WebSocket first.
2. An HTTP 426 WebSocket upgrade response immediately activates sticky HTTP fallback and reruns the same logical model call over HTTP without another WebSocket attempt.
3. A retryable WebSocket-only failure retries WebSocket with bounded backoff while the WebSocket budget remains.
4. When that budget is exhausted, activate sticky HTTP fallback, reset the model-call transport retry counter, and rerun the same logical model call over HTTP.
5. A retryable HTTP failure uses the HTTP retry budget established by the Phase 1 SDK HTTP adapter.
6. Exhausting HTTP retries fails the logical model call and enters the existing failed-Run boundary.
7. A transport-independent or non-retryable error fails the logical model call immediately without switching transports.
8. Once HTTP fallback activates, every later model call and failed-Run retry in the same `SessionRunner` starts and remains on HTTP.

WebSocket retryable/fallback-eligible failures initially include upgrade and handshake transport failures other than authentication or request rejection, connect timeout, network close, WebSocket framing or envelope decode failure, retryable WebSocket service status, and `websocket_connection_limit_reached`. A provider model failure, rate or quota rejection, authentication or authorization failure, invalid request, unsupported option, lowering or size-guard failure, and other transport-independent errors do not activate HTTP fallback.

A model-call retry after any parsed event requires Azents to remove that call attempt's assistant and reasoning live projections before the next physical attempt begins. It must never mix events from the failed WebSocket stream with the HTTP or replacement-WebSocket stream. Completed durable output and executed client tool calls are not rolled back; therefore retry remains disallowed after the logical model call has crossed its explicit completion boundary.

The retry loop remains inside one Azents model-call watchdog attempt. Its backoff, WebSocket retries, and HTTP fallback do not reset the parsed-event idle or absolute attempt clocks; only a newly parsed provider event resets the idle clock. Each new connection still receives the common connection-establishment timeout. This preserves ADR-0146 and prevents physical transport retries from multiplying the 30-minute absolute bound.

The retry counts remain an open decision. Codex defaults to five stream retries before fallback, but Azents also has a durable failed-Run retry layer, so copying that numeric budget would multiply worst-case provider attempts. The initial Azents budget should be selected together with the failed-Run interaction; two WebSocket retries before fallback and two HTTP retries after fallback are the current starting proposal, both constrained by the one shared watchdog attempt.

## Subsequent Decisions

After ownership is confirmed, this ADR will record:

- lazy connection, preconnect, idle close, and rotation policy;
- strict delta-continuation eligibility and full-request fallback;
- handshake, pre-first-event, and post-first-event failure boundaries;
- protocol error classification and bounded retry budgets;
- cancellation, timeout, socket close, and worker-shutdown cleanup;
- performance, reliability, and live verification gates.
