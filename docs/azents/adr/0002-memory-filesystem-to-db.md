---
title: "ADR-0002: Move Memory Storage from Filesystem to PostgreSQL"
date: 2026-04-26
related_issue: "#3021"
related_design: "design/memory-db-redesign.md"
---

# ADR-0002: Move Memory Storage from Filesystem to PostgreSQL

## Context

nointern's Memory system stores memories as Markdown files on the EFS filesystem: a `MEMORIES.md` index plus individual `{type}_{topic}.md` files. The model directly modifies those files through existing file tools such as write, edit, read, and delete.

This structure has the following problems:

1. **Concurrency**: If multiple sessions of the same agent edit `MEMORIES.md` at the same time, last-write-wins can lose data.
2. **No atomicity**: Saving a memory is a two-step operation, file write plus index edit. If the operation fails in the middle, orphan files can remain.
3. **EFS dependency**: This blocks the SDK Workspace direction introduced in Discussion #3011.

## Decision

Move Memory storage to the PostgreSQL `agent_memories` table and provide dedicated tool calls instead of file tools: `save_memory`, `list_memories`, `get_memory`, `search_memories`, and `delete_memory`.

Key decisions:

- **Single table** `agent_memories` — distinguish agent/user scope with `user_id = NULL`.
- **Built into BuiltinToolkit** — add memory tools to the existing Shell toolkit without introducing a separate ToolkitType.
- **SQL ILIKE search** — sufficient while the scale is below 50 entries; FTS/vector search can follow in a later phase.
- **Batch migration** — migrate existing data with a script and cut over immediately, without dual-write.
- **Partial unique indexes** — one for agent scope `(agent_id, name)` and one for user scope `(agent_id, user_id, name)`.

## Consequences

### Positive

- DB transactions fully solve concurrency problems.
- Saves become one-step atomic upserts.
- First step toward removing the EFS dependency is complete.
- Structured data makes future FTS/vector search expansion easier.

### Negative

- The model must adapt to the new tool call pattern, which requires prompt changes.
- Memories are no longer accessible through the old file-tool paths. This is intentional.
- Migration can encounter parsing errors, so dry-run validation is required beforehand.

### Impact Scope

- `rdb/models/` — new SQLAlchemy model
- `repos/memory/` — new repository
- `engine/tools/shell.py` — BuiltinToolkit changes: add tools and update prompt
- `engine/tools/memory.py` — new tool implementation
- `db-schemas/rdb/migrations/` — Alembic migration
- `memory_prompt_test.py` — update existing tests

## Alternatives

| Alternative | Reason Rejected |
|------|-----------|
| S3 + distributed lock with DynamoDB | PostgreSQL already exists; extra infrastructure complexity is unnecessary |
| Files + conditional PUT lock | File API does not support it, and it moves against the goal of removing EFS |
| Separate Memory microservice | Too much separation for the current scale |
| Add Redis cache layer | Memory is read once at session start; caching has no benefit |

## Status

Proposed
