---
title: "Memory"
created: 2026-05-10
tags: [backend, engine, api, frontend]
spec_type: domain
domain: memory
owner: "@Hardtack"
code_paths:
  - python/apps/azents/src/azents/rdb/models/memory.py
  - python/apps/azents/src/azents/repos/memory/**
  - python/apps/azents/src/azents/services/memory/**
  - python/apps/azents/src/azents/api/public/agent/v1/__init__.py
  - python/apps/azents/src/azents/api/public/agent/v1/data.py
  - python/apps/azents/src/azents/engine/tools/memory.py
  - python/apps/azents/src/azents/engine/tools/shell.py
  - python/apps/azents/src/azents/engine/run/resolve.py
  - typescript/apps/azents-web/src/features/agents/AgentMemorySettingsPage.tsx
  - typescript/apps/azents-web/src/features/agents/components/AgentMemorySettings.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentMemorySettingsContainer.ts
  - typescript/apps/azents-web/src/trpc/routers/agent.ts
api_routes:
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/memories
  - /agent/v1/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}
last_verified_at: 2026-07-02
spec_version: 2
---

# Memory

## Overview

Memory is an RDB-backed knowledge store for saving user preferences, project state, repeated feedback, and external system references discovered by agent during conversation so they can be reused in later executions. Current implementation does not use vector DB or hidden automatic summaries. Memory changes only when agent explicitly calls `save_memory`, `list_memories`, `get_memory`, `search_memories`, or `delete_memory` tools.

Memory belongs to Agent. Even within same Workspace, Memory is not shared when Agent differs. Within a single Agent, Memory has two scopes. Memory can be changed by Agent runtime tools and by human-facing Agent Memory settings UI/API; neither path creates hidden automatic summaries.

- `agent` scope — team/project knowledge shared with all users of that Agent.
- `user` scope — personal preferences/feedback visible only to specific user. Cannot be read or stored in executions without user context.

## Domain Model

```mermaid
erDiagram
    AGENT ||--o{ AGENT_MEMORY : owns
    USER ||--o{ AGENT_MEMORY : "optional owner"

    AGENT_MEMORY {
        string id PK
        string agent_id FK
        string scope "agent|user"
        string type
        string name
        string description
        string content
        string user_id "nullable"
        datetime created_at
        datetime updated_at
    }
```

Main constraints of `agent_memories` are:

| Constraint | Meaning |
|---|---|
| `uq_agent_memories_agent_scope` | `(agent_id, name)` unique in agent scope where `user_id IS NULL` |
| `uq_agent_memories_user_scope` | `(agent_id, user_id, name)` unique in user scope where `user_id IS NOT NULL` |
| `ix_agent_memories_agent_id` | partial index for listing agent scope |
| `ix_agent_memories_agent_user` | partial index for listing user scope |

`scope` column is PostgreSQL ENUM `memory_scope` (`agent`, `user`). `type` is stored as free string in current code, but tool descriptions recommend four usages: `user`, `feedback`, `project`, `reference`.

## Behavior

### Tool exposure

During AgentRuntime resolve, Agent with `memory_enabled` enabled receives Memory tools and Memory index prompt. If user context exists, both agent scope and user scope summaries are exposed; if user context does not exist, only agent scope is exposed. If `memory_enabled=false`, neither Memory tools nor prompt are exposed.

### Save / upsert

`save_memory` uses `name` as upsert key within same scope. If existing row exists, update `description`, `content`, `type`, and `scope`; otherwise create new row. If tool input has `scope=user` but execution context has no `user_id`, raise `FunctionToolError("Cannot save user-scope memory: no user context")`.

### Tool list / get / search / delete

- `list_memories(scope=None, type=None)` returns agent scope summary and user scope summary grouped by type as markdown list. It queries sorted up to 100 rows per scope.
- `get_memory(scope, name)` returns full `content` of a single Memory. Missing row is handled as tool error.
- `search_memories(query, scope=None)` is `ILIKE` search over `name`, `description`, and `content`. If `scope=None` and user context exists, it searches both agent scope and user scope and returns up to 50 summaries.
- `delete_memory(scope, name)` deletes by scope/name and returns existence result as JSON.

### Public API and settings UI

Agent Memory settings use public Agent API routes under `/agent/v1/workspaces/{handle}/agents/{agent_id}/memories`. The list route requires an exact `scope` query parameter and accepts optional `type` and `query` filters. Empty search query uses normal sorted list semantics; non-empty search query performs lexical `ILIKE` search over `name`, `description`, and `content`.

Visibility follows Agent visibility. Agent-scope Memory is readable by users who can view the Agent. User-scope Memory is limited to entries whose `user_id` is the current authenticated user. Private Agent visibility failures are reported as `404 Agent not found` rather than exposing existence. Missing or scope-invisible Memory IDs are reported as `404 Memory not found`.

Human-facing create/update/delete semantics are stricter than the runtime `save_memory` upsert tool:

- Creating Memory with a duplicate `name` in the same effective scope returns conflict instead of upserting.
- Updating `name` to another visible row's name in the same effective scope returns conflict.
- Agent-scope create/update/delete requires Agent admin or Workspace owner.
- User-scope create/update/delete is allowed for the current user's own visible entries.

The Agent Memory settings page exposes the Agent `memory_enabled` toggle and manual Memory management. It has Agent/User scope tabs, search, create/edit modal, and delete confirmation. It does not automatically promote conversation content into Memory and does not change runtime tool exposure beyond the explicit `memory_enabled` Agent setting.

## Invariants

- Memory is isolated per Agent. user scope is also limited by `(agent_id, user_id)`.
- user scope cannot be written or directly read in execution without user context.
- Output of Memory tools is normal tool output, so it may remain as conversation event. Whether to save credentials, secrets, or personally identifiable information depends on Agent tool-use policy and user instruction.
- Search is lexical `ILIKE`. Current implementation has no embedding similarity, automatic relevance ranking, or automatic compaction-to-memory promotion.
- Runtime tool `save_memory` is upsert-by-name, while human-facing API create/update uses strict duplicate conflict semantics.

## Change History

| Date | Version | Change |
|---|---:|---|
| 2026-07-02 | 2 | Added public Agent Memory settings API/UI behavior and permission semantics |
| 2026-05-10 | 1 | Initial Memory domain spec |

## Related specs

- LLM/tool orchestration of Agent follows [`agent.md`](agent.md) and [`../flow/agent-execution-loop.md`](../flow/agent-execution-loop.md).
- Conversation history compaction is separate from Memory and covered in [`../flow/context-compaction.md`](../flow/context-compaction.md).
