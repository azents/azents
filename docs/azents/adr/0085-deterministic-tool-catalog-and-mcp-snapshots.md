---
title: "ADR-0085: Deterministic Tool Catalog, MCP Tool Snapshots, and Stable Toolkit Prompts"
created: 2026-06-28
tags: [architecture, backend, engine, toolkit, mcp, llm]
---
# ADR-0085: Deterministic Tool Catalog, MCP Tool Snapshots, and Stable Toolkit Prompts

## Context

Azents sends model-visible tools through the Responses API top-level `tools` field. This is distinct from Codex's internal `additional_tools` input item used by its Responses Lite path. `additional_tools` does not solve cache instability by itself: changing any model-visible tool schema or order still changes the provider-facing request prefix.

The current optimization problem is that Azents' model-visible tool catalog can be non-deterministic even when the user-facing toolkit configuration has not changed. Provider prompt caches are sensitive to tool schema and order, so the same session can lose cache locality when the tool array changes unnecessarily.

Known instability sources include:

- MCP-based toolkits returning tools in external server order.
- MCP tool discovery completing after the first run has already started.
- MCP loading/error states changing model-visible tools, such as exposing a retry tool.
- GitHub multi-installation MCP tools becoming available at different times.
- Goal or Todo tools regressing into state-dependent visibility.
- Provider-hosted tools preserving upstream order when multiple hosted tools are present.
- Final `ToolCatalog.native_tools` preserving upstream insertion order rather than applying a canonical order.
- Toolkit prompts embedding transient state such as MCP loading/error state, current Goal state, or current Todo list.

A previous Azents implementation waited for MCP tool lists on every user input. That made runs very slow, with responses delayed by more than a minute when MCP servers were slow or unstable. MCP server availability must therefore not become a synchronous dependency for normal run startup.

System prompt stability matters for the same cache locality reason as tool schema stability. Azents assembles model instructions from the agent prompt, toolkit prompt fragments, and turn-injected hook prompts. The agent prompt and configuration-derived toolkit prompts are expected to change when configuration changes. Transient toolkit state should not be injected into the system prompt unless it is deliberately part of the agent instruction model.

## Research notes

### Codex

Codex starts MCP clients asynchronously, but its general MCP tool build path awaits the managed client when no cached tool list exists. It also supports required MCP servers and validates those during session initialization.

Codex applies strong deterministic normalization before model exposure:

- MCP tools are normalized from raw server/tool identity into model-visible names.
- Name collisions are resolved with deterministic hash suffixes.
- Tool candidates are sorted by raw identity before being exposed.
- Namespace tools are sorted by function name.
- Codex Apps can use cached tools while startup is still in progress or after startup failure.

This is useful evidence for canonical ordering and snapshot fallback, but Codex's blocking behavior is not directly suitable for Azents because Azents previously observed unacceptable latency when waiting for MCP list calls on input handling.

### opencode

opencode connects MCP servers and stores listed tool definitions in process state. It updates the stored definitions when the MCP server emits a tool-list-changed notification.

Before sending an LLM request, opencode sorts the final tool object by tool name:

```ts
tools: Object.fromEntries(
  Object.entries(tools).toSorted(([a], [b]) => a.localeCompare(b))
)
```

This provides a simple and relevant precedent for Azents: even if upstream tool construction order varies, the provider-facing tool catalog should be canonicalized at the final request boundary.

## Decision

### ADR-0085-D1. Canonicalize provider-facing tool order

Azents will make the final model-visible tool list deterministic. The provider-facing `native_tools` array must be sorted by a stable key, initially `tool.spec.name`.

Toolkit-level tool generation should also avoid relying on external ordering. MCP-derived tools should be sorted before snapshotting and wrapping. Multi-source toolkits, such as GitHub multi-installation and GCP multi-service toolkits, should use explicit deterministic ordering for source groups and raw tool names.

Configuration-dependent tool differences are acceptable. For example, Kubernetes read/write mode, enabled GCP services, enabled GitHub toolsets, attached toolkits, and runtime tools enabled/disabled may change the tool catalog. The requirement is that the same configuration snapshot and loaded toolkit state produce the same provider-facing tool list.

### ADR-0085-D2. Keep MCP tool discovery off the run critical path

Azents will not wait synchronously for MCP `list_tools` during normal LLM request preparation.

MCP servers are external dependencies and may be slow or unstable. A slow MCP server must not delay ordinary user input processing or make Azents appear unavailable. This intentionally differs from Codex's general MCP await path and preserves Azents' lazy-loading direction.

### ADR-0085-D3. Store MCP tool snapshots in Azents Toolkit State

MCP tool catalogs will be stored as session-bound Toolkit State using the existing `ToolkitStateStore` / `ToolkitStateHandle` abstraction.

The MCP toolkit's model-visible tools are derived from the latest successful snapshot stored in Toolkit State, not directly from live MCP server state during `update_context()`.

A snapshot should contain enough data to reconstruct model-visible tool specs and route tool calls to the raw MCP tool, including at least:

- raw MCP tool name;
- model-visible tool name;
- description;
- input schema;
- relevant server/toolkit identity or config hash needed for validation and routing;
- snapshot metadata such as schema version, loaded timestamp, and tool hash.

The exact payload schema is an implementation detail, but partial snapshots must not be exposed.

### ADR-0085-D4. Use background refresh with atomic snapshot replacement

MCP `list_tools` refresh runs in the background. `update_context()` reads the current Toolkit State snapshot and returns immediately.

Refresh policy:

- If no snapshot exists, expose no MCP tools.
- If a snapshot exists, expose that snapshot immediately.
- Start or continue background refresh when appropriate.
- On refresh success, build the complete deterministic tool snapshot and replace the stored snapshot once.
- On refresh failure, keep the previous successful snapshot unchanged.
- Do not expose intermediate or partially loaded MCP tool lists.

This gives stale-while-revalidate behavior: model-visible tools are stable in steady state, while background refresh can eventually replace the snapshot after a complete successful discovery.

### ADR-0085-D5. Do not expose MCP loading, retry, or status pseudo-tools

Azents will not add model-visible retry/status/setup tools solely to represent MCP loading or discovery failure.

If the initial MCP snapshot is absent, the MCP toolkit exposes no tools. If refresh later succeeds, the next catalog build can expose the stored snapshot. If refresh fails and a previous snapshot exists, the old snapshot remains visible; if no previous snapshot exists, no MCP tools are visible.

Retry is an internal background refresh concern, not a model-visible capability. This avoids low-value tool calls and prevents loading/error states from changing the tool catalog.

### ADR-0085-D6. Keep Goal and Todo tools model-visible regardless of stored state

Goal toolkit tools should remain model-visible regardless of the current goal state. State-specific behavior should be handled by tool execution and prompt text, not by adding/removing goal tools from the catalog.

Todo toolkit tools should likewise remain model-visible regardless of whether the current todo list is empty or populated. Todo state may change the prompt fragment and UI snapshot, but it must not change the tool definition set.

This keeps the provider-facing tool list stable across normal Goal/Todo state transitions.

### ADR-0085-D7. Sort provider-hosted tools when multiple hosted tools are present

Provider-hosted tools, such as hosted web search, are lowered separately from client-executed function tools. They are configuration/model dependent, so their presence may legitimately change when the run's model or configured builtin tools change.

When multiple hosted tools are present, Azents should apply a deterministic order before sending the provider request. For the current optimization scope, only ordering is in scope; no behavior change is required for provider-hosted tool selection.

### ADR-0085-D8. Apply the snapshot lifecycle to all MCP-backed toolkits

The MCP snapshot policy applies to every toolkit whose model-visible tools are derived from MCP `list_tools`, not only to the generic MCP toolkit implementation.

Toolkits that simply specialize authentication or filtering should use the common MCP snapshot implementation directly. Dedicated wrapper toolkits, such as GCP, AWS, GitHub, Sentry, or Notion when they do not directly inherit the generic lifecycle, must still follow the same lifecycle contract:

- `update_context()` reads only the latest successful Toolkit State snapshot and does not await live MCP discovery.
- Initial missing snapshot exposes no tools.
- Refresh runs in the background.
- Refresh success replaces the stored snapshot once, after a complete deterministic snapshot is built.
- Refresh failure keeps the previous successful snapshot unchanged.
- Loading, retry, and status pseudo-tools are not exposed to the model.

Wrapper payload schemas may be toolkit-specific. Multi-source wrappers should use component-based snapshots where useful. For example, GCP may store one component per service, and GitHub may store one component per installation. A refresh may merge successful refreshed components with previous components for failed sources, then save the merged toolkit snapshot atomically once. Final exposure must flatten components in deterministic order.

### ADR-0085-D9. Keep Toolkit prompts stable and avoid transient state injection

Toolkit prompts should describe stable instructions, configuration, and constraints. They should not embed transient runtime state merely to inform the model that a toolkit is loading, failed, or currently has a particular stored state.

MCP loading/error state must not be injected into toolkit prompts. With snapshot-backed MCP tools, an absent snapshot simply means no MCP tools are exposed yet.

Goal and Todo toolkit prompts should be fixed instruction text. Current Goal state and current Todo list must not be injected into the system prompt for normal runs. The model can call the relevant tools when it needs current state, and Goal continuation already supplies follow-up execution when an active goal requires it. Re-injecting Goal state during compaction may be reconsidered later, but it is not part of this decision.

Future UI work may expose per-toolkit state directly to users instead of routing that state through the model system prompt.

### ADR-0085-D10. Return compact acknowledgements from state-update tools

State-update tools should avoid echoing large updated state payloads when the model does not need them.

In particular, `update_todo` should return a compact acknowledgement such as `Done` rather than echoing the full Todo list JSON. The stored Todo state and UI snapshot remain the source of truth for user-visible Todo state. This reduces redundant transcript growth and avoids feeding the same state back into the model unnecessarily.

Goal update/create tools may also use compact acknowledgement responses when the updated state is not needed for immediate reasoning, while `get_goal` remains available for explicit state retrieval.

### ADR-0085-D11. Keep Memory prompt injection as designed

Memory summaries and memory rules are intentionally injected through the system prompt. Memory changes may affect prompt-cache locality, and that is accepted for this decision because Memory prompt injection is part of the current product design.

### ADR-0085-D12. Treat configuration-derived Toolkit prompts as legitimate cache boundaries

Toolkit prompts derived from explicit configuration are allowed to change when configuration changes. Examples include GCP project/service configuration, Kubernetes cluster and read/write mode configuration, Google Analytics default property, runtime allowed/denied domains, and registered runtime projects.

These prompts should still be assembled deterministically. Lists inside configuration-derived prompts should use stable ordering when the underlying configuration does not intentionally define an order.

Large runtime/project context prompts are a separate topic and are intentionally left for a later discussion.

### ADR-0085-D14. Treat AGENTS.md as a `read` tool result appendix, not a Toolkit prompt

AGENTS.md instructions should not be injected through Toolkit prompt fragments. They are better modeled as an appendix to file observation results: when the agent reads a file, applicable AGENTS.md instructions for that file path are appended to the `read` tool result.

This keeps AGENTS.md content out of the stable system prompt and therefore out of the provider prompt-cache prefix. It also removes the need to store AGENTS.md contents in Toolkit State or refresh them in the background. AGENTS.md content is read fresh when it is appended, and any later AGENTS.md edits are represented by the agent's own file-edit tool results rather than by mutating previously provided instructions.

AGENTS.md discovery must not create or touch the runtime solely to discover `/workspace/agent/AGENTS.md`. Runtime use is triggered only by explicit runtime file tools. The root workspace AGENTS.md is an applicable candidate for read paths under `/workspace/agent`. Registered Project AGENTS.md files are applicable for read paths inside their registered project roots. Nested AGENTS.md candidates are discovered along the path from the applicable root to the target file's directory.

To keep behavior simple, Azents initially appends AGENTS.md instructions only to successful `read` tool results. Other file tools such as `write`, `edit`, `delete`, `grep`, `glob`, `import_file`, and `present_file` do not receive AGENTS.md appendices in this decision.

Dedupe is path-based and stored in session-bound Toolkit State. The state stores only paths that have already been appended; it does not store AGENTS.md contents. Session compaction clears this dedupe path set so applicable AGENTS.md files may be appended again after compaction.

The appendix should be appended after the original read result, using the same AGENTS.md content cap policy as existing AGENTS.md loading. It is acceptable to append after the original read result has already been output-capped because AGENTS.md content has its own cap and the appendix is expected to be small enough for this purpose.

### ADR-0085-D13. Remove legacy per-user GitHub PAT behavior outside this optimization scope

GitHub `per_user_pat` behavior is legacy and conflicts with the current toolkit-level integration direction. It should be removed rather than optimized. Per-user setup pseudo-tools should not remain as a model-visible path for GitHub toolkit availability.

This cleanup is not part of the immediate tool-catalog optimization scope because the path is not expected to be used.

## Consequences

### Positive

- MCP server latency no longer blocks normal run preparation.
- Slow or failing MCP servers are isolated from Azents' core run availability.
- Loaded MCP tool catalogs become stable across runs until a complete refresh succeeds.
- Provider prompt-cache locality improves because model-visible tool order is canonical.
- Retry/status pseudo-tools no longer pollute the model-visible tool list.
- Goal/Todo lifecycle changes no longer change the tool catalog or system prompt.
- Todo updates avoid echoing redundant Todo state into the transcript.

### Negative

- On a new session with no MCP snapshot, MCP tools are unavailable until background refresh succeeds.
- A stale snapshot may expose a tool that the MCP server later removed or changed. In that case, the tool call should fail as a tool-level observation and trigger/allow a future refresh; it must not destabilize the whole run.
- Persisting tool snapshots in Toolkit State introduces a schema and migration surface.
- Background refresh needs concurrency control and backoff to avoid repeatedly hitting unhealthy MCP servers.
- Removing current Goal/Todo state from the system prompt means the model must call `get_goal` or rely on tool results/continuations when it needs exact current state.

## Implementation notes

Initial implementation should prioritize:

1. Sort final provider-facing client-executed tools by tool name.
2. Sort provider-hosted tools when more than one hosted tool is present.
3. Sort MCP-derived tools before snapshotting/wrapping.
4. Store MCP successful snapshots in session-bound Toolkit State for generic MCP and MCP-backed wrapper toolkits.
5. Make MCP-backed `update_context()` implementations read snapshots without awaiting live MCP discovery.
6. Remove MCP retry/status pseudo-tool exposure.
7. Keep Goal/Todo tool definitions fixed across stored state changes.
8. Replace Goal/Todo dynamic state prompts with fixed instruction prompts.
9. Change `update_todo` to return a compact acknowledgement instead of the full Todo state JSON.
10. Move AGENTS.md injection from Toolkit prompts to successful `read` tool result appendices with Toolkit State path dedupe reset on compaction.
11. Add observability for `tool_count`, canonical `tool_names_hash`, full `tools_schema_hash`, `system_prompt_hash`, snapshot age, refresh outcome, and refresh duration.

The immediate non-MCP tool scope is intentionally narrow: final tool ordering, hosted-tool ordering, and regression coverage for Goal/Todo fixed tool definitions. Background task and subagent tool injection are known future redesign areas and are not part of this optimization pass.

The immediate system-prompt scope is also narrow: remove transient MCP status prompts, make Goal/Todo prompts fixed, keep Memory prompt injection as-is, and keep configuration-derived Toolkit prompts as legitimate cache boundaries. Project/root agent instruction prompts require separate discussion.

Refresh concurrency should avoid duplicate refreshes for the same session/toolkit. A process-local task guard may be sufficient for the first implementation, but Toolkit State metadata or a lightweight lease may be needed if multiple workers can refresh the same session toolkit concurrently.

## Alternatives

### Wait for MCP tools before every run

Rejected. Azents previously experienced more than one minute of run startup delay when MCP tool discovery was awaited on every input. This makes external MCP server health part of Azents' core availability and is not acceptable.

### Expose retry/status tools while MCP is loading

Rejected. These tools have low task value and make the model-visible tool list depend on transient loading/error state. Background refresh and observability should handle retry/status internally.

### Inject current Goal/Todo state into the system prompt

Rejected. Goal and Todo state changes are frequent and do not need to be part of the stable instruction prefix. The model can retrieve current Goal state through tools when needed, Todo state is available through the Todo UI/state store, and Goal continuation already handles active-goal follow-up. This can be revisited for compaction-specific recovery if evidence shows the state must be reintroduced after summarization.

### Echo complete Todo state from `update_todo`

Rejected. Echoing the full Todo list after every update adds redundant transcript content and can reintroduce unnecessary state churn. A compact acknowledgement is sufficient for the model after a successful state update.

### Keep snapshots only in toolkit instance memory

Rejected for the decision target. Instance memory can still hold non-serializable runtime details such as an in-flight refresh task, but the tool snapshot source of truth should be the existing session-bound Toolkit State abstraction so it survives toolkit instance reuse boundaries within the session design.

### Use Codex `additional_tools`

Rejected for this problem. Azents already passes tool schemas through the Responses API top-level `tools` field. Moving schemas into an `additional_tools` input item would not solve catalog instability and is not known to be a stable provider-compatible path for Azents' LiteLLM-based execution.
