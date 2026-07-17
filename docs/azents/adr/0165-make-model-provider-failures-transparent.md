---
title: "ADR-0165: Make Model Provider Failures Transparent"
created: 2026-07-17
tags: [architecture, backend, engine, llm, reliability, security, ux]
---

# ADR-0165: Make Model Provider Failures Transparent

## Context

Azents currently over-sanitizes some model-provider failures. The OpenAI-native Responses path replaces a typed provider `error` event with `Model call failed.` and replaces many final SDK exceptions with `OpenAI Responses request failed.`. The latter retains only limited metadata in process memory, and the worker currently neither projects that metadata to the user nor records it in structured logs.

This makes provider outages, customer quota exhaustion, credential failures, permission failures, and Azents programming failures look alike. It also makes an external provider problem appear to be an Azents internal failure.

ADR-0157 intentionally prohibited copying raw SDK exception strings and provider response bodies into user-visible or durable output. That security boundary is valid for arbitrary bodies, credentials, headers, stack traces, raw frames, and SDK object serialization, but it is too broad for provider-authored error fields intended to explain a failed model request. ADR-0145 already permits bounded provider messages and codes when constructing user-safe model errors, and the existing LiteLLM Responses normalizer already follows that narrower contract.

## Decision

### ADR-0165-D1. Treat provider-attributed failure details as user-visible by default

When an LLM provider rejects or fails a model request, Azents presents the provider-attributed reason to the user instead of replacing it with an unqualified generic message.

The user-visible error identifies the failure as a model-provider failure and preserves available structured details intended for error reporting, including a bounded provider message, error code or type, and HTTP status when present.

This applies consistently to sampling, compaction, title generation, and other model operations. Operation-specific UI may choose different presentation, but it must not discard the provider attribution or actionable reason.

### ADR-0165-D2. Redact sensitive transport data without hiding the provider reason

Azents does not expose credentials, authorization headers, cookies, request input, response output, stack traces, arbitrary raw response bodies, raw SSE frames, or unbounded HTML/error payloads.

A provider-authored scalar error message is not treated as an arbitrary raw body merely because it originated inside an SDK exception or terminal event. Azents bounds and redacts that message, then preserves it through the domain error, retry state, terminal `system_error`, operator telemetry, and UI projection.

If a safe provider message is unavailable after redaction, Azents falls back to a classified provider message such as authentication failed, permission denied, quota exhausted, rate limited, or provider unavailable. A bare `Model call failed.` message is not sufficient when provider attribution or classification is available.

### ADR-0165-D3. Keep internal programming failures distinct

Unexpected Azents programming failures remain internal errors and must not be mislabeled as provider failures. The adapter boundary records whether a failure is provider-attributed, transport-attributed, user-cancelled, or internal before the worker applies retry and finalization policy.

### ADR-0165-D4. Use layered retry ownership with one logical owner per operation

The SDK or transport adapter may retry only a physical request failure that occurs before a stream is exposed. Those retries remain bounded by the Azents watchdog and do not create separate failed-run attempts.

For a run-scoped model turn, the failed-run controller owns the logical attempt lifecycle around both automatic compaction and sampling. The engine executes those operations but propagates their classified failures to the controller instead of starting an independent logical retry loop. An automatic-compaction failure therefore retries from the current model-turn boundary; a sampling failure does the same. The failed-run controller records one durable retry cycle, applies backoff, honors stop and worker handover, and finalizes only after the logical retry policy ends.

A successfully committed automatic compaction remains authoritative if a later sampling call fails. The following model-turn attempt rebuilds from that committed summary and does not repeat compaction unless the rebuilt context independently requires it. A failed compaction attempt does not append a separate durable failure marker for every retry; retry progress is projected through live run state and only terminal failure becomes durable history.

Standalone model operations that do not belong to an active model turn, including manual compaction and title generation, reuse the shared classification and retry-policy components but use an operation-scoped lifecycle rather than creating or mutating failed-run state for an unrelated `AgentRun`.

### ADR-0165-D5. Use generic provider attribution in the default user presentation

The default user-facing presentation identifies the source generically as a model-provider failure without exposing the concrete provider or integration name. Its default English heading is `Model provider error` followed by the bounded, redacted provider-authored message.

Semantic classification, classification failure, HTTP status, provider code or type, retryability, correlation identifiers, and concrete provider or integration identity remain structured operational metadata rather than default UI content. Azents adds a concise user action only when the error is classified and the action is known. It does not tell users that an internal classifier failed and does not invent guidance for an unrecognized error.

The concrete provider or integration name may appear only when it is necessary to perform a specific user action, such as reconnecting or changing the affected integration. If no safe provider-authored message is available, the default English fallback is `The model provider could not process the request.`

All default UI copy, durable error text, API error messages, and operator logs remain English. Localization may translate presentation text without changing the underlying structured failure contract.

### ADR-0165-D6. Normalize provider failures into one typed engine contract

Every model adapter converts provider and SDK failures into the same typed `ModelProviderFailure` contract before the failure crosses into the Engine or retry boundary. Provider-specific exception classes, SDK objects, arbitrary response bodies, and open-ended metadata dictionaries do not cross that boundary.

The contract carries stable typed fields needed by model operations, failed-run retry, terminal presentation, and observability:

- model operation;
- semantic failure category;
- retryability;
- bounded redacted provider-authored message;
- nullable HTTP status, provider error code, and provider error type;
- nullable typed retry hint;
- internal provider and integration identity.

User presentation is derived from this contract according to ADR-0165-D5. Concrete provider identity and diagnostic fields remain internal unless a specific user action requires them. The provider-authored message remains available for the default user-facing error even when semantic classification is unavailable.

The contract is closed and typed. Adding a new field or variant requires an explicit Engine contract change and exhaustive adapter tests rather than inserting provider-specific keys into an arbitrary metadata map.

### ADR-0165-D7. Use a compact provider-neutral failure taxonomy

`ModelProviderFailure.category` is a closed provider-neutral enum used by retry policy, action guidance, metrics, and alerting. The initial categories are:

- `authentication`;
- `permission`;
- `quota_or_billing`;
- `rate_limit`;
- `invalid_request`;
- `model_unavailable`;
- `context_limit`;
- `content_policy`;
- `provider_unavailable`;
- `transport`;
- `unknown`.

Adapters map provider-specific status, code, type, and typed SDK outcomes into this taxonomy while preserving the original bounded code and type as separate diagnostic fields. Provider-specific codes never become public category values. An unrecognized provider outcome uses `unknown` rather than being reclassified as an internal Azents failure.

The category is not part of the default user presentation. It may select a known concise action hint, but the default error body continues to use the bounded provider-authored message established by ADR-0165-D5.

### ADR-0165-D8. Give every provider failure the full retry budget

Every provider-attributed failure uses the normal model-turn retry policy and its complete retry budget regardless of semantic category, status, provider code, or retryability classification. Authentication, permission, quota or billing, content policy, invalid request, transient, and unknown failures do not finalize early.

Under the current failed-run policy, this means the initial attempt plus up to ten automatic retries with the standard durable backoff, stop, and worker-handover behavior. Category and retryability remain structured diagnostic and observability fields, but they do not reduce the retry count or short-circuit the failed-run controller. Provider retry-delay hints are preserved as typed operational metadata but do not alter the standard backoff schedule.

This policy prefers consistent recovery behavior over avoiding requests for failures that appear deterministic. Provider code, type, status, category, retryability, and bounded message remain available in structured attempt telemetry, while the default user presentation remains the concise English provider-error message defined by ADR-0165-D5.

### ADR-0165-D9. Represent automatic compaction retry as one live operation

Automatic compaction does not append a durable failure marker for each failed attempt. The current model turn exposes at most one live compaction operation whose default English status is `Preparing conversation context…`. Backoff and repeated attempts update that same live identity rather than creating additional transcript or UI items.

Successful compaction commits the normal `compaction_summary`, removes the live operation, and leaves no durable retry-failure history. If the complete provider retry budget is exhausted, Azents removes the live operation and appends one terminal failed-run error using the `Model provider error` presentation and bounded provider message established by ADR-0165-D5.

Attempt count, provider classification, status, code, retryability, and failure history remain in structured retry state and operator telemetry rather than the default compaction UI. The UI does not use the technical term `compaction` in its default user-facing status.

### ADR-0165-D10. Keep a stopped execution recoverable in live state

User Stop terminates automatic retry and the active provider request without promoting the latest provider failure to a durable `system_error` or a failed Run. The active Run becomes terminal `STOPPED`, while the live projection retains that last stopped Run and its bounded last-error presentation as a recoverable stopped state.

The stopped state exposes Retry. An explicit Retry starts a new Run linked to the stopped Run, copies the original ordered input associations and requested inference-profile intent according to the existing manual retry contract, and starts with a fresh full retry budget. Azents does not reopen or mutate the terminal stopped Run.

If the user sends a new message instead of selecting Retry, that message is appended normally and starts the next Run. The new pending or running Run replaces the recoverable stopped projection, so the previous error disappears from live UI without adding it to durable transcript history. The stopped Run remains durable execution history but is no longer the active live item.

Active retry state and recoverable stopped state are distinct. Automatic worker recovery continues only active retry state; it never resumes a stopped Run automatically. The retained stopped projection contains the bounded information required for display and explicit Retry without preserving an auto-resumable backoff deadline.

The same user semantics apply when Stop occurs during sampling, automatic compaction, a retry wait, or a retry attempt. Manual compaction uses the same stopped-operation presentation and fresh-budget Retry behavior within its operation-scoped lifecycle.

This decision supersedes ADR-0084 only where it requires Stop during retry to promote the latest failure into terminal failed-run output.

### ADR-0165-D11. Alert immediately and group by unknown failure fingerprint

Every provider attempt emits structured failure telemetry through the normal application logger. A provider failure classified as `unknown` emits an error-level structured log immediately without waiting for retry exhaustion, an aggregate-rate threshold, or terminal user impact. A later successful retry does not suppress the alert because the classifier gap still requires investigation. Runtime product code does not call a monitoring SDK directly.

The safe base fingerprint is derived only from bounded redacted fields such as provider, operation, HTTP status, provider code or type, and normalized provider-message shape. It is attached as structured log metadata and never includes credentials, raw provider bodies, request input, response output, or arbitrary SDK object serialization. The shared logging integration combines that base fingerprint with the deployed release when assigning the monitoring event fingerprint.

Repeated attempts and occurrences with the same base fingerprint and release update one active monitoring incident rather than producing one notification per retry. Different fingerprints or releases remain distinct. The incident records occurrence count, affected sessions and Runs as bounded references, first and latest occurrence time, recovery rate, and whether retry eventually succeeded or exhausted. A frequency or impact increase escalates the existing incident.

Unknown-failure monitoring is a classifier response queue, not only an availability alert. Operators must be able to add a classification fixture and mapping quickly, while the full retry-budget policy from ADR-0165-D8 remains unchanged for affected users.

Known authentication, permission, quota, and other customer-scoped failures remain structured metrics by default. Provider-wide failure-rate or retry-exhaustion spikes and Azents internal failures have separate alerts based on their operational impact.

### ADR-0165-D12. Cut over the complete behavior atomically

Azents ships the typed provider-failure contract, all supported adapter mappings, full-budget retry behavior, automatic-compaction live lifecycle, recoverable stopped state, frontend presentation, structured telemetry, and unknown-failure alerting as one coordinated product cutover.

The release does not use a shadow behavior phase, long-lived dual read or write contracts, provider-path fallback, or a feature flag that preserves the previous generic-error semantics. Backend, worker, frontend, API projection, and alert configuration must be compatible within the same release artifact set before production rollout begins.

Pre-release verification must therefore include provider fixtures for every supported adapter, redaction and unknown-classification cases, full retry exhaustion, worker handover, automatic and manual compaction, Stop/Retry/new-message transitions, REST/live resync, frontend history and live rendering, and alert deduplication. Unknown-failure alerting is active from the first production request after cutover.

Database migrations may use additive and rollback-safe mechanics where required for deployment safety, but product behavior has one post-cutover contract. Azents does not retain a legacy runtime fallback after the coordinated release is active.

## Relationship to Earlier Decisions

This ADR narrows and supersedes ADR-0157's blanket prohibition on carrying provider exception text across the adapter boundary. ADR-0157 remains authoritative for cancellation, watchdog ownership, terminal completion semantics, and prohibition of arbitrary raw provider payloads.

ADR-0145's bounded user-safe provider-message rule becomes the common behavior for every supported model adapter rather than only a permitted implementation detail.

## Consequences

### Positive

- Users can distinguish provider, quota, credential, permission, and Azents failures.
- Provider incidents no longer appear to be unexplained Azents internal errors.
- Support and operators retain actionable safe metadata without storing raw provider payloads.
- OpenAI-native and LiteLLM-backed model paths converge on one transparency policy.

### Trade-offs

- Provider messages require bounded redaction and compatibility tests because providers control their wording.
- User-visible strings become less stable than fixed generic messages, so clients must treat structured classification as the stable contract.
- Existing tests that require provider messages to be discarded must be replaced with redaction and transparency fixtures.
