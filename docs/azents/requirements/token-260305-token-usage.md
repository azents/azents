---
title: "Token Usage Storage Historical Requirements Reconstruction"
created: 2026-03-05
implemented: 2026-04-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: token-260305
historical_reconstruction: true
migration_source: "docs/azents/design/token-usage-storage.md"
---

# Token Usage Storage Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `token-260305`
- Source: `docs/azents/design/token-260305-token-usage.md`
- Historical source date basis: `2026-03-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

1. **No turn boundary**: event stream does not explicitly represent turn boundary. Multiple events (reasoning + text + tool_call) are stored in one turn, but it is impossible to know where the turn ends.
2. **Usage not stored**: token usage by turn is absent from DB, so usage analysis, cost tracking, context window management are impossible.
3. **Provider information loss**: detailed usage information provided by provider (cached tokens, reasoning tokens, etc.) is lost.
4. **Context window management impossible**: when conversation grows long, current history's occupancy in context window is unknown, so compaction trigger timing cannot be determined.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- **Turn completion marker**: explicitly represent turn boundary in event stream.
- **Store token usage**: persist usage by turn in DB.
- **Preserve provider original**: store normalized common fields + provider raw fields together.
- **Provide context window estimation basis**: use stored usage to estimate context size of next turn.

---

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Restrict existing truncate API (`DELETE /sessions/{id}/messages/{message_id}/after`) basis to **`TurnCompleteEvent` only**.

- Verify target `message_id` has `role=turn_complete`.
- Return `400 Bad Request` for other roles.

**Reason**: If truncated mid-turn, event sequence without `TurnCompleteEvent` (usage) appears and context window estimation becomes impossible. Cutting history only by turn keeps invariant that every event sequence ends with `TurnCompleteEvent`.

---

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
