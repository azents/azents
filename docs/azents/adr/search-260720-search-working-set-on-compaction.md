---
title: "Reset the Tool Search Working Set on Successful Compaction"
created: 2026-07-20
tags: [architecture, backend, engine, toolkit, compaction, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: search-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0172-reset-tool-search-working-set-on-compaction.md"
---
# search-260720/ADR: Reset the Tool Search Working Set on Successful Compaction

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-185) established a session-scoped Tool Search working set that survives context compaction. That policy preserves capability recency across the entire AgentSession, but compaction is also the explicit boundary where Azents replaces the model-visible conversation history with a new durable checkpoint.

Keeping deferred-tool activation across that boundary can expose tools selected for details that no longer remain in the active model context. The compacted model should rediscover deferred capabilities from the checkpoint and subsequent user intent instead of inheriting an unbounded pre-compaction relevance history.

The working set is stored as the `tool_search/working_set` session-bound Toolkit State. Other Toolkit State in the same AgentSession includes independent durable state such as Todo, Goal, and MCP tool snapshots and must not be reset with Tool Search recency.

## Decision

A successful manual or automatic context compaction resets the Tool Search working set for the compacted AgentSession.

The reset has the following contract:

1. The compaction transaction appends the marker and summary, moves the Session model-input head, and replaces `tool_search/working_set` with an empty `tool_names` list atomically.
2. The reset applies regardless of the Agent's current `tool_search_enabled` value so disabling and later re-enabling Tool Search cannot restore pre-compaction activation.
3. A compaction that is skipped because there is no input or the automatic threshold is not exceeded does not reset the working set.
4. A failed or stale compaction does not reset the working set.
5. No other Toolkit State identity is changed.
6. After compaction, direct tools and `tool_search` remain available according to the normal Agent and provider projection rules. Deferred tools must be activated again through Tool Search or later invocation intent.

The reset runs through the existing Toolkit State optimistic-lock contract using the same database session as the final compaction write transaction. If the reset cannot be persisted, the marker, summary, and model-input-head move are rolled back with it.

## Rationale

- Compaction is the clearest existing lifecycle boundary for discarding stale capability relevance.
- Atomic persistence prevents the Session transcript head and Tool Search state from representing different compaction epochs.
- Resetting only one Toolkit State identity preserves Todo, Goal, MCP discovery snapshots, and other independent session state.
- Applying the reset while Tool Search is disabled prevents stale activation from reappearing after an Agent setting change.

## Consequences

- Tool Search recency continues to survive model turns, AgentRuns, worker restart, session-owner handoff, and archive/unarchive until a successful compaction occurs.
- The first prepared model call after compaction contains direct tools and Tool Search, but no deferred tools activated only before the compaction boundary.
- Agents may need one additional Tool Search call after compaction to recover a still-relevant deferred capability.
- The compactor gains a generic transactional state-update callback so the Tool Search concern remains outside the generic transcript compaction implementation.

## Alternatives Considered

### Keep the working set across compaction

Rejected because the working set can retain capability relevance derived from transcript detail that the model can no longer inspect after compaction.

### Reset after the compaction transaction commits

Rejected because a process failure or Toolkit State write failure could leave the summary committed while the old working set remains active.

### Delete all Session Toolkit State

Rejected because Todo, Goal, MCP snapshots, and other Toolkit State have independent durability semantics and are required after compaction.

## Relationship to Earlier Decisions

This ADR supersedes only the [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-186) statement that Tool Search working-set recency survives compaction. All other [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-187) decisions remain in effect.

## Migration provenance

- Historical source filename: `0172-reset-tool-search-working-set-on-compaction.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
