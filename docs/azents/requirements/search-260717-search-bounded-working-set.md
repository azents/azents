---
title: "Tool Search and a Bounded Model-Visible Tool Working Set Historical Requirements Reconstruction"
created: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: search-260717
historical_reconstruction: true
migration_source: "docs/azents/adr/0147-tool-search-bounded-working-set.md"
---

# Tool Search and a Bounded Model-Visible Tool Working Set Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `search-260717`
- Source: `docs/azents/adr/search-260717-search-bounded-working-set.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently collects every enabled Toolkit's available `FunctionTool` values for each model turn and lowers the complete, name-sorted catalog into the provider request. [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) made this catalog deterministic and moved MCP discovery off the run critical path through session-bound snapshots, but it intentionally deferred the separate problem of limiting how many collected tools are model-visible.

Large combinations of built-in, MCP, cloud, and service toolkits can exceed a model or provider's hard limit on declared tools. Some model families reject a request that declares more than their supported maximum instead of merely degrading tool selection quality. Even below a hard limit, sending every schema increases prompt size and weakens tool selection.

Claude Code and Codex address the scaling problem through deferred tool exposure and Tool Search: a small direct tool set remains visible, deferred metadata is searched on demand, and matching tools are added to a subsequent model request.

Current provider documentation confirms that this is both a hard compatibility constraint and a quality problem:

- xAI documents a maximum of 200 tools per request in its Function Calling schema reference.
- Google Vertex AI documentation is internally inconsistent: generated `Tool` API references state a maximum of 128 function declarations, while the current function-calling overview states that up to 512 declarations can be specified.
- Google AI Studio's direct Gemini API function-calling guidance recommends limiting the active set for quality, but does not currently state a matching hard declaration-count limit.

The Google documentation conflict was verified on 2026-07-19. Azents uses the lower documented Vertex AI value as a conservative compatibility ceiling for applicable Vertex-hosted Google/Gemini request paths until Google publishes one consistent contract. This ceiling does not apply to direct Gemini API requests or to non-Google models hosted by Vertex AI.

Sources:

- <https://docs.x.ai/developers/tools/function-calling>
- <https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rpc/google.cloud.aiplatform.v1#tool>
- <https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling>
- <https://ai.google.dev/gemini-api/docs/function-calling>

Azents also needs to preserve provider prompt-cache locality. Changing the model-visible tool array changes the provider request prefix even when the system-prompt text itself is unchanged. Therefore arbitrary per-turn ranking or truncation would produce avoidable cache churn. A session-scoped bounded working set can keep the visible catalog stable until a Tool Search result or actual capability change requires a deliberate boundary.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Define an Agent-level, opt-in, provider-independent Tool Search mechanism that:

1. preserves the existing complete model-visible tool catalog unless an Agent administrator explicitly enables Tool Search;
2. when enabled, never sends more model-visible tool declarations than the selected provider request path permits;
3. keeps essential tools directly visible;
4. makes the remaining executable catalog searchable;
5. retains a stable session-scoped working set across model turns and AgentRuns;
6. changes the visible tool prefix only at explicit capability boundaries, primarily Tool Search activation, catalog invalidation, or model change;
7. evicts old deferred tools deterministically when newly activated tools would exceed the model budget.

## Non-goals

- Delaying MCP `list_tools`; snapshot-backed passive discovery remains governed by [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md).
- Provider-native deferred-loading protocol support in the first phase.
- Embedding-based semantic search in the first phase.
- Persistently changing which Toolkits are attached to an Agent.
- Hiding authorization, safety, or essential runtime controls behind Tool Search.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

- `Toolkit.update_context()` returns the complete currently available tool list each model turn.
- `build_tool_catalog()` applies final Toolkit slug prefixes and constructs the executable catalog.
- `ToolCatalog.native_tools` currently exposes the complete catalog in canonical name order.
- The model capability contract records whether tool calling is supported, but does not record a maximum tool count.
- The model call is prepared again after tool outputs within the same AgentRun, so a Tool Search call can affect the immediately following model request.
- [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) requires deterministic provider-facing ordering and snapshot-backed MCP tool availability.
- Recovery or control-plane capabilities that are necessary to operate the agent cannot depend on discovering themselves.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
