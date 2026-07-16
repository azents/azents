---
title: "ADR-0160: Use Documented OpenAI Responses Terminal Discriminators"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, streaming, reliability]
---

# ADR-0160: Use Documented OpenAI Responses Terminal Discriminators

## Status

Accepted. Implementation has not started.

## Context

ADR-0153 requires OpenAI-native stream handlers to match both the official SDK class and its documented wire discriminator. ADR-0157 lists `response.failed`, `response.incomplete`, `error`, and `response.error` as typed failure events.

Validation against the pinned OpenAI Python SDK 2.45.0 found that its `ResponseStreamEvent` union contains:

- `ResponseFailedEvent` with `type="response.failed"`;
- `ResponseIncompleteEvent` with `type="response.incomplete"`;
- `ResponseErrorEvent` with `type="error"`.

The pinned union does not define a typed `response.error` discriminator. Treating an incidental loose SDK fallback class carrying that unknown discriminator as `ResponseErrorEvent` would violate ADR-0153's class-and-wire-type guard.

## Decision

The OpenAI-native normalizer recognizes the three documented failure variants above by both official SDK class and exact wire `type` value. It does not add a special `response.error` handler for the pinned SDK.

An event with an unknown discriminator, including `response.error`, follows the unsupported-event path. It cannot establish successful completion. A stream that ends after such an event without a recognized `ResponseCompletedEvent` with `type="response.completed"` therefore still fails as premature exhaustion before durable model output is appended.

If a future pinned SDK or explicitly validated ChatGPT protocol contract introduces another typed terminal discriminator, Azents adds it through that versioned class-and-wire contract rather than promoting an incidental fallback class.

This ADR corrects only the typed terminal-event list in ADR-0157. ADR-0157's timeout, cancellation, safe exception mapping, and explicit-completion requirements remain unchanged.

## Consequences

- Normalization matches the actual official SDK 2.45.0 event union.
- Unknown-event forward compatibility does not weaken terminal success or failure classification.
- A future terminal variant requires an explicit SDK/protocol compatibility update and fixture.
- Tests must cover all three documented failures, an unknown `response.error` discriminator, and EOF without `response.completed`.

## Alternatives Considered

### Treat `response.error` as `ResponseErrorEvent` based on class alone

Rejected because the SDK may use a known class as a loose fallback for an unknown discriminator, and class-only promotion would contradict ADR-0153.

### Treat any event whose discriminator contains `error` as terminal

Rejected because string-pattern classification is not an official protocol contract and could misclassify future non-terminal events.
