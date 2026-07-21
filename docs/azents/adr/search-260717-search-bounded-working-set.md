---
title: "Tool Search and a Bounded Model-Visible Tool Working Set"
created: 2026-07-17
tags: [architecture, backend, engine, toolkit, llm, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: search-260717
historical_reconstruction: true
migration_source: "docs/azents/adr/0147-tool-search-bounded-working-set.md"
---
# search-260717/ADR: Tool Search and a Bounded Model-Visible Tool Working Set

## Context

Azents currently collects every enabled Toolkit's available `FunctionTool` values for each model turn and lowers the complete, name-sorted catalog into the provider request. [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) made this catalog deterministic and moved MCP discovery off the run critical path through session-bound snapshots, but it intentionally deferred the separate problem of limiting how many collected tools are model-visible.

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

## Current Constraints

- `Toolkit.update_context()` returns the complete currently available tool list each model turn.
- `build_tool_catalog()` applies final Toolkit slug prefixes and constructs the executable catalog.
- `ToolCatalog.native_tools` currently exposes the complete catalog in canonical name order.
- The model capability contract records whether tool calling is supported, but does not record a maximum tool count.
- The model call is prepared again after tool outputs within the same AgentRun, so a Tool Search call can affect the immediately following model request.
- [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) requires deterministic provider-facing ordering and snapshot-backed MCP tool availability.
- Recovery or control-plane capabilities that are necessary to operate the agent cannot depend on discovering themselves.

## Goal

Define an Agent-level, opt-in, provider-independent Tool Search mechanism that:

1. preserves the existing complete model-visible tool catalog unless an Agent administrator explicitly enables Tool Search;
2. when enabled, never sends more model-visible tool declarations than the selected provider request path permits;
3. keeps essential tools directly visible;
4. makes the remaining executable catalog searchable;
5. retains a stable session-scoped working set across model turns and AgentRuns;
6. changes the visible tool prefix only at explicit capability boundaries, primarily Tool Search activation, catalog invalidation, or model change;
7. evicts old deferred tools deterministically when newly activated tools would exceed the model budget.

## Non-Goals

- Delaying MCP `list_tools`; snapshot-backed passive discovery remains governed by [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md).
- Provider-native deferred-loading protocol support in the first phase.
- Embedding-based semantic search in the first phase.
- Persistently changing which Toolkits are attached to an Agent.
- Hiding authorization, safety, or essential runtime controls behind Tool Search.

## Decision Topics

The following topics were discussed and are recorded in the accepted decisions below:

1. Provider-request tool-budget contract and the fallback policy when no verified limit is known.
2. Direct, deferred, and hidden exposure classification.
3. Scope and persistence of the active deferred-tool working set.
4. LRU recency semantics and deterministic eviction behavior.
5. Behavior when direct tools alone exceed the provider request path's tool budget.
6. Search result activation size, ranking, and handling of removed or schema-changed tools.
7. Provider cache boundaries and observability.
8. Agent-level opt-in configuration and disabled-mode compatibility behavior.

## Decisions

### search-260717/ADR-D1. Keep one session-scoped working set; apply the limit at each prepared model call

Azents will keep one deferred-tool working set per session. It will not maintain separate working-set membership or recency histories per model or provider request path.

The current provider request path contributes only its effective model-visible tool limit. When a model call is prepared, Azents projects the shared session working set into that call's available deferred-tool slots after accounting for pinned direct tools. If the resolved request-path limit is smaller, the provider-facing projection includes only the most recent eligible deferred tools that fit. Switching to a request path with a larger limit can expose more tools from the same session working set without rebuilding a separate history.

Tool Search activation and actual deferred-tool invocation update the shared session recency order. A smaller prepared-call projection does not delete the non-visible tail from the session working set merely because those tools do not fit that call.

Rationale:

- A tool remains relevant to the conversation when the user switches models or provider request paths.
- Maintaining parallel request-path-specific histories would make behavior harder to understand and would require repeat discovery after model changes.
- Request-path differences are compatibility constraints on request lowering, not separate user capability states.

Consequences:

- The session working set may contain more tools than a particular provider request path can receive.
- Every model call must deterministically project the session working set under the current provider request path's resolved limit.
- Tools outside a smaller prepared-call projection remain searchable and can be promoted by Tool Search, displacing older visible deferred tools according to the shared recency order.

### search-260717/ADR-D2. Treat the tool declaration limit as an optional request compatibility exception; default to unlimited

A maximum tool declaration count is not assumed to be a universal model capability. Before every prepared model call, Azents resolves an optional explicit limit from the current provider-request compatibility policy described in search-260717/ADR-D9. An absent resolved value means unlimited and does not trigger count-based truncation.

Known request-path constraints may set an explicit limit, such as 200 for applicable xAI requests. Applicable Vertex AI request paths for Google/Gemini models use a conservative 128 declaration ceiling while Google's official 128-versus-512 documentation conflict remains unresolved. Direct Gemini API requests have no explicit rule until an authoritative hard limit is verified, and Vertex-hosted non-Google models do not inherit the Google/Gemini rule. Azents will not apply a conservative global fallback and will not introduce a product-wide soft limit in this decision.

For a model call with no explicit resolved limit, the provider-facing set consists of all pinned direct tools plus the complete active deferred-tool working set. Tool Search still reduces the normal catalog because unactivated deferred tools remain hidden, but Azents does not evict or truncate active tools solely due to an assumed limit.

Rationale:

- Tool-count limits are provider request compatibility exceptions rather than a common contract shared by every model.
- The same upstream model family may have different request contracts through a direct provider API, Bedrock, Vertex AI, or another lowering path.
- An invented fallback could unnecessarily hide capabilities on models without such a constraint.
- Provider compatibility data should describe verified behavior rather than encode an arbitrary platform policy.

### search-260717/ADR-D3. Keep core execution tools direct and make attached service tools deferred

Azents will treat its core execution and session-control capabilities as pinned direct tools. These include Tool Search itself, shell and file operations, Goal, Todo, Memory, subagent/task control, and other auto-bound tools required to operate the session without first discovering basic capabilities.

Tools supplied by attached external-service Toolkits are deferred by default. This includes generic MCP and service-oriented Toolkit operations such as GitHub, GCP, AWS, Sentry, Notion, Kubernetes, and Google Analytics. Toolkit-specific control capabilities that are required to select or recover the attached integration may be explicitly classified as direct, while the service operation catalog remains deferred.

Pinned direct tools are never LRU eviction candidates. If their count alone exceeds the current provider request path's explicit resolved limit, Azents will fail model-call preparation with a clear compatibility error instead of silently removing direct tools. The error must be raised before sending an invalid provider request.

Rationale:

- Shell, file, session state, and delegation capabilities form the agent's basic execution language and should not require a discovery round trip.
- External Toolkit catalogs are the primary source of tool-count growth and are well suited to metadata search.
- Silently dropping a direct tool would violate its availability contract and make agent behavior model-dependent in an opaque way.

### search-260717/ADR-D4. Automatically activate a small ranked result set and update shared session recency

A `tool_search` call will both search and activate its returned tools. Azents will not require a separate load step.

The search input supports an optional result limit with a default of 5 and a maximum of 10. Matching tools are ranked deterministically. The activated results are moved to the front of the shared session recency order while preserving search relevance order, with the highest-ranked result most recent. Searching for an already-active tool refreshes its recency.

Actual invocation of a deferred tool moves that tool to the most-recent position regardless of whether the invocation succeeds or returns a tool-level error. The invocation itself is evidence that the capability remains relevant to the current conversation.

For a model call with an explicit resolved tool declaration limit, the maximum activatable result count is also bounded by the total deferred capacity remaining after pinned direct tools. When fewer results can fit than requested, Azents activates and returns only the highest-ranked results that can be made model-visible on the immediately following call. The tool result reports that the provider request limit reduced the activated count.

Rationale:

- Related workflows commonly require more than one service operation, such as creating an issue and then applying labels.
- A separate `load_tools` call would add latency and create another failure mode in which the model discovers a capability but forgets to load it.
- A small default and hard search-result maximum bound working-set churn without forcing one-result-at-a-time discovery.

### search-260717/ADR-D5. Persist final model-visible tool names in session-bound Toolkit State

Azents will persist the Tool Search working set through the existing session-bound Toolkit State infrastructure. The state stores only an ordered list of activated final model-visible tool names and the minimal version metadata needed for safe decoding. It does not duplicate tool descriptions, input schemas, handlers, or MCP snapshots.

Each model-call preparation reconciles the persisted names against the current executable Tool Catalog. A currently available name uses the current catalog's schema and handler. A currently absent name is skipped for that projection but remains in the session recency list so a tool that returns in a later Run can recover its prior position. A schema or handler change under the same final name retains activation and uses the latest catalog entry.

A prepared model call snapshots the reconciled executable catalog, deferred search index, provider-visible projection, and executor routing as one immutable call boundary. Tool calls emitted by that model response resolve only against the snapshot whose schemas were shown to the model. Catalog, model, hosted-tool, or compatibility-policy changes are incorporated when the next model call is prepared and must not partially mutate an in-flight call.

Tool Search activation and actual deferred-tool invocation update the session-bound recency state atomically. The state survives AgentRun boundaries, worker restart, session-owner handoff, compaction, and archive/unarchive according to the normal session Toolkit State lifecycle.

Rationale:

- `FunctionTool` and `ToolCatalog` currently have no separate stable tool identity contract; the final model-visible name is the existing routing and execution key.
- Toolkit slug prefixing and installation-specific internal prefixes already make attached Toolkit tool names unique in the model-visible catalog.
- The selected scope is the session, so process-local runner state does not provide the required lifecycle.
- Transcript reconstruction would make compaction and runtime projection state unnecessarily coupled.
- Current tool catalogs and MCP snapshots remain the source of truth for executable schemas; the working set only records activation and recency.

### search-260717/ADR-D6. Build a deterministic in-memory BM25 index from the current deferred catalog

Tool Search will index only deferred tools from the current executable Tool Catalog. It will not search a separate workspace-global or Toolkit-global database index.

Each search document includes the final model-visible tool name and tokenized name segments, Toolkit slug/type/display name, tool description, parameter names and descriptions, and available routing metadata such as installation account identity. Search result ordering uses BM25 relevance with final model-visible tool name as the deterministic tie-breaker.

Azents may cache the in-memory index by a deterministic deferred-catalog metadata hash. When the current executable catalog's searchable metadata changes, the cache is invalidated and the index is rebuilt. New tools become searchable, removed tools disappear, and updated descriptions or schemas are reflected without a separate synchronization protocol.

The Tool Search description will instruct the model to translate the user's intent into a concise capability query when needed. Embedding or vector search is not part of the initial design.

Rationale:

- The executable catalog already incorporates current authentication, Toolkit configuration, MCP snapshots, routing prefixes, and session-specific availability.
- A persisted global index could return tools that the current session cannot execute and would create another consistency boundary.
- The expected catalog size is small enough for local lexical indexing, while BM25 remains deterministic and operationally simple.

### search-260717/ADR-D7. Keep the Tool Search schema description generic and stable

The `tool_search` tool will use a fixed generic description. It will not dynamically embed the list of searchable Toolkits, sources, installations, or tool counts in its schema.

Azents already communicates attached Toolkit identities and stable capability instructions through Toolkit system-prompt fragments. The model uses that existing context to decide whether Tool Search is relevant, then searches the current deferred catalog with a capability query.

Rationale:

- Repeating the Toolkit list in the Tool Search schema would duplicate existing system-prompt context.
- A fixed schema avoids an additional prompt-cache boundary when searchable source details change.
- Individual tool metadata remains deferred and is only returned through an explicit search.

### search-260717/ADR-D8. Apply limits to the final provider-counted tool declarations

An explicit resolved tool declaration limit applies according to the selected provider's request semantics, not blindly to the client function catalog alone.

The common Tool Search projection owns session recency, direct/deferred classification, and deferred membership. Before projection, the provider lowering policy reports how many enabled provider-hosted tools consume the same declared-tool limit. The effective client-function budget is:

```text
resolved tool declaration limit
- provider-counted hosted tool declarations
```

Pinned direct function tools consume this effective budget first, and the remaining slots are filled from the session working set in MRU order. When the provider request path has no explicit resolved limit, no count-based projection is applied.

Provider-hosted tools that do not count toward a provider's documented function-declaration limit reserve zero slots. Provider adapters must not independently perform LRU selection or silently truncate client tools.

Rationale:

- Provider limits differ in what they count; Gemini documents a function-declaration limit while other providers may describe a total tools-per-request limit.
- Ignoring counted hosted tools can still produce an invalid request after client tools have been capped.
- Keeping membership policy in the common engine prevents provider-specific working-set behavior.

### search-260717/ADR-D9. Resolve verified limits from a versioned provider-request compatibility registry

Azents will maintain verified tool declaration limits in a code-owned, versioned provider-request compatibility registry. It will not scrape provider documentation at runtime, depend on a universal model-listing field, or introduce mutable Admin configuration for the initial implementation.

A compatibility rule identifies the request path precisely enough to avoid applying a model-developer-wide assumption. Its match dimensions include the Azents provider, lowering target or provider API mode, and an exact runtime model identifier or a documented model-family matcher. Each rule also records the maximum declaration count, the provider counting scope, a stable rule identifier, the authoritative documentation source, and the verification date.

Rule matching uses deterministic specificity: an exact runtime model match takes precedence over a model-family rule, which takes precedence over a documented endpoint-wide rule. Conflicting rules at the same specificity are invalid configuration and must fail validation rather than selecting one by incidental declaration order.

Model-call preparation constructs an explicit normalized compatibility key containing the provider, lowering target or provider API mode, runtime model identifier, and normalized family information required by the registered matchers. The registry consumes this key and does not infer request semantics from model-developer names, credential configuration, or incidental string prefixes inside provider adapters.

Before each model call is prepared, Azents resolves the effective rule from the current request's provider, lowering mode, and runtime model identifier. The deployed compatibility registry is the runtime authority, so an older `AgentModelSelection` capability snapshot cannot freeze a stale hard limit. This call-time authority supersedes [catalog-260620/ADR-D13](./catalog-260620-catalog-projection-sync.md) only for the effective tool declaration limit as a transport compatibility constraint; all other normalized model capabilities retain the existing saved-snapshot semantics. If a provider model-listing source later supplies an explicit, semantically equivalent maximum declaration count, the normalized value may be retained as catalog metadata and used only when no registry rule matches. Unverified or ambiguous source fields are ignored. If neither source supplies a verified value, the effective limit remains absent and search-260717/ADR-D2's unlimited behavior applies.

Compatibility rule changes require a reviewed code change that cites authoritative provider documentation and updates exact, family, endpoint, precedence, counting-scope, and unknown-limit tests. Runtime provider failures must not automatically learn or persist a new limit. Observability records the matched rule identifier and effective count so operators can diagnose stale or incorrect compatibility data without exposing provider credentials or request contents.

The initial registry policy includes xAI's documented 200-tools request limit and a conservative 128-declaration rule only for Vertex AI request paths targeting Google/Gemini models. The Vertex rule records the conflicting 128 and 512 official sources and the 2026-07-19 verification date. Direct Gemini API requests remain unmatched and therefore unlimited until a hard limit is officially verified. Vertex-hosted Anthropic and other non-Google model request paths are excluded from the Vertex Google/Gemini rule.

Rationale:

- Current provider listing APIs and LiteLLM capability metadata do not expose a reliable cross-provider maximum tool declaration field.
- Tool limits are hard request compatibility constraints and must follow the current provider request contract rather than remain frozen in a model selection snapshot.
- A code-owned registry makes documentation provenance, review, rollout, and rollback explicit.
- Runtime scraping or mutable configuration would add availability and safety risks to every model call.

### search-260717/ADR-D10. Make Tool Search an Agent-level opt-in setting that defaults to disabled

Each Agent stores a `tool_search_enabled` boolean setting. New and existing Agents default to `false`. Agent administrators can enable or disable the setting through the Agent settings API and UI.

When `tool_search_enabled` is `false`, Azents preserves the pre-search-260717/ADR runtime behavior: the complete executable client-tool catalog is model-visible in canonical final-name order, no `tool_search` function is injected, attached service tools are not deferred, and the compatibility registry does not truncate or reject the catalog. Existing session working-set state may remain stored but is ignored while the feature is disabled.

When `tool_search_enabled` is `true`, the direct/deferred classification, pinned Tool Search function, compatibility-budget projection, search activation, and session-shared recency rules in this ADR apply. Toggling the setting takes effect when the next Agent run resolves its immutable Agent snapshot. Re-enabling the feature may reuse valid session working-set names retained by the normal Toolkit State lifecycle.

The setting belongs to the Agent rather than an individual selectable model because the working set is shared by the Agent session across model changes. It is not a workspace-wide or provider-wide rollout switch.

Rationale:

- Tool Search changes which capabilities are initially visible to the model and therefore requires explicit administrator intent during rollout.
- Default-disabled persistence preserves existing Agent behavior and avoids silently changing established workflows.
- Agent scope matches the existing session-shared working-set decision; model-scoped toggles would create conflicting behavior inside one session.
- Keeping disabled mode as a true legacy path makes the rollout reversible without deleting session state.

## Current Direction

The design now uses an Agent-level opt-in setting and, when enabled, a session-scoped bounded working set with prepared-call provider-request projection limits:

- `tool_search_enabled` defaults to `false`; disabled Agents keep the complete legacy model-visible catalog and do not receive `tool_search` or budget projection.
- Enabled Agents apply the remaining Tool Search decisions below.
- Direct tools are pinned and always consume the model-visible budget.
- `tool_search` is a pinned direct tool.
- Deferred tools remain executable catalog entries but are not model-visible until activated.
- Tool Search activates ranked matches for the next model call and updates the shared session recency order.
- The current provider request path's compatibility-registry limit determines how much of that shared working set is projected into the provider request.
- A registry rule matches provider, lowering mode, and runtime model identity with deterministic exact, family, then endpoint specificity.
- Current deployed compatibility rules override stale saved model capability snapshots; verified provider-reported counts are fallback metadata only.
- Actual tool invocation refreshes shared session recency.
- Final visible schemas remain canonically sorted by model-visible tool name; LRU affects membership and projection, not provider-facing order.

All decision topics are resolved. The remaining work is design validation and implementation planning.

## Migration provenance

- Historical source filename: `0147-tool-search-bounded-working-set.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
