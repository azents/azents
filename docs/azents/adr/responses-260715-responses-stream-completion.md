---
title: "Require Explicit Responses Stream Completion"
created: 2026-07-15
tags: [architecture, backend, engine, llm, retry, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: responses-260715
historical_reconstruction: true
migration_source: "docs/azents/adr/0145-require-explicit-responses-stream-completion.md"
---
# responses-260715/ADR: Require Explicit Responses Stream Completion

## Status

Accepted.

## Context

The LiteLLM Responses output normalizer currently accumulates completed output items and treats them as a completed model step when the native stream reaches EOF, even if it never observes `response.completed`. A stream can therefore end with a reasoning item after `response.incomplete`, `response.failed`, or an unclassified early EOF. Because reasoning is a durable event and there is no foreground client tool call, `AgentRunExecution` can then mark the Run completed without a user-visible assistant response.

The worker already has a failed-run retry and finalization boundary. `ModelCallError` raised by the model execution path becomes a failed attempt, remains non-durable while retrying, and is promoted to terminal failed-run output only when retry policy finalizes it. The missing boundary is strict validation of the adapter-native Responses terminal event before normalized output is admitted as a successful model step.

## Decision

### responses-260715/ADR-D1. Require `response.completed` for successful Responses stream normalization

A normally exhausted LiteLLM Responses stream is successful only when its output normalizer observed an explicit `ResponseCompletedEvent` representing native `response.completed`.

Completed output items are intermediate normalization inputs. They must not independently prove successful model-call completion.

### responses-260715/ADR-D2. Convert unsuccessful or missing terminal states to `ModelCallError`

The LiteLLM Responses output path will convert these cases to `ModelCallError`:

- native `response.incomplete`;
- native `response.failed`;
- native `error`;
- EOF before any recognized terminal event.

Provider-reported messages and codes may be used to construct a bounded user-safe error message. Raw provider response bodies, credentials, and internal transport details must not be copied into durable user-visible output.

`AgentRunExecution` will not append normalized model events, a turn marker, or a completed run marker for the failed attempt. The existing worker retry/failure boundary remains the owner of retry state and terminal failed-run finalization.

### responses-260715/ADR-D3. Keep successful-output semantics unchanged in this phase

This phase validates only the adapter-native terminal state. It does not change the existing definition of durable model output and does not reject a reasoning-only response when the provider explicitly reports `response.completed`.

User-visible terminal-output validation, response-incomplete reason-specific retryability, and provider-specific recovery policies are separate follow-up concerns.

### responses-260715/ADR-D4. Preserve user-stop behavior

User-requested cancellation continues through the existing interruption path. Partial assistant text may be durably preserved only by that path. Provider-reported incomplete, failed, error, and unclassified EOF outcomes are failed attempts rather than user interruptions and do not durably preserve their partial output items.

## Consequences

### Positive

- A reasoning item or tool item received before an unsuccessful terminal event can no longer cause a false completed Run.
- Missing `response.completed` becomes observable through the existing retry/failure lifecycle instead of being silently accepted.
- No database, public API, or transcript schema change is required.
- Retry and final failed-run presentation remain consistent with the existing failed-run architecture.

### Negative / trade-offs

- Providers or LiteLLM transports that end a nominally successful stream without emitting `response.completed` will now retry and eventually fail instead of being accepted through the permissive output-item fallback.
- Provider `response.incomplete` reasons are initially handled by the common retry policy; deterministic reasons such as output limits may consume the retry budget before finalization.
- Explicitly completed reasoning-only responses remain possible until a separate terminal-output policy is designed.

## Alternatives

### Continue accepting completed output items at EOF

Rejected. Output-item completion does not establish response completion and reproduces the false-success path.

### Treat incomplete or failed output as a completed Run with a system message

Rejected. This would bypass the existing failed-run retry boundary and conflate failed model attempts with successful Run completion.

### Add user-visible terminal-output validation in the same change

Deferred. It would broaden the accepted scope beyond native terminal-state correctness and requires a separate decision for provider-hosted outputs and explicitly completed reasoning-only responses.

## Related documents

- [execution-260527/ADR: Agent Execution Transcript Normalization](./execution-260527-execution-transcript-normalization.md)
- [event-260613/ADR: Adopt Event / Native Event Terminology](./event-260613-event-event-terminology.md)
- [failed-260627/ADR: Failed-run Error Retry and Finalization](./failed-260627-failed-error-retry.md)
- [Agent Execution Loop](../spec/flow/agent-execution-loop.md)

## Migration provenance

- Historical source filename: `0145-require-explicit-responses-stream-completion.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
