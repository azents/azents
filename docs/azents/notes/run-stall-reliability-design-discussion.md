---
title: "Run Stall Reliability Design Discussion"
created: 2026-07-14
updated: 2026-07-14
tags: [backend, engine, frontend, reliability, streaming]
---
# Run Stall Reliability Design Discussion

## Purpose

Record the topic-by-topic design discussion that follows the seven findings from the run-stall investigation. Each topic presents the original finding first, followed by solution options, trade-offs, and the accepted decision.

## Discussion Topics

| Order | Original topic | Status | Accepted direction |
| --- | --- | --- | --- |
| 1 | LLM streaming is not shown before provider EOF | Decided | Restore the intended incremental live-partial pipeline while preserving completion-only durability and tool admission. |
| 2 | A real server-side LLM hang is structurally possible | Implemented | Cancel a model stream after 90 seconds without its first native event or 360 seconds without a subsequent native event, then use the existing retry boundary. |
| 3 | Auto-compaction runs before the next LLM call for large contexts | Decided | Keep compaction blocking at the model boundary, split the transaction around the external summary call, and make start/completion/input-buffer behavior durable and push-driven. |
| 4 | Repeated preparation cost occurs between tool completion and the next LLM call | Deferred | The available MCP timings measure background refresh, not confirmed foreground latency; instrument the model-call preparation boundary before selecting an optimization. |
| 5 | One completed tool does not mean that all sibling tools completed | Deferred | — |
| 6 | A separate client-side false-hang bug exists | Deferred | — |
| 7 | Meaning of the forced-stop screenshot | Deferred | — |

## Topic 1: LLM Streaming Is Not Shown Before Provider EOF

### Original Finding

The current implementation collects native provider events in memory and does not normalize or project them to the UI until the provider stream reaches EOF.

- Provider stream reception: `python/apps/azents/src/azents/engine/events/litellm_responses.py`
- Native event collection: `python/apps/azents/src/azents/engine/events/execution.py`
- Normalization after stream completion: `python/apps/azents/src/azents/engine/events/execution.py`
- Live projection after normalization: `python/apps/azents/src/azents/engine/events/engine_adapter.py`

As a result, healthy model reasoning, a provider that is actively sending tokens, a provider stream that has stalled, and a half-open network wait all appear as the same generic activity indicator. Incremental projection was previously introduced and then reverted, and the deployed version still has completion-only projection.

### Original Architectural Intent

The separate durable-event and live-partial projection paths exist so that model output can be visible incrementally without weakening durable run semantics:

- assistant text and reasoning deltas are projected live while the provider stream is open;
- canonical assistant output is appended durably only at the completion boundary;
- incomplete tool calls are never admitted or executed;
- an explicit user stop may preserve valid partial assistant text durably;
- the durable event replaces its live counterpart without duplicate content.

The current completion-only behavior is therefore treated as a regression, not as the desired architecture.

### Regression History

Repository history shows the current regression chain directly:

1. `6ccc98d0` restored incremental model delta normalization and projection while retaining completion-only durable output and tool admission.
2. `b92cbc6d` reverted that restoration, returning `_stream_model()` to collecting every native event in a list and normalizing only after EOF.
3. `b4faaf2f` subsequently removed the worker live-partial batcher after the engine had stopped producing live partials, leaving the current path without the original coalescing layer.

The available repository history begins with an imported codebase whose event-engine path was already completion-only, so it does not establish which pre-import change first broke the older incremental behavior. It does establish that `b92cbc6d` is the direct regression in the currently deployed history and that `b4faaf2f` compounded the restoration work required.

### Accepted Decision

Restore the original incremental streaming intent rather than designing a new completion-only progress model.

The restoration must preserve these invariants:

- normalize native provider events incrementally as they arrive;
- emit assistant and reasoning deltas through the live, non-durable path;
- retain bounded delta coalescing before Redis and WebSocket publication;
- keep canonical assistant output completion-durable;
- admit and execute tool calls only after complete provider output;
- durably preserve valid partial assistant text on explicit user stop;
- replace the live counterpart with the durable event without duplication or loss;
- keep reconnect and REST resync able to reconstruct the current live partial.

Implementation should recover the established intent and tests from the prior incremental path, then adapt it to subsequent engine changes instead of introducing a parallel streaming architecture.

### Status

Accepted.

## Topic 2: A Real Server-Side LLM Hang Is Structurally Possible

### Original Finding

The model-call path has no Azents-owned deadline for receiving the first provider event, no watchdog for time between provider events, and no overall attempt deadline. `_stream_model()` waits for the provider async iterator to finish, while the LiteLLM call and returned stream are not wrapped in an application-level timeout.

Transport defaults are provider and LiteLLM implementation details rather than a product policy. A half-open connection or a stream that never reaches EOF can therefore keep a run in the model phase for many minutes or longer. Retry begins only after an exception, so a stream that remains pending without raising never reaches retry handling. Once an error does occur, the existing outer retry policy can add several more minutes of hidden delay.

Restoring incremental projection in Topic 1 makes active output visible, but it does not terminate a provider stream that stops making progress.

### Solution Options

#### Option A — Continue relying on transport defaults

Leave timeout ownership to LiteLLM and the underlying HTTP transport. This avoids new policy but keeps behavior provider-dependent, does not reliably bound semantic stream idle time, and does not give Azents a stable failure contract.

#### Option B — Add one absolute model-call timeout

Wrap the complete model attempt in one wall-clock deadline. This is simple and guarantees termination, but it conflates connection delay, long reasoning, active streaming, and a stalled stream. A single value will either terminate legitimate high-reasoning calls too early or remain too long to be useful for detecting idle stalls.

#### Option C — Add stage-aware, stop-aware model watchdogs

Define separate bounds for:

- request start to first semantic provider event;
- time between subsequent semantic provider events;
- an optional provider/model/profile-specific absolute safety cap.

Any semantic native event refreshes stream activity even when it does not contain user-renderable text. User Stop remains an immediate independent cancellation path. On a watchdog timeout, close the provider stream, classify the attempt as a model timeout, clear or finalize its live partial according to the failed-attempt policy, and pass the error into an explicit timeout retry budget rather than the existing broad retry loop.

### Accepted Direction

Use Option C. Azents owns stage-aware, stop-aware model watchdogs instead of relying on transport defaults or one universal wall-clock timeout.

Numeric thresholds are intentionally not fixed yet. They will be discussed separately for each boundary because providers may acknowledge a request before producing any visible or reasoning output.

| Boundary | Definition | Status |
| --- | --- | --- |
| Provider first event | Request start to the first valid native provider event | In discussion |
| Pre-output idle | First provider event to the first meaningful model-progress event | Pending |
| Active-stream idle | Maximum gap between meaningful progress events after output begins | Pending |
| Absolute safety cap | Optional total attempt duration by provider/model/reasoning profile | Pending |

Timeout retry count and final partial-output handling remain open until the timing policy is established.

### TTFT Threshold Research

The initial 60-second proposal is not suitable as a cross-provider hard TTFT limit. Official provider guidance and production evidence show that long reasoning can legitimately take several minutes, while lifecycle events and visible model progress are distinct boundaries.

#### Official provider and SDK evidence

- OpenAI documents that Codex and Deep Research reasoning tasks can take several minutes and recommends background mode for long-running work to avoid timeout and connectivity failures.
- OpenAI streaming distinguishes `response.created` from later output deltas, so the first lifecycle event is not TTFT.
- OpenAI and Anthropic Python SDKs use 10-minute default request timeouts with 5-second connect defaults. These SDK defaults are comparison evidence, not the active Azents transport path.
- Anthropic recommends streaming or Batches for requests that may exceed 10 minutes and may emit `ping` events that represent transport liveness rather than semantic model progress.
- Gemini Flex documents a 1–15 minute latency target and recommends client timeouts of at least 10 minutes.

#### Active Azents transport

Azents uses LiteLLM's HTTP handler for this Responses path rather than the OpenAI Python SDK transport. With no explicit timeout, LiteLLM 1.87.0 passes a 6000-second scalar request timeout. HTTP read timeout measures inactivity between network chunks, so heartbeat bytes can keep the transport alive without producing a semantic model event.

#### Production evidence

A 14-day worker-log sample could measure total successful model-call wall time but not TTFT because first-event timestamps are absent:

- normal model calls: 4,494 successful proxies, p50 8.763s, p95 22.816s, p99 54.684s, maximum 1,155.462s;
- 38 calls exceeded 60s, 19 exceeded 120s, and 14 exceeded 300s;
- compaction calls: 309 successful calls, p50 35.171s, p95 53.769s, p99 58.117s, maximum 230.413s.

The calls over five minutes may be healthy long reasoning or streaming; current logs cannot determine whether their TTFT exceeded five minutes. A five-minute total-call limit would therefore be unsafe.

### Revised Numeric Proposal

Separate transport/lifecycle start from meaningful TTFT:

| Boundary | Proposed default | Rationale |
| --- | ---: | --- |
| TCP connect | 10s | Network connection establishment only; consistent with common SDK practice while allowing infrastructure variance. |
| First lifecycle event | 90s | Apply only to adapters that guarantee an early lifecycle event such as `response.created` or `message_start`. |
| First meaningful progress / TTFT warning | 60s | Record a slow-call signal only; do not cancel. Production p99 total time is near this boundary. |
| First meaningful progress / TTFT hard deadline | 360s | Preserves a valid five-minute TTFT with one minute of scheduling, parsing, and boundary-race margin. |
| Gemini Flex or explicit low-priority tier | Provider override of at least 600s | Matches the documented 1–15 minute latency class; async/background execution is preferable. |

For adapters that do not guarantee an early lifecycle event, do not apply the 90-second lifecycle deadline; use the 360-second meaningful-progress deadline as the first application-level event bound.

The HTTP read timeout should exceed the application watchdog so Azents owns timeout classification and cleanup. A candidate transport policy is connect 10s, pool 10s, write 60s, and read 420s, subject to verification of load balancer, NAT, and TCP keepalive behavior.

### Ping-Based Liveness Feasibility

Provider heartbeat is a better connection-liveness signal than visible TTFT when the provider guarantees a heartbeat cadence. It must remain distinct from semantic model progress: a ping proves that the stream connection and provider endpoint are alive, but not that the model is producing useful output.

The current LiteLLM Responses abstraction does not expose a reliable heartbeat event to Azents:

- OpenAI's SSE decoder drops comment heartbeat lines beginning with `:` before LiteLLM's Responses iterator yields an event.
- Native Responses JSON events are transformed and yielded, but no cross-provider ping contract exists.
- Anthropic `ping` events pass through lower chat-stream parsing as empty chunks and are not exposed as a distinct Responses event by the completion-to-Responses adapter.
- LiteLLM may synthesize initial Responses lifecycle events before consuming an underlying provider chunk, so those synthetic events cannot prove transport liveness.
- Azents' `LiteLLMResponsesModelAdapter` sees only the transformed iterator output, not raw response bytes or filtered heartbeat events.

A ping timeout is still implementable at the transport layer because `aresponses()` accepts a granular timeout object. HTTP read timeout is reset by raw network chunks, including filtered heartbeat bytes. This can enforce heartbeat liveness without surfacing each ping to the engine, but only for provider paths with a documented or measured maximum heartbeat interval.

A full application-visible heartbeat clock would require LiteLLM to expose raw stream activity through a callback/event or require a provider-specific transport adapter below the current Responses iterator. Tapping the returned iterator's response concurrently is not safe because the stream already owns raw-byte consumption.

#### Proposed capability policy

- For a provider/tier with a guaranteed heartbeat cadence, use a heartbeat-derived HTTP read timeout as the primary connection-stall detector. Treat the five-minute TTFT boundary as a slow-progress/UX boundary rather than immediate cancellation while heartbeats continue.
- For a provider without a guaranteed heartbeat cadence, retain the semantic-progress watchdog as the fallback hard bound.
- Keep an absolute run/cost budget in both cases because continuous ping proves connection liveness, not useful model progress.
- Prefer background status polling over an indefinitely open stream when the provider supports resumable background execution.

### Assessment of LiteLLM Defaults

LiteLLM's default is not accepted as an Azents reliability policy. In the active Responses path, an unspecified timeout becomes a 6000-second scalar per-request timeout. This is compatibility-oriented for a general provider library, but it is unsuitable for an interactive agent runtime:

- it can make connect, pool, write, and read inactivity waits far longer than the product can reasonably explain to a user;
- HTTP read timeout is inactivity between chunks, not a total attempt deadline, so ping traffic can keep a semantically stalled stream alive indefinitely;
- `LITELLM_MAX_STREAMING_DURATION_SECONDS` defaults to no total bound;
- a timeout that occurs only after a very long wait then enters Azents' broader retry path, multiplying user-visible delay;
- infrastructure such as proxies, load balancers, and NAT may terminate the connection earlier, making the effective behavior environment-dependent.

The default remains useful only as a permissive library fallback. Azents should pass explicit granular transport limits and own stage-aware liveness, semantic-progress, cancellation, retry, and background-transition policy.

### Implemented Baseline

The event runtime applies two application-owned progress deadlines to the transformed native provider stream:

- 90 seconds from stream start to the first native provider event;
- 360 seconds between every subsequent native provider event.

A timeout cancels the pending asynchronous iteration, allows up to five seconds for cooperative provider cleanup, and raises a retryable `ModelStreamTimeoutError` even if cleanup remains pending. An adapter-scoped task registry owns and observes detached cleanup tasks until they finish. Provider-owned transport timeouts retain a separate transient failure code. The worker discards buffered deltas, then best-effort clears the failed attempt's live partial projection before it publishes retry state, so a new attempt does not normally append to stale text or reasoning. A projection cleanup failure is logged and does not block durable retry state. User Stop still independently cancels the stream without being converted into a timeout.

This baseline intentionally treats every native event as progress. It does not yet implement a raw-byte heartbeat detector, provider-specific overrides, a meaningful-output deadline, or an absolute attempt cap.

### Status

Implemented as the bounded baseline above. Provider-specific timing policy and raw transport heartbeat support remain future work.

## Topic 3: Auto-Compaction Runs Before the Next LLM Call for Large Contexts

### Original Finding

Automatic compaction is executed synchronously in `PREPARING_INPUT` before the next primary model request. Once the effective context threshold is exceeded, the run loads the selected transcript, appends a started marker, calls a separate summary model, enriches and stores the summary, moves the model-input head, and only then proceeds to normal model preparation.

This means a completed tool can be followed by tens of seconds with no primary-model output even when nothing is deadlocked. The screenshot showed a very large context, and production evidence confirms that compaction is a significant routine delay:

- 309 successful compaction calls: p50 35.171s, p95 53.769s, p99 58.117s, maximum 230.413s;
- one directly observed example took about 29.1 seconds;
- the current UI can lose or obscure the ephemeral compaction-start signal, leaving only a generic activity indicator.

The compactor currently appends the started marker and then awaits the external summary model in the same database transaction. Event append locks the session row, so a slow summary can hold that transaction and block stop/finalization or other session append paths. The summary itself is required before the next primary model call when the current input is over budget, so simply running the primary call concurrently is unsafe.

### Solution Options

#### Option A — Keep the current synchronous transaction

Continue holding the current transaction across summary generation. This preserves a simple snapshot but keeps the lock duration coupled to external model latency and leaves stop/control behavior vulnerable to a slow summary.

#### Option B — Keep compaction at the model boundary but split persistence from external work

Preserve the synchronous requirement that compaction completes before the next primary model request, while changing the operation into committed stages:

1. select a fixed compaction cutoff;
2. append the started marker at its reserved logical model order and commit;
3. generate and enrich the summary without holding the session row lock;
4. reopen a transaction, verify the compaction id, run ownership, cutoff, and current head;
5. append the summary at the reserved logical order, move the model-input head, and commit;
6. append a durable failed/cancelled marker on failure or Stop.

Events appended after the cutoff retain later logical model order and remain visible after the summary head. The durable started marker and run phase become the authoritative UI/resync signal instead of relying only on an ephemeral notification.

#### Option C — Proactively compact in the background before the hard threshold

Start summarizing a stable prefix at a lower soft threshold so the summary may be ready before the next model boundary. Preserve events after the cutoff as raw tail. This can hide most latency but introduces stale-result validation, wasted summaries, concurrent compaction ownership, and additional cost.

### Accepted Decision

Choose Option B. Keep compaction blocking at the model boundary, split database persistence from external summary generation, and include the observed UI delivery and input-buffer failures in the same correction scope.

#### Durable start and immediate UI delivery

The current start path relies on a one-shot ephemeral `compaction_started` control event while the durable started marker remains uncommitted behind the summary-model transaction. If the control event is missed, the client cannot recover the state until a later REST snapshot.

The corrected start boundary must:

1. append the durable started marker and set the run phase to `compacting`;
2. commit both before calling the summary model;
3. publish the committed marker as a canonical `history_event_appended` frame;
4. publish the live phase/control update after commit;
5. let the UI enter compaction state directly from either the run phase or the control event without requiring a blocking full resync.

REST remains recovery for reconnects, not the primary mechanism for rendering compaction start.

#### Durable completion and ordered push delivery

Compaction marker/summary events are currently appended inside the pre-lower filter and are not emitted through the normal durable output sink. The client therefore depends on `compaction_complete` triggering a REST resync. If that resync buffers or stalls, later messages can appear while the compaction marker and summary remain absent until reload.

The corrected completion boundary must:

1. append the summary at the reserved logical order and move the model-input head;
2. commit before publishing;
3. emit the committed `compaction_summary` through the canonical durable history path;
4. publish the completed phase/control update after the durable summary;
5. clear the UI compaction state without requiring full REST resync;
6. preserve durable-summary-before-later-message delivery order.

A missed push remains recoverable from the durable marker, summary, and run phase on reconnect.

#### Input buffering during compaction

The current compaction transaction holds the session row lock while awaiting the summary model. Input-buffer insertion needs the same session serialization boundary, so a user message sent during compaction can block until summary completion and does not appear as pending input.

After the started-marker transaction commits, summary generation must run without the session row lock. Input writes must then:

- commit to the input buffer immediately during compaction;
- publish the pending-input frame immediately;
- remain outside the fixed compaction cutoff and summary content;
- preserve FIFO order;
- be promoted normally after compaction completes and the run reaches its input boundary.

Stop must also remain responsive during the external summary call. Cancellation writes a durable failed/cancelled compaction outcome and must not leave the session head pointing at an incomplete summary.

#### Required regression coverage

- start indicator appears without reload;
- reload during compaction reconstructs the same state;
- summary and marker appear before later appended messages without reload;
- completion clears compaction state without a full resync dependency;
- a message sent during compaction is accepted promptly, shown as pending, and promoted after compaction;
- multiple inputs retain FIFO order;
- Stop during compaction remains responsive and leaves a valid model-input head;
- missed WebSocket control events recover from durable REST state.

Proactive background compaction remains out of scope until this blocking boundary is reliable and measured.

### Status

Accepted.

## Topic 4: Repeated Preparation Cost Before the Next LLM Call

### Corrected Finding

Every model turn rebuilds the complete tool catalog after tool execution and before the next provider request. For each toolkit binding, `build_tool_catalog()` sequentially awaits:

1. `update_context()`;
2. `get_static_prompt()`;
3. `get_dynamic_prompt()`.

MCP remote discovery is already asynchronous and is not awaited by this turn-boundary catalog build:

- `McpBasedToolkit.__aenter__()` starts `_connect_and_list_tools()` as a background task;
- a successful discovery is persisted as a deterministic Toolkit State snapshot;
- `update_context()` loads the latest persisted snapshot, rebuilds local `FunctionTool` wrappers, and returns without awaiting `mcp_list_tools()`;
- if the previous background task has completed, `update_context()` starts another background refresh, again without awaiting it;
- a first turn with no persisted snapshot exposes no MCP tools rather than blocking for discovery;
- the toolkit object is session-scoped, while the snapshot is persisted by agent, session, toolkit namespace, and state name.

Therefore the observed slow `update_context()` measurements do not prove that MCP network discovery blocked the next LLM call. They measure the synchronous snapshot path and any wrapper/toolkit work around it:

- GitHub with 41 exposed tools: approximately 4.3–5.2 seconds;
- Sentry with 9 exposed tools: approximately 0.4–1.0 seconds.

For base MCP this critical path includes a separate DB session and Toolkit State snapshot load, snapshot validation/deserialization, and reconstruction of every wrapper. The affected GitHub configuration has three installations. GitHub multi-installation mode processes those bindings serially, opening one separate session per installation snapshot, and then opens another session to read selected-installation state for its static prompt. The shared session manager commits even read-only sessions, and the engine uses `pool_pre_ping=True`, so one snapshot access can include pool checkout/pre-ping, the snapshot `SELECT`, and transaction completion. The three serial snapshot accesses are therefore the leading explanation for the GitHub-to-Sentry timing ratio, although stage timing is still required to distinguish pool wait, DB round trips, payload validation, and wrapper construction.

Each installation rebuilds wrappers for every tool in its stored snapshot before GitHub applies toolset filtering. Three installations can therefore deserialize and rebuild up to three complete remote catalogs even when the final exposed catalog is much smaller. This is expected to be secondary to I/O but is not currently measured.

The background network refresh can still repeat after completed refresh tasks and can consume provider, DB-pool, and snapshot-write capacity concurrently with foreground work. With three installations it can run three discoveries and later three snapshot writes concurrently. That is a separate load/contention concern, not direct remote discovery latency on the model-turn critical path. Plain snapshot `SELECT` statements do not themselves take row locks, so row-lock blocking is not the leading hypothesis; pool checkout and database/network latency are stronger candidates.

The slow log covers only `update_context()` after it returns. It does not break down snapshot DB wait, deserialization, wrapper construction, static prompt, dynamic prompt, background discovery, or background snapshot persistence. An await that never returns also produces no completed-duration log.

### Solution Options

#### Option A — Instrument before changing preparation behavior

Add per-stage timing and tracing first. Distinguish foreground snapshot load from background MCP discovery and persistence. This has the smallest correctness risk and avoids optimizing the wrong layer, but leaves the measured repeated delay in place until evidence is collected.

#### Option B — Remove repeated MCP snapshot work from the foreground path

Treat the persisted Toolkit State snapshot as bootstrap and recovery storage, not as the per-turn read path. After initial load, keep the latest immutable snapshot and rebuilt tool wrappers on the session-scoped toolkit instance. A successful background refresh atomically replaces the in-memory generation and persists it. `update_context()` reads the current in-memory generation without a DB round trip or wrapper rebuild.

GitHub installation snapshots follow the same pattern per installation. Credential headers remain resolved at tool-call time where required. Binding, configuration, server URL, credential revision, and installation changes create or invalidate the corresponding session-scoped generation.

This directly targets the known MCP foreground work while preserving asynchronous discovery.

#### Option C — Execute independent toolkit preparation concurrently

Run each toolkit binding's foreground preparation as a bounded concurrent task, then merge tools and prompt fragments deterministically by original binding index. Keep operations inside one toolkit ordered when later calls depend on its updated context, and explicitly serialize toolkits that share mutable state or a non-concurrent dependency.

This reduces additive latency across independent toolkits but does not fix a slow path inside the dominant toolkit.

#### Option D — Introduce a general stable/turn-dynamic preparation contract

Separate stable tool definitions and static prompts from turn-dynamic state across all toolkit types. This may benefit built-in toolkits and repeated DB-backed prompts, but it is a broader framework change. Existing MCP already implements asynchronous discovery and durable snapshot reuse, so this option is not a prerequisite for removing MCP network discovery from the foreground path.

### Recommendation

Start with Option A's stage instrumentation, then apply Option B to the confirmed MCP snapshot foreground cost. Add bounded deterministic concurrency from Option C after shared-state safety is classified. Defer the general Option D contract until measurements show material repeated cost outside MCP.

Required measurements are:

- foreground Toolkit State acquisition, including DB pool checkout and query wait;
- snapshot deserialize/validate time;
- wrapper reconstruction and filtering time;
- static and dynamic prompt time;
- background `mcp_list_tools()` time;
- background snapshot save time and lock/pool wait;
- snapshot source and generation (`memory`, `persistent bootstrap`, or `empty`);
- tool count and final catalog build time.

### Status

Awaiting decision.

## Decision Log

- **Topic 1 — Incremental model streaming:** Restore the original durable-final/live-partial architecture. Treat completion-only projection as a regression introduced directly by `b92cbc6d` and compounded by removal of live-partial batching in `b4faaf2f`.
- **Topic 2 — Model watchdog architecture:** Retain the stage-aware, ping-aware direction, but defer implementation and numeric policy until higher-probability incident factors are addressed.
- **Topic 3 — Auto-compaction boundary:** Keep compaction blocking before the next model call, but commit and publish the durable started state before external summary generation, release the session lock during the LLM wait, accept and publish input buffers during that wait, then commit and push the durable summary before later messages. Do not depend on compaction-triggered full REST resync for normal UI delivery.
