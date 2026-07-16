---
title: "ADR-0157: Keep OpenAI HTTP Failure Semantics at the Azents Boundary"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, reliability, security]
---

# ADR-0157: Keep OpenAI HTTP Failure Semantics at the Azents Boundary

## Status

Accepted. Implementation has not started.

## Context

The official OpenAI SDK supplies typed HTTP, connection, timeout, status, and streaming event failures. Its exception strings and response objects may contain provider response bodies or request identifiers. Propagating those exceptions directly would make sampling, compaction, and automatic Session title behavior depend on SDK presentation details and could expose data that Azents does not log or persist.

Azents already owns model-call connection configuration, parsed-event idle and absolute attempt deadlines, User Stop priority, stream cleanup, terminal event requirements, failed-run classification, and user-safe failure messages. The transport migration should preserve those product boundaries while replacing LiteLLM-specific exception handling with official SDK types.

## Decision

The OpenAI HTTP adapter maps official SDK outcomes into the existing Azents timeout, cancellation, and failure contracts.

### Timeout and cancellation ownership

Each physical SDK request receives the existing connect-only HTTP timeout. The SDK retry default from ADR-0155 remains active. Retry and backoff time is contained within the same outer parsed-event idle and absolute attempt deadlines.

A final SDK timeout is converted through the existing model connection timeout path. Parsed-event idle and absolute attempt expiry remain generated only by `ModelStreamWatchdog`.

`asyncio.CancelledError` is never converted to a provider or model failure. It is re-raised immediately after the watchdog initiates stream cleanup. The logical operation closes its SDK client during finalization as established by ADR-0156. User Stop retains priority over a concurrent watchdog expiry.

### Stream terminal semantics

Typed `response.failed`, `response.incomplete`, `error`, and `response.error` events fail normalization before durable model output is appended. Stream exhaustion without a recognized `response.completed` event also fails. A successfully completed stream is never reclassified from partial output alone.

### Safe SDK exception mapping

Provider-originated SDK exceptions are converted at the adapter boundary without copying raw exception strings, provider response bodies, request IDs, response IDs, request input, response output, or raw frames into user messages, durable failure state, or structured logs.

- Final 401, 403, 429, and 5xx status failures preserve the current user-visible `ModelCallError` boundary with fixed safe messages.
- Other final 4xx responses, connection failures, and SDK-internal provider parsing failures become sanitized internal failures rather than exposing provider text.
- Safe operational metadata may include the SDK exception class, HTTP status, and a bounded provider error code.
- Unexpected errors that do not originate from the SDK or provider payload remain normal programming failures and propagate without being disguised as provider failures.

Sanitized SDK mappings do not retain the raw exception as a displayed cause. Operator logging uses the safe domain exception and metadata rather than serializing the SDK request or response object.

## Consequences

- Sampling, compaction, and title generation share one transport failure vocabulary despite using different operation lifetimes.
- SDK implementation details do not become user-facing product behavior.
- Existing Azents watchdog deadlines and User Stop semantics remain authoritative.
- Default SDK retries can recover transient pre-stream failures, while mid-stream failures retain the existing Azents behavior.
- Provider request and response identifiers and bodies do not enter logs or durable failed-run state through exception formatting.
- Tests require status, connection, timeout, cancellation, terminal-event, premature-EOF, cleanup, and redaction fixtures.

## Alternatives Considered

### Propagate official SDK exceptions directly

Rejected because exception presentation is not a stable product contract and may include provider data or identifiers that Azents must not expose.

### Replace the Azents watchdog with SDK timeouts

Rejected because SDK HTTP timeouts do not implement parsed-event idle deadlines, absolute model-attempt deadlines, User Stop priority, or process-owned cleanup for non-cooperative streams.
