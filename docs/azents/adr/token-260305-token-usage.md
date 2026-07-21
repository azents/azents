---
title: "Token Usage Storage Historical Decision Reconstruction"
created: 2026-03-05
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: token-260305
historical_reconstruction: true
migration_source: "docs/azents/design/token-usage-storage.md"
---

# Token Usage Storage Historical Decision Reconstruction

- Snapshot: `token-260305`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/token-usage-storage.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### token-260305/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: 4.9 Truncate API — turn boundary constraint

Restrict existing truncate API (`DELETE /sessions/{id}/messages/{message_id}/after`) basis to **`TurnCompleteEvent` only**.

- Verify target `message_id` has `role=turn_complete`.
- Return `400 Bad Request` for other roles.

**Reason**: If truncated mid-turn, event sequence without `TurnCompleteEvent` (usage) appears and context window estimation becomes impossible. Cutting history only by turn keeps invariant that every event sequence ends with `TurnCompleteEvent`.

---

### Explicit source section: Phase 4: REST API exposure + Truncate constraint

**Goal**: Expose `TurnCompleteEvent` in message list and restrict truncate to turn boundary.

### Explicit source section: 4-3. Truncate API — add turn boundary constraint

**File:** `nointern/services/chat/__init__.py`

Change `truncate_session()`: verify message_id has `role=turn_complete`.

```python
async def truncate_session(
    self,
    session_id: str,
    message_id: str,
    *,
    user_id: str,
) -> Result[None, TruncateSessionError]:
    ...
    async with self.session_manager() as session:
        message = await self.message_repository.get_by_id(session, message_id)
        if message is None or message.channel_id != conv.channel_id:
            return Failure(MessageNotFound())

        # Turn boundary validation: allow only turn_complete role as truncate criterion.
        if message.role != MessageRole.TURN_COMPLETE:
            return Failure(NotTurnBoundary())

        await self.message_repository.delete_after_id(
            session, conv.channel_id, message_id
        )

    return Success(None)
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
