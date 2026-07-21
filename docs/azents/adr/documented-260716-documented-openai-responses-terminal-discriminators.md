---
title: "Use Documented OpenAI Responses Terminal Discriminators"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, streaming, reliability, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: documented-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0160-use-documented-openai-responses-terminal-discriminators.md"
---

# documented-260716/ADR: Use Documented OpenAI Responses Terminal Discriminators

## Status

Accepted. Implementation has not started.

## Context

[official-260716/ADR](./official-260716-official-openai-sdk-stream-events.md) requires OpenAI-native stream handlers to match both the official SDK class and its documented wire discriminator. [failure-260716/ADR](./failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md) lists `response.failed`, `response.incomplete`, `error`, and `response.error` as typed failure events.

Validation against the pinned OpenAI Python SDK 2.45.0 found that its `ResponseStreamEvent` union contains:

- `ResponseFailedEvent` with `type="response.failed"`;
- `ResponseIncompleteEvent` with `type="response.incomplete"`;
- `ResponseErrorEvent` with `type="error"`.

The pinned union does not define a typed `response.error` discriminator. Treating an incidental loose SDK fallback class carrying that unknown discriminator as `ResponseErrorEvent` would violate [official-260716/ADR](./official-260716-official-openai-sdk-stream-events.md)'s class-and-wire-type guard.

## Decision

The OpenAI-native normalizer recognizes the three documented failure variants above by both official SDK class and exact wire `type` value. It does not add a special `response.error` handler for the pinned SDK.

An event with an unknown discriminator, including `response.error`, follows the unsupported-event path. It cannot establish successful completion. A stream that ends after such an event without a recognized `ResponseCompletedEvent` with `type="response.completed"` therefore still fails as premature exhaustion before durable model output is appended.

If a future pinned SDK or explicitly validated ChatGPT protocol contract introduces another typed terminal discriminator, Azents adds it through that versioned class-and-wire contract rather than promoting an incidental fallback class.

This ADR corrects only the typed terminal-event list in [failure-260716/ADR](./failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md). [failure-260716/ADR](./failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md)'s timeout, cancellation, safe exception mapping, and explicit-completion requirements remain unchanged.

## Consequences

- Normalization matches the actual official SDK 2.45.0 event union.
- Unknown-event forward compatibility does not weaken terminal success or failure classification.
- A future terminal variant requires an explicit SDK/protocol compatibility update and fixture.
- Tests must cover all three documented failures, an unknown `response.error` discriminator, and EOF without `response.completed`.

## Alternatives Considered

### Treat `response.error` as `ResponseErrorEvent` based on class alone

Rejected because the SDK may use a known class as a loose fallback for an unknown discriminator, and class-only promotion would contradict [official-260716/ADR](./official-260716-official-openai-sdk-stream-events.md).

### Treat any event whose discriminator contains `error` as terminal

Rejected because string-pattern classification is not an official protocol contract and could misclassify future non-terminal events.

## Migration provenance

- Historical source filename: `0160-use-documented-openai-responses-terminal-discriminators.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
