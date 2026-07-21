---
title: "Adopt Toolkit Hooks and Toolkit State"
created: 2026-05-14
tags: [backend, engine, toolkit, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: toolkit-260514
historical_reconstruction: true
migration_source: "docs/azents/adr/0032-toolkit-hooks-for-agents-md.md"
---

# toolkit-260514/ADR: Adopt Toolkit Hooks and Toolkit State

## Context

The Session Workspace Project contract keeps `/home/sandbox` as the Agent's long-lived workspace and limits project-scoped active configuration discovery to registered Projects. `AGENTS.md` instruction loading must handle both root workspace instructions and Project-scoped instructions, and the system prompt for later turns must change depending on paths targeted by file tools.

The initial design considered creating a dedicated persistent store for AGENTS.md as S3 objects. However, AGENTS.md is only the first example of long-lived state storage needs required by Toolkit runtime. Future memory, policy, audit, and tool-specific caches will have the same lifecycle and identity problems. If we create an AGENTS.md-only store, runtime state source of truth becomes unclear across `runtime_state` blob, S3 objects, and Toolkit internal memory.

Also, in the current nointern runtime, Toolkit is already the execution boundary for tool bundle, prompt, credential, and runtime context. Introducing a separate arbitrary plugin runtime would require designing capability, isolation, versioning, and multi-tenant security together, which is too broad for the current need.

## Decision

Do not create a separate plugin runtime or AGENTS.md-only S3 store. Instead, add tool-call observation hooks and a generalized Toolkit State store to the existing Toolkit interface.

- `Toolkit.on_before_tool_call(...)`: called before nointern function tool handler execution.
- `Toolkit.on_after_tool_call(...)`: called after nointern function tool handler execution.
- Initial hooks are observation/state-update only. Tool deny, args mutation, and output mutation are out of scope for this decision.
- Hook failure is isolated fail-open. Cancellation is re-raised so normal cancellation can propagate.
- `update_context()` reads Toolkit State updated by hooks and reflects it in prompt assembly.
- Runtime provides common `ToolkitStateStore` and typed `ToolkitStateHandle[T]` abstractions.
- Python API is defined with generics + Pydantic models so state schema can be handled type-safely.
- A Toolkit can own multiple named states under one namespace.
- State identity is `scope + agent_runtime_id + optional session_id + toolkit_namespace + state_name`.
- Scope is not session-only; keep it general with `session` and `agent_runtime`.
- Backend is RDB table `toolkit_states`, not `agent_runtimes.runtime_state` blob or S3 object.
- `toolkit_states` rows store `state_json` JSONB, `schema_version`, `version`, and timestamps.
- Save uses whole-state replace + optimistic locking. The row `version` read by `load()` is used as expected version for low-level `save()`. Normal update path uses `ToolkitStateHandle.update()` to reload latest state → reapply typed mutator → CAS save with bounded retry.
- AGENTS.md loader is only the first consumer. Root instruction uses `scope=agent_runtime`, `toolkit_namespace=builtin`, `state_name=root_agents_instruction`. Project-scoped instruction uses `scope=session`, `toolkit_namespace=builtin`, `state_name=project_agents_instructions`.
- AGENTS.md full content snapshot is allowed and necessary. It is a cache snapshot to avoid reading sandbox every turn; source of truth remains the sandbox file. Refresh cadence and file-tool invalidation reconcile sandbox canonical content with the snapshot.
- AGENTS.md loader is implemented as builtin Toolkit functionality. Keep the `engine/tools/builtin.py` rename because builtin toolkit has broader responsibility than shell.

## Consequences

- Runtime adapter must know the active Toolkit list for Toolkit hook dispatch.
- Toolkit interface in `core/tools.py` grows to include tool-call hooks and state handle access.
- RDB migration and repository/service boundary are needed for Toolkit State storage.
- JSONB state is validated by per-Toolkit Pydantic models, while DB schema does not enforce internal payload structure.
- AGENTS.md prompt uses persistent state snapshot as fast path, while preserving that sandbox file is canonical source of truth.
- If policy hooks are needed later, structured result contracts such as `deny` / `modify_tool_input` must be added in a separate ADR.
- Project boundary continues to use Session Workspace Project registry as source of truth.

## Considered Options

### Option A — Introduce separate plugin runtime

The advantage is external extensibility. However, allowing arbitrary plugin execution in a multi-tenant service first requires manifest, capability gate, sandboxed execution, secret/network policy, resource limit, and version compatibility. This is too much prerequisite work just to implement AGENTS.md loader.

### Option B — Insert AGENTS-specific logic directly into tool_converter.py

Short-term implementation is fast, but path-scoped instruction logic appears outside the Toolkit state machine. Every future hook-like feature such as memory, policy, or audit would add feature-specific branching to runtime adapter.

### Option C — AGENTS.md-only S3 AgentsInstructionStore

This solves sharing across workers/pods but creates a store tailored only to AGENTS.md. Toolkit state identity, schema version, session/runtime scope, migration, and observability are not reused for other Toolkit features. It also easily confuses whether the source of truth is sandbox file or S3 object. This option is not adopted.

### Option D — Expand `agent_runtimes.runtime_state` JSON blob

This can store state quickly without a new table. But merging named states from many Toolkits into one blob makes partial update, schema version, ownership, TTL/cleanup, and queryability worse. AgentRuntime row locking/contention also grows. This option is not adopted.

### Option E — Toolkit hook + RDB Toolkit State

This provides hook functionality and durable state within the existing Toolkit execution boundary. Toolkits already update prompt and tool list every turn, so path observation and context prompt reflection connect naturally. RDB table explicitly manages state identity and version metadata. It does not provide an external plugin platform, but it is sufficient for current needs and the next Toolkit consumers.

## Acceptance Criteria

- Toolkit hooks are defined for before/after tool-call observation and separated from `update_context()` prompt assembly.
- Common Toolkit State abstraction is represented by `ToolkitStateStore` and typed `ToolkitStateHandle[T]`.
- Python state models are loaded/saved through a Pydantic-based generic API.
- State identity includes scope, agent runtime, optional session, toolkit namespace, and state name.
- Backend is RDB `toolkit_states` table; S3 and `agent_runtimes.runtime_state` blob are not used as accepted design.
- AGENTS.md loader is described only as the first consumer of `builtin/root_agents_instruction` and `builtin/project_agents_instructions` state.
- AGENTS.md full content snapshot is explicitly allowed as a cache snapshot, and its relationship to sandbox file canonical source of truth plus refresh/invalidation is explained.

## Migration provenance

- Historical source filename: `0032-toolkit-hooks-for-agents-md.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
