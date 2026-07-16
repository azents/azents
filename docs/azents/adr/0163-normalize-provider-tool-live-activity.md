---
title: "ADR-0163: Normalize Provider Tool Live Activity Across Model Adapters"
created: 2026-07-16
tags: [architecture, backend, engine, frontend, llm, tools]
---

# ADR-0163: Normalize Provider Tool Live Activity Across Model Adapters

## Context

Provider-hosted tools execute inside a model-provider stream rather than through the Azents client-tool executor. Some provider transports emit lifecycle observations while a hosted tool is running, but Azents currently creates canonical provider-tool events only after the complete model response has been normalized. Long-running hosted tools such as Web search therefore look like model latency even when the provider has already reported active work.

Provider transports expose different native event classes, identities, and status vocabularies. Making the engine, live-state store, API, or frontend depend on one provider's stream events would violate the adapter boundary and require repeated product changes for each future native adapter.

## Decision

### Add a provider-neutral stream projection

`AdapterOutputNormalizer[TNativeStreamEvent]` implementations may emit a provider-neutral provider-tool activity projection containing:

- a stable adapter-normalized `call_id`;
- the Azents semantic tool name;
- canonical status `running`, `completed`, or `failed`;
- optional canonical JSON-string arguments.

Native lifecycle values such as searching, generating, interpreting, queued, or in-progress remain inside the adapter normalizer. An adapter that receives no progress observation emits no synthetic activity.

### Share lifecycle accumulation across adapters

A common accumulator owns per-call deduplication, argument enrichment, and terminal-state monotonicity. Adapter-specific code only extracts provider-tool observations from native events. It must not publish live state, depend on Redis, or construct frontend messages.

### Project activity through the existing live Event surface

The engine converts provider-tool activity projections into internal ephemeral telemetry. `LiveEventProjector` converts that telemetry into non-durable `provider_tool_call` Event projections stored through `LiveEventStore` and published as the existing `live_event_upserted` and `live_event_removed` actions.

The live projection uses a deterministic identity derived from Session and call ID. A matching durable provider-tool call or result replaces the live projection by semantic call identity. Durable history is published before live removal.

### Keep provider activity outside client-tool execution state

Provider-hosted activity remains inside the `streaming_model` Run phase. It is not stored in `agent_runs.active_tool_calls`, does not enter the client-tool executor, and does not change tool cancellation or recovery semantics.

### Treat activity as model-attempt-local state

Failed-attempt cleanup removes streaming assistant, reasoning, and provider-tool activity projections before retry state is published. Terminal Run cleanup and User Stop remove remaining live activity through the existing Session live-state cleanup path.

### Preserve provider-neutral canonical status

`ProviderToolCallPayload` may carry nullable canonical status so both live and durable provider-tool calls can represent known running, completed, or failed state. Providers that do not expose a reliable state leave it null. Provider-native status strings are not persisted in canonical fields.

## Consequences

- All current and future adapters use one engine, live-state, transport, and frontend contract for provider-hosted tool progress.
- OpenAI SDK, LiteLLM Responses, and future native adapters keep provider event parsing isolated in their normalizers.
- Provider progress appears before the complete model response when the transport supplies a reliable observation.
- Providers without progress observations retain current behavior without guessed activity.
- Live state remains recoverable through `/live` and WebSocket resync without a database migration.
- The stream projection contract becomes a typed discriminated union rather than an open string-plus-optional-fields record.
- Provider-tool status becomes part of the canonical event payload contract and requires backend/frontend compatibility tests.

## Alternatives Considered

### Add OpenAI Web-search lifecycle handling directly to the worker

Rejected because official SDK types and wire discriminators would escape the adapter boundary and the design would not apply to LiteLLM or future native adapters.

### Put provider calls in `agent_runs.active_tool_calls`

Rejected because that state is the durable execution and recovery authority for Azents-executed client tools. Provider-hosted tools cannot be retried, cancelled, or reconciled through the client-tool executor.

### Show activity whenever a hosted tool is enabled

Rejected because tool availability does not prove that the model invoked the tool. Azents displays only observed provider activity.

### Append incomplete provider-tool calls to durable history

Rejected because partial stream observations are attempt-local UI state. Failed attempts and retries must not leave incomplete durable tool history.
