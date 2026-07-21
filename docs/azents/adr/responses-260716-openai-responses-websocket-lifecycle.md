---
title: "Define the OpenAI Responses WebSocket Lifecycle"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, websocket, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: responses-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0150-openai-responses-websocket-lifecycle.md"
---

# responses-260716/ADR: Define the OpenAI Responses WebSocket Lifecycle

## Status

Accepted. This ADR defines the initial lifecycle, retry, fallback, and provider rollout policy for the standard OpenAI Responses WebSocket transport.

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-105) established an OpenAI-native Responses transport family in which HTTP and WebSocket consume the same complete logical request and SDK HTTP is the physical fallback. The HTTP phase is now implemented for OpenAI API-key and ChatGPT OAuth sampling, compaction, and automatic Session title generation. [standard-260716/ADR](./standard-260716-standard-responses-for-chatgpt-oauth.md) also removed the Responses Lite dialect and standardized ChatGPT OAuth on the normal Responses request contract.

The WebSocket work is therefore a physical transport addition to the existing `OpenAIResponsesRequest`, adapter, normalizer, watchdog, and failed-Run boundaries. It does not introduce another lowerer, provider dialect, canonical event format, or tool executor.

## Current Implementation Baseline

### Sampling lifecycle

`AgentEngineAdapter.run()` creates one `OpenAIResponsesModelAdapter` and one official SDK client for one `AgentRunExecution` when the provider is OpenAI API-key or ChatGPT OAuth.

- The adapter is reused across sequential model/tool turns within that execution.
- OpenAI API-key sampling receives a `ResponsesContinuationPlanner`.
- ChatGPT OAuth sampling receives no continuation planner and always lowers complete logical input with `store=false`.
- The execution closes the adapter in `finally` on completion, failure, timeout, or cancellation.
- A failed-Run retry re-enters the engine and creates a new execution-owned adapter and SDK client.

Compaction and automatic Session title generation are separate bounded SDK HTTP operations. They create and close their own clients and do not share the sampling adapter.

### Streaming and normalization

`ModelStreamWatchdog` owns response-handle acquisition, parsed-event idle, absolute-attempt, cancellation, and cleanup bounds. It closes the active response wrapper after timeout or caller cancellation and retains non-cooperative cleanup through the process registry.

`AgentRunExecution._stream_model()` immediately passes every yielded native event to the output normalizer. Incremental projections may be published before terminal completion. A successful model step still requires the exact documented typed terminal boundary. Failed non-Stop attempts are later removed from live projection by the worker failed-Run retry boundary.

This means one normalizer state cannot transparently consume part of a WebSocket response and then restart the same logical request over HTTP. Physical fallback after an event has been yielded must occur in a later model attempt after failed-attempt projection cleanup.

### SessionRunner lifecycle

`SessionRunner` processes one Session sequentially and remains warm for up to 30 minutes of Session idle time.

The lifecycle issues recorded in the earlier draft have been fixed:

- the idle baseline resets after each processed wake-up;
- active Runs renew the sticky owner lease and owner heartbeat;
- idle runners renew the owner heartbeat until idle timeout;
- graceful teardown releases ownership and Session-scoped resources;
- worker handover transfers no in-memory transport state.

A worker can host many warm Session runners, so keeping one open model socket for the full runner lifetime has materially different capacity implications from a single-user Codex process.

## Revalidated SDK and Protocol Facts

The pinned official SDK is `openai==2.45.0`.

- `AsyncOpenAI.responses.connect()` derives a WebSocket `/responses` URL from the configured HTTP base URL unless `websocket_base_url` is supplied.
- The generated Responses WebSocket client-event union exposes `response.create` and no foreground Responses cancellation event.
- Incremental output events do not include a response ID that could safely demultiplex concurrent requests.
- One socket must therefore have at most one active logical response.
- Cancelling SDK `recv()` leaves unread events available. A cancelled or abandoned response cannot share its socket with the next request.
- SDK automatic reconnect is disabled unless `on_reconnecting` is supplied. Reconnect restores a socket and flushes unsent messages but does not replay an already-sent active response.
- Azents must keep SDK auto-reconnect disabled and own request replay, retry, and fallback.
- The WebSocket handshake merges SDK authentication with `responses.connect(extra_headers=...)`; `AsyncOpenAI.default_headers` are not automatically copied into this handshake path.
- ChatGPT account and client-identity headers must be explicitly supplied to the WebSocket connection.
- `openai[realtime]==2.45.0` declares `websockets>=13,<16`. WebSockets 15.x also satisfies the current MCP and Uvicorn constraints.
- The generated WebSocket request method cannot represent the current HTTP-only `extra_body` extension used for the `stop` option. Requests with explicit `stop` remain HTTP-only unless a documented WebSocket representation is added.

Unknown WebSocket discriminators can be materialized by SDK 2.45.0 as an unrelated generated model class while retaining the unknown `type` value. Existing class-and-wire checks must remain in place. Unknown provider metadata events may refresh the stream idle watchdog but do not create canonical output.

The generated union contains `ResponseCompletedEvent` with `type="response.completed"`. The official SDK WebSocket example also contains a compatibility branch for `response.done`. Live ChatGPT OAuth validation completed with `response.completed`; OpenAI Platform terminal behavior was not live-validated before the accepted simultaneous rollout.

## Live ChatGPT OAuth Evidence

A retained external probe established one authenticated ChatGPT OAuth Responses WebSocket and completed two sequential standard Responses requests on that socket.

- Standard text output completed.
- Provider-hosted web search completed.
- The probe worked with and without the currently observed Responses WebSocket beta header.
- Each request used complete logical input; ChatGPT connection-local `previous_response_id` continuation was not tested.
- Provider-specific metadata events appeared alongside standard Responses events.

The probe, token artifacts, response IDs, response text, and raw frames remain outside the repository. OAuth artifacts are retained until the user explicitly authorizes deletion.

## Review of Earlier Draft Decisions

| Earlier draft item | Review | Current treatment |
| --- | --- | --- |
| SessionRunner owns the live socket | Revise | `AgentRunExecution` owns and reuses the live socket only within one execution, limiting sockets to active executions. |
| Strict request-extension continuation | Retain with provider split | Keep the existing strict planner for OpenAI API-key. ChatGPT OAuth continues to send complete input without `previous_response_id`. |
| HTTP fallback is sticky for the SessionRunner lifetime | Revise | `SessionRunner` retains keyed HTTP-only fallback state without retaining the live socket. |
| Two WebSocket retries, then two HTTP retries | Replace | WebSocket has no separate retry loop or budget. A transport failure consumes the existing failed-Run retry count, and the next attempt uses HTTP. |
| SDK automatic reconnect remains disabled | Retain | SDK reconnect does not restore the active logical response. |
| Cancellation or terminal stream failure invalidates the socket | Retain | Required to prevent unread events from contaminating the next request. |
| ChatGPT OAuth remains HTTP-only | Obsolete | Standard ChatGPT OAuth Responses WebSocket text and hosted web search have now been validated. |
| SessionRunner idle and owner-renewal fixes are prerequisites | Resolved | Both discrepancies recorded by the earlier draft are fixed in the current implementation. |
| One-hour provider socket limit | Remove as an assumption | This was not revalidated from the current documented SDK contract and is not needed for the initial lifecycle decision. |

## Confirmed Engineering Constraints

These constraints do not require further product-level discussion:

- WebSocket and HTTP consume the same complete `OpenAIResponsesRequest` after all lowerers, filters, compaction, file materialization, and size guards.
- LiteLLM does not send fallback requests for OpenAI-compatible providers.
- One socket processes one logical response at a time.
- Successful sequential responses may reuse a healthy socket within its chosen owner scope.
- User Stop, timeout, cancellation, premature close, framing failure, or decode failure before terminal completion closes and invalidates the socket.
- SDK automatic reconnect stays disabled.
- A new socket generation starts without a WebSocket continuation boundary.
- ChatGPT OAuth uses full logical input, `store=false`, encrypted reasoning inclusion, and no `previous_response_id`.
- Unknown transport metadata does not create live or durable model output.
- Requests containing an explicit `stop` option use HTTP.
- Custom OpenAI-compatible base URLs are not assumed to support WebSocket.
- Compaction and automatic Session title generation remain HTTP-only in the initial phase.
- No credentials, authorization codes, account headers, request or response bodies, response IDs, response text, or raw frames are logged or retained as evidence.

## Decision 1: AgentRunExecution Owns the Live Socket

`AgentRunExecution` owns the live WebSocket. It opens the connection lazily, reuses it across sequential model/tool turns within the execution, and closes it when the execution ends.

`SessionRunner` owns only lightweight HTTP-only fallback state keyed to the resolved provider, endpoint, and non-sensitive credential configuration identity. A failed-Run retry can therefore start directly on HTTP after a transport-specific WebSocket failure without retaining an idle socket between Agent Runs.

This boundary intentionally reconnects for each later Agent Run. The initial implementation accepts that handshake frequency in exchange for matching the existing adapter lifecycle and limiting live sockets to active executions. Cross-Run connection retention will be reconsidered only if observed connection frequency or handshake overhead becomes an operational problem.

Rejected alternatives:

- Keeping both the socket and fallback state execution-scoped would cause a failed-Run retry to repeat the same WebSocket failure.
- Keeping the socket for the full SessionRunner lifetime would retain one socket per warm Session for up to 30 minutes and require idle rotation and connection-capacity controls before evidence shows they are necessary.

## Decision 2: WebSocket Fallback Uses the Failed-Run Retry Boundary

Azents does not perform inline WebSocket-to-HTTP fallback inside one model attempt. A WebSocket transport failure before exact terminal completion follows the same failed-Run retry boundary regardless of whether the adapter has yielded a native event.

1. Close and invalidate the WebSocket.
2. Mark the matching SessionRunner transport state HTTP-only.
3. Fail the current model attempt.
4. Let the worker discard failed-attempt live assistant and reasoning projections. This is a no-op when no event produced a projection.
5. Let the next failed-Run attempt create a fresh execution and normalizer and execute the complete logical request over SDK HTTP.

The transport failure consumes the existing failed-Run retry count and backoff exactly like an HTTP connection or request failure. There is no separate WebSocket retry budget, reconnect loop, or retry exemption. Exhausting the shared retry budget may therefore terminate the Run without an HTTP attempt; this is accepted as the normal consequence of retry exhaustion.

Only failures classified as WebSocket transport failures activate HTTP-only state. Provider response failures, invalid requests, authentication, authorization, quota errors, and model errors do not activate fallback because HTTP is expected to repeat them. User Stop remains an interrupted Run rather than a failed-Run retry and does not mark WebSocket unsupported. An application watchdog expiry invalidates the active socket but does not by itself prove that the WebSocket transport is unsupported.

The first-yielded-event boundary remains relevant to explaining why inline fallback would be unsafe after normalizer mutation, but it does not change the selected retry behavior.

## Decision 3: Roll Out OpenAI Platform and ChatGPT OAuth Together

The initial sampling rollout makes both official OpenAI API-key and ChatGPT OAuth configurations eligible for WebSocket under the same deployment control. OpenAI Platform activation is not blocked on a separate live terminal-event gate.

This accepts the risk that live OpenAI Platform behavior may expose a terminal or event-shape difference not observed through the generated SDK contract or ChatGPT OAuth validation. The existing exact class-and-wire terminal checks remain authoritative; an unrecognized terminal is not promoted to successful completion. If production evidence reveals an incompatibility, the WebSocket change is disabled or cleanly reverted and sampling returns to the existing SDK HTTP path without data migration or artifact rewriting.

The remaining rollout scope is:

- Custom OpenAI-compatible base URLs remain HTTP-only initially.
- Compaction and automatic Session title generation remain HTTP-only initially.
- WebSocket eligibility is deployment configuration rather than a stored model capability.
- Deterministic connection, sequential-response, cancellation, invalidation, and fallback behavior remains covered by automated tests even though OpenAI Platform live validation is not a rollout prerequisite.

Safe telemetry may include provider, model, call kind, selected transport, connection reuse, connection outcome, fallback stage, bounded failure class or status, parsed event count, and timing. Content-bearing fields remain prohibited.

## Remaining Risks

- A request replayed after it may have reached the provider has at-least-once physical execution semantics and may duplicate inference or hosted web-search cost.
- OpenAI Platform may require an explicit `response.done` adaptation that is not represented by the generated SDK event union.
- WebSocket handshake headers must remain in lockstep with HTTP credential and identity configuration.
- A provider or proxy may support HTTP Responses but reject WebSocket upgrade or large frames.
- A WebSocket transport failure consumes the shared failed-Run retry budget and may terminate the Run before any HTTP attempt when that budget is exhausted.

## Decision Summary

1. `AgentRunExecution` owns and reuses the live socket within one Run, while `SessionRunner` retains only keyed HTTP-only fallback state.
2. A WebSocket transport failure uses the existing failed-Run retry boundary and shared retry budget; there is no inline fallback or separate WebSocket retry loop.
3. Official OpenAI API-key and ChatGPT OAuth sampling roll out together under the same deployment control, with SDK HTTP retained as the revert path.

## Migration provenance

- Historical source filename: `0150-openai-responses-websocket-lifecycle.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
