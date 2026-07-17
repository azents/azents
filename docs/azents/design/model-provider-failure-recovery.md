---
title: "Model Provider Failure Recovery"
created: 2026-07-17
updated: 2026-07-17
tags: [architecture, backend, engine, frontend, api, llm, reliability, observability, security, ux]
---

# Model Provider Failure Recovery

## Summary

Azents replaces adapter-specific model failure handling with one typed provider-failure contract. Provider-authored explanations are bounded and redacted, every provider-attributed failure receives the full retry budget, automatic compaction is represented as one live operation, and a stopped Run remains explicitly recoverable without becoming auto-resumable.

This design implements ADR-0165 as one coordinated backend, API, frontend, and operational cutover.

## Problem

The previous paths handled equivalent provider outcomes differently:

- OpenAI-native failures frequently lost their provider-authored explanation.
- LiteLLM and OpenAI failures crossed the Engine boundary through different exception types.
- retryability classification could prematurely end deterministic provider failures.
- automatic compaction emitted durable lifecycle markers for repeated attempts.
- Stop during retry promoted the latest failure into durable failed output.
- unknown provider outcomes lacked a stable immediate alerting fingerprint.

The result was inconsistent recovery behavior and provider failures that appeared to be unexplained Azents failures.

## Goals

- Normalize provider failures into one closed `ModelProviderFailure` contract.
- Preserve only bounded, redacted provider-authored scalar messages.
- Give every provider-attributed failure the configured full retry budget.
- Make the failed-run controller own sampling and automatic-compaction retries.
- Project automatic compaction as one live `preparing_context` operation.
- Keep `STOPPED` terminal while exposing explicit fresh-budget Retry.
- Dismiss stopped recovery naturally when newer input creates a Run.
- Emit safe structured attempt telemetry and immediate fingerprint-grouped unknown alerts.
- Keep title generation standalone and best-effort.

## Non-goals

- Retrying Azents programming errors as provider failures.
- Exposing credentials, headers, request input, output, raw bodies, frames, or SDK serialization.
- Adding provider-specific categories to the public API.
- Letting provider retry hints change the standard backoff policy.
- Automatically resuming a stopped Run.
- Adding a new in-process metrics or incident service.
- Preserving the legacy generic provider-error behavior.

## Accepted Design

### 1. Typed provider-failure boundary

All supported adapters raise `ModelProviderFailure` before a provider-attributed failure crosses the Engine boundary. The contract carries:

- operation;
- provider-neutral category and diagnostic retryability;
- bounded provider message;
- nullable status, provider code/type, and retry hint;
- internal provider, integration, and model identity;
- stable safe fingerprint.

Adapter SDK objects and arbitrary metadata dictionaries never cross this boundary. Unexpected Azents failures remain internal exceptions.

The category set is closed: authentication, permission, quota or billing, rate limit, invalid request, model unavailable, context limit, content policy, provider unavailable, transport, and unknown.

### 2. Safe provider-message handling

The shared sanitizer accepts only scalar strings, normalizes controls and whitespace, applies a fixed length cap, and redacts credential-shaped values. Oversized body-shaped JSON or HTML is discarded. Provider code/type fields use stricter identifier validation.

Only the sanitized message may enter retry state, terminal errors, UI projections, logs, or monitoring. When no safe message remains, the user-facing fallback is `The model provider could not process the request.`

The default presentation uses `Model provider error` without exposing the concrete provider or integration name.

### 3. Exhaustive adapter mapping

The OpenAI-native path maps typed terminal events, final SDK exceptions, HTTP failures, and WebSocket failures into the common contract. The LiteLLM path maps final LiteLLM/OpenAI exceptions and typed terminal events through the same contract.

Compaction and title helpers preserve the typed failure rather than replacing it with a generic operation error. Failures without reliable provider attribution remain internal.

### 4. Retry ownership and budget

For a model turn, `RunExecutor` owns the logical retry cycle around both automatic compaction and sampling. Adapter-internal retries may cover only physical request setup before a stream is exposed.

Every `ModelProviderFailure` consumes the same initial attempt plus configured retries regardless of category or diagnostic retryability. Existing non-provider deterministic errors may still finalize early. Provider retry hints remain telemetry only.

A successful compaction commit remains authoritative if later sampling fails. A failed compaction attempt appends no durable failure marker; the next logical attempt rebuilds from current committed history.

Title generation uses the same classification and retry policy in an operation-scoped loop. Exhaustion abandons title generation and never fails the owning Agent Run.

### 5. One live context-preparation operation

An active Run may expose one optional live operation:

```json
{
  "kind": "preparing_context",
  "operation_id": "<run-id>",
  "status": "running"
}
```

Retries and backoff retain the same identity. Success removes the live operation and commits the normal summary. Exhaustion removes it and lets failed-run finalization produce one terminal error. Historical compaction markers remain readable, but the new automatic path does not create lifecycle markers.

### 6. Recoverable stopped Run

`agent_runs.recovery_state` retains a user-safe projection on a terminal `STOPPED` Run. It is distinct from active retry state and has no retry deadline.

Stop during sampling, context preparation, retry wait, or retry attempt:

1. cancels the active operation;
2. transitions the source Run to `STOPPED`;
3. clears active retry state;
4. retains the last bounded provider failure when available, or a generic stopped state;
5. appends no provider `system_error`;
6. leaves the stopped Run visible as recoverable live state.

Worker recovery never resumes a stopped Run automatically.

### 7. Explicit Retry and new-message replacement

`POST /chat/v1/sessions/{session_id}/retry-stopped-run` accepts the agent ID, stopped Run ID, and client request ID.

The service verifies that the source is the latest recoverable stopped Run and the session is idle. It creates a new pending Run linked through `retry_source_run_id`, copies ordered input associations and requested inference intent, and starts with no retry state. The source Run remains immutable.

If the user sends a new message instead, normal input processing creates the newer Run. Live projection then omits the older stopped recovery without rewriting durable history.

A stopped manual-compaction Run may have no copied input events; its Retry creates a linked pending Run and requeues the compaction command.

### 8. API and frontend projection

Live Run state gains:

- optional `operation` for context preparation;
- optional `recovery` for a stopped Run;
- existing retry state for active attempts.

The frontend shows:

- one provider-error card for active retry;
- one `Preparing conversation context…` item;
- Retry for recoverable stopped state;
- one terminal provider-error card after exhaustion.

Technical attempt history, provider identity, codes, and taxonomy remain outside the default card. The OpenAPI document and generated Python and TypeScript clients carry the new endpoint and projection fields.

### 9. Structured telemetry and unknown alert grouping

Every provider attempt emits a structured warning with Run/session context, operation, provider/model/integration, category, retryability, status, provider code/type, fingerprint, attempt number, and retry outcome.

Unknown attempts also emit `logger.error("Unknown model provider failure", extra={...})` immediately. The base fingerprint is derived only from bounded provider, operation, status, code/type, and normalized safe message shape. The shared logging integration maps `provider_failure_fingerprint` plus the deployed release to the Sentry event fingerprint, so repeated attempts update one incident while different fingerprints or releases remain distinct. Runtime product code does not call the Sentry SDK directly.

Logs never include raw provider payloads, credentials, request input, or model output.

## Data and API Changes

### Database

- nullable `agent_runs.recovery_state` JSONB;
- nullable self-reference `agent_runs.retry_source_run_id`;
- explicit index for retry source lookup.

The migration is additive and updates the schema revision pointer.

### Domain

- `ModelProviderFailure` and its category/retryability enums;
- provider diagnostics in durable retry state;
- typed stopped recovery state;
- linked fresh-budget retry Run.

### Public API

- active or recoverable stopped Run projection;
- optional live operation and recovery fields;
- stopped-Run retry request and accepted write type.

## Error Handling and Security

- Unknown provider semantics remain provider failures, not internal errors.
- Sanitization failure removes the unsafe message but does not hide provider attribution.
- Cancellation remains separate from provider failure mapping.
- A stale or non-latest stopped retry is rejected through the existing conflict contract.
- Session authorization and idle-write validation apply to Retry.
- Broker wake failure follows the existing accepted-write recovery path.
- Logging/monitoring delivery cannot influence retry state or user recovery.

## Migration and Rollout

The feature ships as one coordinated cutover:

1. apply the additive migration;
2. deploy backend, worker, API, generated clients, and frontend together;
3. verify structured fingerprint grouping through the existing logging integration;
4. observe provider retry and stopped-recovery transitions.

A code rollback ignores the additive fields. No legacy behavior fallback or dual-write path is retained.

## Test Strategy

### Deterministic E2E matrix

1. Safe provider messages appear under `Model provider error`; provider identity stays hidden.
2. Credential/body-shaped messages are redacted or replaced everywhere.
3. Provider categories all receive the configured full budget unless stopped.
4. Automatic compaction retries retain one live operation and no failed markers.
5. Sampling retry after successful compaction reuses the committed summary.
6. Exhaustion creates one failed Run and one terminal error.
7. Stop during sampling, preparation, wait, and retry produces recoverable `STOPPED` without a durable provider error.
8. Retry creates a linked fresh-budget Run and replaces the stopped card.
9. New input replaces stopped recovery without deleting durable Run history.
10. REST reconnect restores active or stopped state; handover resumes only active retry.
11. Title timeout/failure does not fail a completed Agent Run.
12. Unknown failures emit immediate structured errors whose base fingerprint and release define Sentry grouping.

### Fixtures

Use deterministic model fixtures for typed terminal failures, malicious messages, fail-N-then-succeed behavior, compaction failures, blocking Stop timing, and unknown fingerprints. Live-provider tests remain optional diagnostics; deterministic coverage must not depend on credentials.

### Unit and integration coverage

- sanitizer and taxonomy classification;
- OpenAI HTTP/WebSocket/terminal mapping;
- LiteLLM exception and terminal mapping;
- full-budget finalization rules;
- retry serialization and worker handover;
- compaction event absence and operation projection;
- stopped persistence, idempotency, stale conflict, copied inputs, command retry, and source linkage;
- API/live contracts and generated clients;
- frontend card states, actions, locales, and stories;
- structured logging field safety and Sentry fingerprint mapping.

### Evidence and CI

Validate durable history and Run rows, REST/WebSocket projections, frontend states, captured `LogRecord` fields, Python quality/tests, TypeScript format/lint/typecheck/build, documentation indexes, generated clients, and focused E2E scenarios.

The change fails validation if it leaks provider payloads, short-circuits a provider retry category, creates repeated durable compaction failures, resumes a stopped Run automatically, reopens the source Run on Retry, or delays unknown reporting until exhaustion.

## Alternatives Considered

- **Adapter-specific errors** — rejected because retry and presentation would remain provider-aware.
- **Retry only transient categories** — rejected in favor of uniform recovery behavior.
- **Durable marker per compaction attempt** — rejected because retry state already owns attempt durability.
- **Reopen the stopped Run** — rejected to preserve terminal Run immutability.
- **Promote Stop to failed history** — rejected because Stop is a user-controlled interruption.
- **New incident service** — rejected because structured logging already provides delivery and grouping.

## Validation Result

The design matches current failed-run persistence, command Run, event compaction, live projection, and generated-client boundaries. Both adapter families have a typed mapping point. The additive Run fields are necessary because stopped recovery is neither active retry nor subagent parentage. ADR-0165 records the persistent contract and lifecycle decisions; current behavior is reflected in the linked living specs.
