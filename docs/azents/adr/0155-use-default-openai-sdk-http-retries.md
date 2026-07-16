---
title: "ADR-0155: Use Default OpenAI SDK HTTP Retries"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, reliability]
---

# ADR-0155: Use Default OpenAI SDK HTTP Retries

## Status

Accepted. Implementation has not started.

## Context

The official OpenAI Python SDK retries transient HTTP failures before returning a successful response or final exception to its caller. In the pinned 2.45.0 release, the default `max_retries` value is two, allowing up to three physical HTTP requests for one SDK call.

The retry policy covers transport exceptions and initial HTTP responses including 408, 409, 429, and 5xx. It honors bounded `retry-after-ms` and `retry-after` values and the provider-specific `x-should-retry` override before falling back to exponential backoff with jitter. It does not restart a Responses stream after a successful HTTP response has been returned and stream events have begun.

Azents could disable SDK retries so one application model attempt always maps to one physical HTTP request. That would make request counts exact at the Azents attempt boundary, but it would promote short transport, rate-limit, and server failures into the durable failed-run retry path instead of allowing the official SDK to recover them immediately.

## Decision

OpenAI API-key and ChatGPT OAuth Responses HTTP clients use the official OpenAI SDK retry default. Azents does not set `max_retries=0` and does not replace the SDK retry schedule with an adapter-local equivalent.

SDK retries remain internal to one Azents model attempt. Azents records and classifies only the final SDK result or exception; it does not promote each physical SDK retry into a separate durable attempt.

The SDK retry boundary ends when a successful streaming HTTP response is returned. Parsed-event idle, absolute attempt, cancellation, stream cleanup, semantic terminal failures, and premature stream exhaustion remain owned by the existing Azents watchdog and output normalization contracts.

The connect-only HTTP timeout applies to each physical SDK request. The outer parsed-event idle and absolute attempt deadlines include SDK retry and backoff time. The exact `previous_response_not_found` continuation fallback remains an explicit adapter operation because that response is not part of the SDK transient retry policy.

## Consequences

- One Azents attempt may issue up to three physical HTTP requests under the pinned SDK default.
- Brief connection failures, 408, 409, 429, and 5xx responses may recover without entering durable failed-run retry.
- Azents attempt counts do not represent exact provider request counts.
- A request that may have reached the provider before a transport failure can be submitted again; the SDK does not provide an Azents-visible deduplication guarantee for this path.
- SDK retry and backoff latency consume the same outer Azents attempt deadline.
- Mid-stream disconnects are not retried by the SDK and retain the existing Azents failure behavior.
- Upgrading the pinned OpenAI SDK requires reviewing any change to its default retry count, retryable status set, and backoff policy.

## Alternatives Considered

### Disable SDK HTTP retries

Rejected because short provider and transport failures should use the official SDK recovery behavior instead of immediately entering the durable failed-run retry boundary.

### Reimplement the SDK retry policy in the Azents adapter

Rejected because it would duplicate official SDK transport behavior without adding a product-level semantic boundary.
