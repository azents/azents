---
title: "External Watch / Raw Session Event Subscription Historical Decision Reconstruction"
created: 2026-05-03
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: external-260503
historical_reconstruction: true
migration_source: "docs/azents/design/external-watch-raw-session-subscription.md"
---

# External Watch / Raw Session Event Subscription Historical Decision Reconstruction

- Snapshot: `external-260503`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/external-watch-raw-session-subscription.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### external-260503/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Current Worker Constraints

- `EngineWorker` shards per-session runner by `session_id` of message received from broker.
- When receiving `SessionMessage`, it updates `conversation_sessions.run_state`, `last_activity_at`, `run_heartbeat_at`, and notifies sandbox manager of activity.
- Stuck recovery creates `RESUME` message with `ConversationSession` record.
- Therefore, first implementation of #3332 provides bridge to use `session_id = agent.raw_session_id`, and removal of `ConversationSession` runtime fields is completed in #3331/#3338.

### Explicit source section: Access Policy Hook

`ExternalWatchService.resolve_or_create_watch(...)` calls following hook before creating watch.

```python
class ExternalWatchPolicy(Protocol):
    async def can_bind_external_watch(
        self,
        *,
        agent_id: str,
        source: str,
        scope: str,
        actor_user_id: str | None,
        installation_id: str | None,
        metadata: dict[str, object],
    ) -> bool: ...
```

Initial implementation validates only workspace membership, installation ownership, and channel binding. Personal agent DM-only/private policy is added as subsequent implementation of this hook.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
