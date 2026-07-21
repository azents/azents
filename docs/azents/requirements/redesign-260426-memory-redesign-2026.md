---
title: "Memory Redesign: Filesystem → DB + Tool Call Historical Requirements Reconstruction"
created: 2026-04-26
implemented: 2026-04-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: redesign-260426
historical_reconstruction: true
migration_source: "docs/azents/design/memory-db-redesign-2026-04-26.md"
---

# Memory Redesign: Filesystem → DB + Tool Call Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `redesign-260426`
- Source: `docs/azents/design/redesign-260426-memory-redesign-2026.md`
- Historical source date basis: `2026-04-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Current Memory system stores markdown files in EFS filesystem, and model directly manipulates them with existing file tools (write/edit/read/delete).

Switch this to PostgreSQL DB based + dedicated tool calls to:

1. **Resolve concurrency issue** — when multiple sessions of same agent modify MEMORIES.md concurrently, last-write-wins can lose data
2. **First step toward removing EFS dependency** — prerequisite for SDK Workspace introduction (Discussion #3011)
3. **Atomicity of 2-step save** — currently file write + index edit are separate, creating orphan files if intermediate failure occurs

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Agent's experience of storing/querying/deleting information learned during conversation remains same, but uses dedicated memory tools instead of file tools:

```
[Before]
Agent: write("/data/agent/memories/feedback_no_mock.md", content="---\n...")
Agent: edit("/data/agent/memories/MEMORIES.md", old_string="...", new_string="...")

[After]
Agent: save_memory(scope="agent", type="feedback", name="no-mock", description="...", content="...")
```

## Supporting Scenarios

Agent's experience of storing/querying/deleting information learned during conversation remains same, but uses dedicated memory tools instead of file tools:

```
[Before]
Agent: write("/data/agent/memories/feedback_no_mock.md", content="---\n...")
Agent: edit("/data/agent/memories/MEMORIES.md", old_string="...", new_string="...")

[After]
Agent: save_memory(scope="agent", type="feedback", name="no-mock", description="...", content="...")
```

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

```sql
-- agent scope: (agent_id, name) unique where user_id IS NULL
CREATE UNIQUE INDEX uq_agent_memories_agent_scope
    ON agent_memories (agent_id, name) WHERE user_id IS NULL;

-- user scope: (agent_id, user_id, name) unique where user_id IS NOT NULL
CREATE UNIQUE INDEX uq_agent_memories_user_scope
    ON agent_memories (agent_id, user_id, name) WHERE user_id IS NOT NULL;

-- for index injection: agent scope query
CREATE INDEX ix_agent_memories_agent_id
    ON agent_memories (agent_id) WHERE user_id IS NULL;

-- for index injection: user scope query
CREATE INDEX ix_agent_memories_agent_user
    ON agent_memories (agent_id, user_id) WHERE user_id IS NOT NULL;
```

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
