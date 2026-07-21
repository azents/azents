---
title: "Memory Redesign: Filesystem → DB + Tool Call Historical Decision Reconstruction"
created: 2026-04-26
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: redesign-260426
historical_reconstruction: true
migration_source: "docs/azents/design/memory-db-redesign-2026-04-26.md"
---

# Memory Redesign: Filesystem → DB + Tool Call Historical Decision Reconstruction

- Snapshot: `redesign-260426`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/memory-db-redesign-2026-04-26.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### redesign-260426/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Constraints

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

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
