---
title: "OpenAI Responses WebSocket Transport Historical Requirements Reconstruction"
created: 2026-07-17
implemented: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: openai-260717
historical_reconstruction: true
migration_source: "docs/azents/design/openai-responses-websocket-transport.md"
---

# OpenAI Responses WebSocket Transport Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `openai-260717`
- Source: `docs/azents/design/openai-260717-openai-responses-websocket-transport.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Unknown — the historical source does not state this explicitly.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Prefer the official Responses WebSocket transport for eligible OpenAI API-key and ChatGPT OAuth sampling.
- Reuse one healthy socket across sequential model and foreground-tool turns within one `AgentRunExecution`.
- Preserve the complete `OpenAIResponsesRequest` as the single logical request contract for HTTP and WebSocket.
- Preserve the existing output normalizer, watchdog, failed-Run retry, live projection cleanup, and durable event admission boundaries.
- Prevent a cancelled, timed-out, abandoned, or malformed response from contaminating the next request on a reused socket.
- Make transport fallback sticky for the owning `SessionRunner` without retaining idle sockets between Agent Runs.
- Preserve current OpenAI continuation semantics without allowing response IDs or connection-local state to become durable conversation state.
- Provide a deployment kill switch and a clean revert path to the already-supported official-SDK HTTP transport.
- Keep credentials, account headers, request/response content, response IDs, and raw frames out of logs and test evidence.

## Non-goals

- No Responses Lite dialect or Codex-specific request lowering.
- No Codex attestation, prewarm request, private metadata, request compression policy, or private hosted-tool executor.
- No process-wide or SessionRunner-lifetime socket pool.
- No concurrent responses on one socket.
- No SDK automatic reconnect or active-response replay.
- No WebSocket support for custom OpenAI-compatible base URLs in the initial release.
- No WebSocket transport for compaction or automatic Session title generation.
- No connection-local `previous_response_id` use for ChatGPT OAuth.
- No change to client-tool execution, provider-hosted tool normalization, durable transcript schemas, or public APIs.
- No attempt to hide retry exhaustion by granting WebSocket transport failures an additional retry budget.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
