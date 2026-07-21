---
title: "Make Model Provider Failures Transparent"
created: 2026-07-18
tags: [architecture, backend, engine, llm, reliability, security, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: failures-260718
historical_reconstruction: true
migration_source: "docs/azents/adr/0165-make-model-provider-failures-transparent.md"
---

# failures-260718/ADR: Make Model Provider Failures Transparent

## Context

Azents currently obscures some model-provider failures at the adapter boundary. The OpenAI-native Responses path replaces typed provider terminal errors with generic text such as `Model call failed.` and replaces final SDK failures with `OpenAI Responses request failed.`. LiteLLM and OpenAI paths also map equivalent provider outcomes through different exception families.

This makes provider rejection, authorization failure, quota exhaustion, rate limiting, provider unavailability, and Azents programming failures appear alike. It also prevents the failed-run retry lifecycle, terminal history, frontend, and operational telemetry from preserving the safe reason that explains the failure.

The existing security boundary remains necessary: Azents must not expose raw provider bodies, serialized SDK exceptions, credentials, headers, request input, model output, stack traces, request or response identifiers, or raw streaming frames. However, provider-authored scalar error fields intended to explain a rejected request can be bounded, redacted, and carried safely.

Error transparency cannot be implemented only at final presentation. A provider failure may pass through adapter normalization, automatic compaction, model-turn retry, worker handover, terminal failed-run finalization, and frontend resync. Retry ownership and lifecycle must preserve one safe typed failure through all of those boundaries.

## Decision

### failures-260718/ADR-D1. Preserve safe provider-attributed failure details

When a provider or its transport rejects or fails a model request, Azents identifies the result as a model-provider failure and preserves a bounded, redacted provider-authored scalar message when one is safely available.

The default English presentation is:

- heading: `Model provider error`;
- body: the bounded provider-authored message; or
- fallback body: `The model provider could not process the request.`

The default presentation does not expose the concrete provider, integration, model, HTTP status, provider code, provider type, taxonomy category, diagnostic retryability, fingerprint, or correlation identifier.

### failures-260718/ADR-D2. Normalize provider failures into one closed Engine contract

Every supported model adapter converts provider-attributed failures into a typed `ModelProviderFailure` before the failure crosses the Engine or retry boundary.

The contract contains only validated fields required by retry, presentation, and observability:

- model operation;
- provider-neutral failure category;
- diagnostic retryability;
- bounded redacted provider message;
- nullable HTTP status, provider error code, provider error type, and retry hint;
- internal provider, integration, and model identity;
- a stable safe fingerprint.

The provider-neutral categories are `authentication`, `permission`, `quota_or_billing`, `rate_limit`, `invalid_request`, `model_unavailable`, `context_limit`, `content_policy`, `provider_unavailable`, `transport`, and `unknown`.

Provider-specific exceptions, response objects, arbitrary metadata dictionaries, and raw exception causes do not cross this boundary. Unexpected Azents programming failures remain internal failures. `asyncio.CancelledError`, User Stop, and Azents watchdog expiry retain their existing distinct contracts.

### failures-260718/ADR-D3. Use one logical retry owner for each model operation

The SDK or transport adapter may retry only a physical request failure before a stream is exposed. Those retries remain contained within the Azents watchdog deadlines and do not create separate logical failed-run attempts.

For a run-scoped model turn, `RunExecutor` owns one logical retry lifecycle around both automatic compaction and sampling. The Engine executes those operations but propagates their classified failures instead of owning an independent logical retry loop.

A failed automatic-compaction provider call therefore returns to the same model-turn retry boundary as a failed sampling call. The controller persists one retry state, applies the standard backoff, honors stop and worker handover, and finalizes only when the logical retry policy ends.

Standalone model operations reuse the same provider-failure contract and shared retry policy without creating unrelated failed-run state. Automatic title generation uses an operation-scoped best-effort retry lifecycle. Manual compaction runs inside its command Run and therefore uses the Run-owned lifecycle.

### failures-260718/ADR-D4. Give every provider-attributed failure the complete retry budget

Every `ModelProviderFailure` receives the initial attempt plus the configured complete model-turn retry budget regardless of category, status, code, or diagnostic retryability.

Authentication, permission, quota or billing, content policy, invalid request, transient, and unknown provider failures do not finalize early. Diagnostic retryability remains available for support, metrics, and future policy decisions, but it does not reduce the retry count in this contract.

The existing Azents backoff schedule remains authoritative. Provider retry-delay hints are retained only as typed operational metadata. Existing non-provider deterministic failures may continue to finalize early under their current policy.

### failures-260718/ADR-D5. Make automatic compaction part of the model-turn retry lifecycle

Automatic compaction is context preparation for the current model turn, not an independent failed-run lifecycle.

Compaction follows a plan, generate, and commit boundary:

1. capture the transcript cutoff and summary inputs without writing a lifecycle marker;
2. generate and enrich the summary outside a database transaction;
3. after success, atomically append the successful compaction marker and summary and advance the model-input head.

A provider failure, cancellation, User Stop, worker shutdown, or stale-plan conflict before commit writes no compaction lifecycle event. A subsequent logical attempt rebuilds its plan from current durable state.

A successfully committed compaction remains authoritative if later sampling fails. The next attempt rebuilds from that summary and does not repeat compaction unless the rebuilt context independently requires it.

The active Run exposes at most one live `preparing_context` operation. Backoff and repeated attempts keep the same operation identity. Success, exhaustion, User Stop, or terminal transition removes it. Failed compaction attempts do not create repeated durable transcript items.

### failures-260718/ADR-D6. Preserve provider attribution through retry and terminal presentation

The durable retry state stores only the safe typed provider fields required for worker handover and finalization. REST and WebSocket retry projections and terminal failed-run metadata expose a provider-neutral presentation discriminator, such as `model_provider` versus `runtime`, plus the existing bounded user-safe message and retry progress.

Public contracts do not expose provider identity, taxonomy, status, code, retry hint, or fingerprint. The discriminator exists only so clients can present a provider failure distinctly from an Azents runtime failure without parsing message text.

### failures-260718/ADR-D7. Keep User Stop terminal and non-replayable

User Stop preempts an active provider request, automatic compaction, retry wait, or retry attempt. The current Run becomes terminal `STOPPED`, active retry and live-operation state are cleared, and the existing interruption and tool-cancellation finalization remains authoritative.

A provider failure observed before Stop may remain in bounded structured telemetry, but Stop does not promote it to a durable `system_error` or failed Run. A stopped Run has no recovery projection, Retry action, replay source, retry deadline, or automatic worker resume.

A later user message follows the normal input path from durable conversation state. The existing manual failed-run Retry remains scoped only to the latest terminal failed-run error; it does not apply to stopped Runs.

This supersedes [failed-260627/ADR](./failed-260627-failed-error-retry.md) only where Stop during failed-run backoff finalizes the latest provider failure instead of preserving the user-selected stopped outcome.

### failures-260718/ADR-D8. Apply the shared policy to automatic title generation without failing the Run

Automatic Session title generation uses the same provider-failure normalization and complete retry budget in an operation-scoped loop.

Before another attempt and before committing a generated title, the service verifies that the original prompt boundary and `auto_initial` title are still current. A manual title update terminates the operation. Exhaustion keeps the deterministic initial title and does not fail or mutate the owning Agent Run.

### failures-260718/ADR-D9. Emit safe structured provider-attempt telemetry

Every provider-attributed failed attempt emits structured telemetry through the normal application logger. Runtime product code does not call a monitoring SDK directly.

An `unknown` provider failure emits an immediate error-level log even if a later retry succeeds. The base fingerprint is derived only from bounded redacted fields such as internal provider identity, operation, status, code or type, and normalized safe-message shape. It excludes Session or Run identity from grouping and never includes credentials, raw bodies, request input, model output, or arbitrary SDK serialization.

The shared logging integration combines the provider-failure fingerprint with release context for monitoring grouping. Repeated attempts with the same fingerprint and release update one incident rather than generating one independent incident per retry.

### failures-260718/ADR-D10. Ship one coordinated behavior cutover without stopped-Run schema

The typed failure contract, adapter mappings, retry behavior, compaction lifecycle, User Stop correction, title retry, public presentation, frontend behavior, and structured logging ship as one coordinated cutover.

No database migration is required. Existing `agent_runs.retry_state` remains the only durable active retry field. The implementation does not add `recovery_state`, `retry_source_run_id`, a stopped-Run retry endpoint, a stopped recovery projection, or a legacy behavior fallback.

## Relationship to Earlier Decisions

[failure-260716/ADR](./failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md) remains authoritative for cancellation, watchdog ownership, terminal completion requirements, transport cleanup, and the prohibition on raw SDK/provider payload propagation. This ADR narrows only its fixed-message treatment by permitting bounded redacted provider-authored scalar error fields inside the new typed contract.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-109) remains authoritative for explicit Responses terminal completion and model-turn-scoped durable retry state. This ADR extends that retry lifecycle to preserve typed provider failures consistently across supported adapters and automatic context preparation.

[failed-260627/ADR](./failed-260627-failed-error-retry.md) remains authoritative for failed-run retry storage, backoff, handover, and terminal failed-run history except for the User Stop correction in failures-260718/ADR-D7 and the complete-budget provider policy in failures-260718/ADR-D4.

## Consequences

### Positive

- Users can distinguish model-provider failures from Azents runtime failures and see the safe actionable provider reason.
- OpenAI-native and LiteLLM-backed paths share one Engine failure contract.
- Provider diagnostics survive retry, worker handover, terminal finalization, REST/WebSocket resync, and frontend presentation without exposing raw payloads.
- Automatic compaction no longer creates a second logical retry owner or repeated durable failed-attempt markers.
- User Stop remains a terminal user-selected outcome and cannot replay completed side effects.
- Unknown provider mappings become immediately observable and consistently grouped.

### Trade-offs

- All provider-attributed categories consume the configured retry budget, including failures that appear deterministic.
- Provider-authored message handling requires strict sanitizer, redaction, and compatibility fixtures.
- Compaction must separate planning and external generation from its atomic durable commit.
- Backend, worker, API clients, frontend, deterministic fixtures, specs, and logging integration must change together.

## Migration provenance

- Historical source filename: `0165-make-model-provider-failures-transparent.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
