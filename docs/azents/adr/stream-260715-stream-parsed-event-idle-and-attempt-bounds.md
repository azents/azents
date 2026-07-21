---
title: "Bound Model Streams by Parsed-Event Idle and Absolute Attempt Time"
created: 2026-07-15
tags: [architecture, backend, engine, streaming, reliability, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: stream-260715
historical_reconstruction: true
migration_source: "docs/azents/adr/0146-model-stream-parsed-event-idle-and-attempt-bounds.md"
---

# stream-260715/ADR: Bound Model Streams by Parsed-Event Idle and Absolute Attempt Time

## Status

Accepted. Implementation has not started; implementation validation requirements are listed below.

## Context

Azents currently has no Azents-owned watchdog that guarantees a model provider attempt will terminate when its stream stalls. Provider and HTTP-library defaults are insufficient as the product-level reliability contract because their timeout boundaries and retry behavior can vary by provider and adapter.

The watchdog must not infer whether an event represents meaningful or semantic progress. Provider event vocabularies differ, hidden reasoning may be legitimate work, and LiteLLM may transform or synthesize events. Azents can reliably observe only whether the adapter yielded another parsed provider event.

The watchdog must preserve the existing stream lifecycle boundaries:

- canonical provider output becomes durable only after completed provider output;
- incomplete tool calls are never admitted or executed;
- explicit User Stop may preserve valid partial assistant text;
- live partial output is non-durable and must hand off without duplication or loss;
- reconnect and REST resynchronization reconstruct current live state.

## Decision

### Use parsed-provider-event inactivity as the common stream idle signal

The parsed-event idle deadline starts when the provider request begins, before the adapter calls LiteLLM `aresponses()`. The initial 300,000 millisecond period therefore bounds both acquisition of the streaming response handle and receipt of the first parsed provider event. While consuming the stream, Azents bounds each subsequent wait for the next parsed provider event yielded by the adapter. Every yielded event resets the stream idle deadline, regardless of its type or payload.

Azents does not classify semantic progress. Raw network bytes, incomplete chunks, and transport heartbeats that do not produce a parsed provider event do not reset this deadline.

The parsed-event idle policy applies by default to every provider with a 300,000 millisecond deadline. This duration matches the current OpenAI Codex stream-idle default, while the ownership boundary intentionally differs: Codex applies its SSE deadline after acquiring the HTTP response and around each parsed SSE event wait, whereas Azents starts the same duration before response-handle acquisition. Provider or model overrides may change the duration when operational evidence requires it; enablement does not depend on a separately declared event-cadence capability.

### Bound connection establishment separately

Azents applies a 15,000 millisecond connection-establishment timeout. This is an Azents-owned general transport policy, independent of model reasoning or stream activity. Codex uses the same numeric duration specifically for Responses WebSocket connection and prewarm, not as a generic HTTP or TCP connection default; that narrower Codex policy is comparison evidence rather than the source of Azents' broader boundary. The connection timeout does not replace the parsed-event idle deadline.

### Keep one application-owned stream deadline

Azents sets no separate product deadline for connection-pool acquisition, request-body write, or raw transport reads. The parsed-event idle deadline begins before the provider request and therefore bounds those waits together with response-handle and parsed-event waits. Operating-system or transport failures may still terminate the request earlier and propagate as transport errors.

This avoids competing lower-level clocks that could preempt Azents timeout classification and cleanup. The 15-second connection-establishment timeout is the only shorter transport-specific deadline.

### Bound continuously active streams with an absolute attempt deadline

Parsed events can continue indefinitely without completing a provider response. Each provider attempt therefore has an absolute elapsed-time deadline of 1,800,000 milliseconds. The deadline is not refreshed by events.

The stream idle deadline and absolute attempt deadline are independent. The first deadline reached terminates the attempt. The initial 30-minute value is based on the 14-day Azents worker-log sample recorded in the run-stall reliability discussion: 4,494 successful normal model calls had a maximum total duration of 1,155.462 seconds. The limit leaves approximately 10 minutes and 45 seconds of headroom over that observed maximum. The sample measures total call duration rather than parsed-event gaps, so it supports only the absolute cap. Ultra-long-running model profiles remain outside the initial scope and require an explicit override decision.

### Apply the watchdog to every streaming Responses model call

The common watchdog applies to all Azents model calls that use a streaming Responses API, including primary agent sampling, context-compaction summary generation, and automatic Session title generation. This does not require separate lifecycle machinery: primary sampling already consumes an async iterator, while compaction and title generation share `call_responses_model()` and `extract_response_text()`, so they can reuse one generic watched-async-iterable boundary.

Each caller preserves its existing failure semantics:

- primary sampling converts timeout into failed-run retry state;
- context compaction converts timeout into `CompactionFailedError` and follows the Run failure/retry boundary;
- automatic Session title generation logs the timeout and abandons the best-effort title without failing the Run.

Non-streaming model requests are outside this ADR because parsed-event idle does not apply to them.

### Keep LiteLLM internal retries inside one Azents attempt

Existing LiteLLM internal retry behavior remains unchanged. The Azents parsed-event and absolute clocks start before `aresponses()` and do not reset when LiteLLM internally retries request establishment or a provider stream. Only a parsed provider event resets the idle clock, and nothing resets the absolute clock. A timeout or final exception that exits the complete LiteLLM call then enters the existing Azents failed-run retry boundary.

### Bound cooperative close and track non-cooperative tasks

When timeout ends a stream wait, Azents cancels the active `anext()` task and gives iterator/response close a five-second cooperative grace period. Five seconds is an internal cleanup budget rather than a provider or Codex timeout: it allows normal cancellation and close hooks to settle without letting cleanup materially extend the failed attempt. Cleanup that does not settle within that period cannot block retry. User Stop remains preemptive: it requests cancellation/close but transfers unfinished cleanup immediately instead of delaying interrupted-run finalization. Shutdown performs only bounded cleanup within its existing handover window.

The worker process owns a cleanup registry for unfinished or non-cooperative stream tasks. The registry keeps strong references, consumes eventual results and exceptions, records task age and active count, and discards any late event result before normalization or live/durable projection. Worker shutdown cancels registered tasks again and gives them a final bounded five-second drain; remaining tasks are logged and left for process exit to reclaim.

### Classify model-stream timeouts explicitly

Azents represents watchdog expiration as a dedicated `ModelStreamTimeoutError` under the user-visible model-call error hierarchy. The error preserves one of three structured failure codes:

- `model_connect_timeout`;
- `model_stream_idle_timeout`;
- `model_attempt_timeout`.

The failed-attempt boundary records `source = model`, `retryability = transient`, and the specific failure code. An intermediate timeout remains retry/live state and does not append a durable error. Only retry exhaustion promotes the user-safe timeout message to durable failed-run history. Internal logs preserve the timeout kind, configured deadline, elapsed duration, provider attempt number, provider, and model without logging generated content.

### Give User Stop precedence while an attempt is active

The model-stream wait races User Stop with the parsed-event idle and absolute attempt deadlines. Before converting a reached deadline into a timeout failure, the controller checks User Stop. If Stop and a deadline are ready together, User Stop wins.

When User Stop wins, the existing interruption path owns finalization and may durably preserve valid partial assistant text. Once timeout handling has claimed the attempt and begun failed-attempt cleanup, later Stop does not retroactively restore discarded output. It is handled as stopping retry under the existing failed-run policy and finalizes the latest timeout failure.

### Discard failed-attempt live output before publishing retry state

A timed-out provider attempt never contributes assistant text, reasoning, or incomplete tool projections to the next attempt. Before publishing live retry state, Azents performs this ordered cleanup:

1. prevent additional batch flushes from the timed-out attempt;
2. discard buffered partials;
3. await any already-started live upsert;
4. remove already-published assistant, reasoning, and incomplete tool projections;
5. persist and publish retry state;
6. start the next attempt with an empty model-output projection.

The cleanup ordering guarantees that an in-flight upsert cannot recreate stale output after removal and that failed and retried output never appear as one continuous response. Timeout-attempt output is not appended to durable history.

### Reuse the existing failed-run retry policy

Model-stream timeouts use the existing failed-run retry policy rather than a timeout-specific retry budget. The initial policy permits up to 10 retries after the initial attempt, with the existing durable retry state, exponential backoff, worker-handover recovery, live retry projection, and user stop control. The current `failed_attempt_count >= max_retries` implementation is an off-by-one drift from [failed-260627/ADR](./failed-260627-failed-error-retry.md) and must be corrected before timeout failures rely on the policy.

The timeout deadlines bound each provider attempt, not the total Run. A Run may therefore remain active for substantially longer than one attempt deadline while automatically retrying. This is intentional: background work should continue recovering without requiring the user to restart it manually. A user who no longer wants to wait can stop retry through the existing control path.

### Provide defaults with specific overrides

Azents owns common timeout defaults. Effective configuration is resolved from most specific to least specific:

1. model or inference-profile override;
2. provider override;
3. Azents default.

The initial implementation uses an internal typed policy resolver with the precedence above and no configured overrides. It does not add database columns, API fields, or UI settings. Each attempt records its effective policy in structured logs. Persistent provider, model, or inference-profile settings require a later design when an actual override use case exists.

The initial scope defines no special override for Deep Research, Flex, or other ultra-long-running model profiles. Such overrides require later operational evidence and an explicit decision.

### Use structured logs and enable the policy by default

Each streaming call records its effective deadlines, time to response handle, time to first parsed event, maximum parsed-event gap, total duration, outcome, and timeout failure code as structured fields. Run and Session identifiers remain searchable log fields rather than metric dimensions. Generated content, native event payloads, tool arguments, credentials, and attachments are never logged. Grafana/Loki derives timeout, latency, retry-recovery, and orphan-cleanup measurements without new durable timing columns or a new metrics client.

The watchdog is enabled by default for every streaming Responses call. There is no per-Session feature flag or legacy execution fallback. Rollback uses deployment rollback or a process-wide validated duration adjustment; persistent provider/model/profile settings remain outside this scope.

## Rejected Alternatives

### Infer semantic progress from event type or payload

Rejected because Azents cannot consistently determine which provider events represent meaningful work. This would couple reliability behavior to provider-specific semantics and LiteLLM normalization details.

### Use raw transport-byte inactivity as the model stream watchdog

Rejected as the product-level stream signal. A connection can continue delivering bytes or heartbeats while the adapter produces no usable parsed events. Transport libraries may still enforce lower-level connection safety, but raw byte activity does not define Azents model-stream progress.

### Enable parsed-event idle only for providers with a declared cadence capability

Rejected in favor of a common default with explicit duration overrides. Requiring capability metadata would leave unclassified providers without a bounded parsed-event wait.

### Use only an absolute attempt deadline

Rejected because it would delay detection of a completely stalled stream until the full attempt deadline.

## Consequences

- A model attempt that produces no parsed event is bounded even when its connection continues receiving non-event traffic.
- Event meaning is irrelevant to the watchdog; metadata and lifecycle events refresh the same deadline as content events.
- Providers that legitimately remain silent longer than the common deadline require an explicit override.
- Adapter parsing and event-yield behavior become part of the timeout boundary and require deterministic tests.
- A separate absolute deadline remains necessary for streams that stay active but never complete.

## Validation Remaining

- Confirm LiteLLM 1.87.0 timeout exception mapping and cancellation behavior for supported provider paths.
- Prove parsed-event idle, absolute deadline, failed-partial cleanup, retry recovery, and User Stop races with deterministic lower-level and testenv E2E coverage.
- Update the Agent Execution Loop living spec when implementation lands.

## Evidence

OpenAI Codex `2e1607ee2fa8099a233df7437adee5f16a741905` uses a 300,000 millisecond stream-idle timeout, a 15,000 millisecond Responses WebSocket connection timeout, five stream reconnection retries, and four HTTP request retries. Its HTTP SSE path applies the idle timeout after response-handle acquisition around each parsed SSE event wait. Its WebSocket path applies the idle timeout around request send and each next-frame wait, so Ping and Pong frames also satisfy the wait before their payload is ignored. Codex does not inspect event semantics for this deadline and has no application-level absolute attempt cap in these stream loops.

The Codex values are comparison evidence with distinct boundaries:

- 300 seconds directly supports the selected idle duration and all-event treatment, but Azents additionally covers initial response-handle acquisition.
- 15 seconds in Codex covers Responses WebSocket connection/prewarm only; Azents independently adopts the same duration for general connection establishment.
- Codex retry counts do not define Azents failed-run retry policy.
- Codex provides no source for Azents' 30-minute absolute cap or five-second cleanup grace.

The Azents 30-minute cap uses the production worker-log distribution recorded in the run-stall reliability discussion. The five-second close grace is an internal bounded-cleanup decision.

## Related Decisions

- [Model Stream Timeout Watchdog design](../design/model-stream-timeout-watchdog.md)
- [Run Stall Reliability Design Discussion](../notes/run-stall-reliability-design-discussion.md)
- [live-260604/ADR: Define Chat Live/History Handoff and Streaming Partial Batching](./live-260604-live-history-projection-handoff-and-stream-batching.md)
- [preemptive-260607/ADR: Preemptive User Stop with In-Flight Run Finalization](./preemptive-260607-preemptive-stop.md)
- [failed-260627/ADR: Failed Run Errors Use One Bounded Automatic Retry](./failed-260627-failed-error-retry.md)

## Migration provenance

- Historical source filename: `0146-model-stream-parsed-event-idle-and-attempt-bounds.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
