---
title: "Tool discovery and working sets"
created: 2026-11-04
tags: [wiki]
---

# Tool discovery and working sets

Owns model-visible names, MCP snapshot lifecycle, tool search and bounded exposure. Connection ownership and runtime network policy are distinct from deciding which tool definitions a model sees.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Toolkits](../domain/toolkit.md)
- [MCP OAuth](../flow/mcp-oauth.md)
- [Toolkit State and execution binding](../execution/tool-state.md)
- [Request capabilities and built-in tools](../models/request-capabilities.md)

## Tool Name Prefixing

ToolkitConfig `slug` is the administrator-visible, non-unique base alias. One Agent+Toolkit namespace reservation owns the effective outer tool-name prefix. The first allocation for a base Slug uses the base unchanged; later allocations use `_2`, `_3`, and increasing monotonic ordinals. Candidate collisions with already reserved namespaces consume the next ordinal instead of reassigning an old name.

`resolve_agent_tools()` resolves the canonical effective relation into `ToolkitBinding` records that carry both stored `slug` and `effective_namespace`, with `use_prefix=True`. During `build_tool_catalog()`, every `FunctionTool` returned by an enabled binding is renamed with `tool.with_prefix(f"{effective_namespace}__")` when `use_prefix=True`. The final model-visible name is therefore:

```text
{effective_namespace}__{tool_name}
```

Catalog construction rejects duplicate final names before publication and reports both source ToolkitConfig IDs; dictionary overwrite is never collision handling. The catalog source retains ToolkitConfig ID, Type, persisted Name, base Slug, effective namespace, revision, and a bounded allowlisted non-secret connection identity. Tool Search, executor routing, runtime hooks, durable source snapshots, and activity projections consume that exact selected source rather than parsing the final name.

Auto-bound single-instance toolkits use `use_prefix=False`; names are exposed as-is.
This includes Saved Memory writes, generic readable-storage tools, Runtime mutation/
process tools, Subagent collaboration, and Session Goal/Todo tools. For example,
`save_memory`, `delete_memory`, `read`, `grep`, `glob`, `exec_command`,
`write_stdin`, `run_tool_to_file`, `spawn_agent`, `wait`, `get_goal`, and
`update_todo` are not prefixed. Memory context is a prompt-only binding.

Some toolkits may add their own internal segment before the outer effective namespace is applied. GitHub multi-installation routing does this by prefixing each installation's MCP tools with a safe account-login segment. With effective namespace `github`, installation `azents`, and MCP tool `get_file_contents`, the final model-visible name becomes:

```text
github__azents__get_file_contents
```

The effective prefix is only a tool-call namespace. Toolkit State uses its own `toolkit_namespace` field and is not derived automatically from the model-visible tool name.

Toolkit State identity and payload models are pure core types. Database handles
and optimistic compare-and-set storage live in the repository layer. Goal and
Skill owners expose completed typed repository operations; application callers do
not pass arbitrary mutation callbacks into a live repository transaction. Goal
clear, objective changes, create, and status transitions retain their existing
validation and event behavior. Skill Project invalidation composes through its
passed-session database primitive when a Project mutation must remain atomic.

Final provider-facing client tools are canonicalized by model-visible tool name before lowering to the model request. Toolkit-local generation may use whatever construction order is convenient, but `ToolCatalog.native_tools` is name-sorted so identical toolkit configuration and identical successful toolkit state produce stable function-tool ordering. Provider-hosted tools are also sorted by stable semantic name/config before request lowering when more than one hosted tool is present.

One logical catalog entry may declare multiple provider wire variants while preserving its final
model-visible name, catalog identity, source metadata, Tool Search identity, and executor lookup.
`FunctionTool` owns the immutable variant declarations and optional guidance for each dialect.
Ordinary tools implicitly declare one JSON-function variant.

Prepared-call selection is generic. A semantic model-profile registry determines eligibility, an
adapter-profile registry supplies the ordinary default dialect preference plus any semantic-profile
override, and catalog projection chooses the first matching tool-declared variant. Selection never
branches on the model-visible tool name. The selected declaration, guidance, handler route, and
durable dialect are frozen together. Variant guidance is included only when the matching declaration
is provider-visible after Tool Search projection.

Candidate catalog construction records tool declarations without selecting a wire dialect.
Provider declaration lowering and execution require a prepared catalog produced by compatibility
projection. Internal post-projection extensions are validated as unconditional JSON-function
variants before they are added. The current extensions are `run_tool_to_file` when Runtime
authority is available and `tool_search` when deferred entries require search.

The current dual-variant entry is `apply_patch`. It requires the reviewed V4A patch semantic profile
and declares JSON-function and plaintext-custom variants. Native OpenAI Responses prefers plaintext
custom, while the reviewed OpenRouter Pydantic AI Responses profile selects JSON function. Other
Pydantic AI model-message routes keep ordinary JSON tools but do not enable the V4A patch semantic profile. A prepared
catalog exposes one variant, never both, and Tool Search/declaration-budget projection counts that
selected declaration once.

## MCP Tool Snapshot Lifecycle

MCP-backed toolkits must keep `list_tools` discovery off the normal run preparation critical path.

- Active Toolkit bindings retain their own MCP SDK sessions per target, transport,
  proxy and credential identity. Generic MCP, Notion, Sentry, GitHub installation
  bindings, AWS and GCP reuse those sessions; setup probes remain short-lived.
  No live session, secret or auth callback is persisted in the snapshot.
- A dedicated task owns each SDK context from entry through exit. Cold concurrent
  calls share initialization and one complete paginated tool listing, warming the
  SDK result-schema cache before execution. Up to 16 independent calls per
  connection are admitted, with readiness/capacity bounded by the call timeout.
- Authority and current credentials are checked per call and again after waits at
  dispatch. HTTP auth behavior and 401 observation are request-local; shared client
  defaults are not mutated. Credential rotation selects a new session and retires
  the old one. Different Toolkit/Session/installation bindings never share sessions.
  Dispatch admission denial performs no provider I/O and is handed back only to
  that request, preserving other callers on the shared SDK transport. Streamable
  HTTP uses a correlated local non-success response; legacy SSE's writer requires
  local 202 acknowledgment plus cancellation/error handoff to the exact operation.
  The tool caller always receives the original denial, never synthetic success.
- Confirmed unusable sessions/transports are discarded for later operations.
  Request-local admission, timeout, argument/result validation, and ordinary
  tool errors do not retire a healthy shared session or poison queued siblings.
  A failed or uncertain
  `tools/call` is not automatically replayed; existing explicit provider 401
  refresh remains separate from connection recovery. Single-call cancellation
  does not terminate unrelated operations or the shared connection.
- Recent successful listings are reused for 300 seconds. Supported
  `notifications/tools/list_changed` marks a connection stale; the next
  context refresh or call refreshes its complete listing with single-flight
  serialization. Refresh failure retains the previous durable snapshot.
- Toolkit removal/replacement and SessionRunner teardown stop admission, cancel
  and boundedly drain operations, then close the SDK session/transport (including
  DELETE when supported). Cleanup waits at most 10 seconds before cancelling a
  remaining owner task and reporting the deadline. Worker restart prepares fresh
  sessions rather than restoring live connections from metadata.
- Toolkit teardown distinguishes an owned discovery task's cancellation from
  cancellation of the teardown caller. When connection cleanup succeeds, caller
  cancellation propagates; GitHub installation bindings each receive cleanup
  even when another binding's teardown is interrupted.
- `update_context()` reads the latest successful session-bound Toolkit State snapshot and returns immediately.
- If no successful snapshot exists, the toolkit exposes no MCP tools.
- Background refresh lists tools, sorts them deterministically, builds a complete serializable snapshot, then atomically replaces the stored snapshot.
- Discovery retries HTTP 429 and MCP `Too many requests` failures up to three times with 1s/2s/4s backoff when no numeric `Retry-After` is provided. Numeric delays up to 60s are honored; invalid or longer delays stop the attempt rather than retrying early. Nested groups are retryable only when every leaf is throttling. This read-only retry boundary does not replay tool execution.
- Exhausted discovery throttling retains an actionable internal error and a sanitized warning with traceback; unrelated connection failures remain errors and cancellation propagates.
- Explicit MCP connection tests return a generic failed result for an MCP protocol
  error or a group containing only MCP protocol errors, without exposing provider
  details. Mixed protocol and internal failures propagate; cancellation is preserved.
- Refresh failure keeps the previous successful snapshot unchanged. If there is no previous snapshot, no tools are exposed.
- Loading, retry, setup, and status pseudo-tools are not model-visible MCP availability controls.
- MCP loading/error text is not injected into Toolkit prompts.
- Generic MCP, Notion, and Sentry use the common MCP snapshot lifecycle. AWS, GCP, and GitHub MCP wrapper paths follow the same non-blocking/no-loading-prompt exposure contract and sort component/tool output deterministically.

Snapshot payload stores only serializable tool metadata needed to rebuild model-visible wrappers, including raw MCP name, model-visible name, description, input schema, server URL, transport mode, loaded timestamp, and a stable tool hash. Runtime-only objects such as background tasks, auth callbacks, SigV4 auth, token providers, and artifact sinks stay in process memory.

GitHub multi-installation bindings must expose cached installation MCP tools even before the lazy concrete `McpToolkit` for that installation has finished preparing. A binding that already has target metadata, `agent_id`, `session_id`, and an installation-specific MCP snapshot state name has enough information to read a previous successful snapshot from Toolkit State. Reconstructing model-visible specs from that snapshot must not require installation token exchange.

Snapshot-backed GitHub tool handlers resolve installation authorization at execution time. They call the installation token provider only when the model calls a tool, and they preserve the same auth-failure retry path as live MCP-backed tools. This keeps first-turn provider-facing schemas stable when an installation snapshot exists, while avoiding token issuance work during normal run preparation.

## Model-Visible Tool Exposure and Search

Kubernetes `k8s_exec` normalizes the WebSocket client result before exposing it
to the model. A native string is returned unchanged, `WsResponse.data` bytes are
decoded as UTF-8, non-byte `WsResponse.data` and other response objects are
stringified, and an empty normalized value returns
`Command completed with no output.`. Command output therefore does not expose a
Python bytes representation.

Each Agent stores a persisted `tool_search_enabled` setting that defaults to `true` when a new Agent is created and is managed from the Agent Capabilities API/UI. Existing Agents retain their stored value; setting the field to `false` is an explicit opt-out. When disabled, the complete executable client-tool catalog remains model-visible in canonical final-name order. The engine does not inject `tool_search`, defer attached service operations, apply compatibility-budget projection, or update Tool Search working-set recency.

When `tool_search_enabled` is enabled, the executable Tool Catalog retains every currently available client function with its final model-visible name, current schema and handler, Toolkit source metadata, and an exposure class. The final name is both the executor routing key and the persisted working-set identity.

For each DB-attached catalog entry, the catalog source retains the ToolkitConfig ID, type, display name, and slug independently of the final model-visible name. When the model invokes that entry, the engine snapshots those source facts onto the durable `client_tool_call` and the matching active/live client-tool projection. UI consumers use this snapshot for product identity and must not infer Toolkit ownership from a tool-name prefix. Built-in and auto-bound entries have no ToolkitConfig source snapshot.

Auto-bound core execution and session-control capabilities are direct and remain pinned in every prepared model call. DB-attached service Toolkit operations are deferred by default, including MCP, GitHub, GCP, AWS, Sentry, Notion, Kubernetes, and Google Analytics operations. A service control tool required to operate its integration may be explicitly direct; the current registered exception is GitHub `switch_installation`.

Each ToolkitConfig also stores an `always_expose_tools` boolean that defaults to
`false`. Workspace managers can change it through the common Toolkit create/edit API
and UI. When Tool Search is enabled and the value is `true`, every executable tool
from that attached ToolkitConfig is classified as direct, remains model-visible on
every prepared call, and is excluded from lexical deferred search. Exact-name
lookup can still identify it as already available. The policy
applies to all Agents attached to that ToolkitConfig and to future tools produced by
its current runtime snapshot. Directly exposed tools continue to count against the
existing pinned declaration compatibility budget. When the value is `false`, the
normal deferred classification and explicit platform exceptions apply.

The auto-bound External Channel `channel_action` and `download_external_file`
capabilities are deferred while Tool Search is enabled. The active External
Channel Toolkit keeps a minimal static publication-boundary prompt visible before
discovery. It scopes that boundary to the current input explicitly marked as an
External Channel turn or continuation and tells the model to use Tool Search only
when the capability is enabled. When Tool Search is disabled, the complete catalog
remains directly visible and the static prompt omits the search instruction.

When at least one deferred tool exists, the engine adds the unprefixed direct
`tool_search` function. Its stable description explains discovery, next-call
activation and ranked rather than exhaustive results. The `query` accepts an
exact tool name or short English service/action/object keywords. The optional
`limit` defaults to 5 and has a maximum of 10.

Lookup first checks the trimmed, case-sensitive final name against the current
authorized, model-compatible catalog, then the explicitly retained original
operation name. A unique deferred match bypasses lexical ranking but retains
the activation budget. An exact direct match returns `already_available_tools`
without activating it or changing recency, even with zero deferred capacity.
Multiple original-name matches return bounded `ambiguous_tools`, the
`total_exact_matches` count and a final-name selection hint; they do not
arbitrarily activate a source when the result limit is small.

Queries without an exact match use deterministic in-memory BM25 over the current
deferred catalog. Documents include final-name tokens, Toolkit slug/type/class/
display name, description, parameter names and descriptions, and routing metadata.
Positive-score results are ordered by relevance and then final name. Exact lookup
does not search unavailable tools, infer prefixes or introduce filter syntax.

Calling `tool_search` activates the returned names for the immediately following prepared model call. Search activation moves results to the front of shared recency in relevance order; searching for an already-active tool refreshes it. Invoking a deferred tool also moves it to the most-recent position before runtime-hook denial, handler execution, or tool-level failure, because invocation itself is the relevance signal.

The working set is session-bound Toolkit State with identity `tool_search/working_set`. Its versioned payload stores only an ordered most-recent-first list of final tool names; it does not copy descriptions, schemas, handlers, or MCP snapshots. Updates use the existing optimistic-lock retry contract. A missing name is skipped while unavailable but remains in recency state. If that final name returns, or its schema/handler changes, the current executable catalog entry is used without losing activation. The state survives model turns, AgentRuns, worker handoff/restart, and archive/unarchive until a successful context compaction. Manual and automatic compaction replace its `tool_names` with an empty list in the same transaction that appends the summary and moves the model-input head, regardless of the current Agent opt-in value. Skipped, failed, cancelled, or stale compaction leaves the working set unchanged. Other Session Toolkit State is not reset.

Tool Search does not replace Toolkit attachment, credential validation, or MCP discovery. MCP-backed availability continues to come only from the latest successful session snapshot described above; Tool Search indexes the executable catalog produced from that snapshot and never performs `list_tools` on the model-call critical path.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/core/mcp_connections.py`](../../../../python/apps/azents/src/azents/core/mcp_connections.py)
- [`python/apps/azents/src/azents/core/mcp_transport.py`](../../../../python/apps/azents/src/azents/core/mcp_transport.py)
- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
