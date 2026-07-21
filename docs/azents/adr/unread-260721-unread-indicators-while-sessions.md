---
title: "Suppress Unread Indicators While Sessions Run"
created: 2026-07-21
tags: [frontend, chat, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: unread-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0181-suppress-unread-indicators-while-sessions-run.md"
---

# unread-260721/ADR: Suppress Unread Indicators While Sessions Run

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-202) established a durable Session-shared unread boundary for terminal Run results. A Session can begin a newer Run before an older terminal result is reviewed, so the durable unread boundary and `run_state = running` can coexist.

Showing both the running spinner and unread dot in the Agent rail made active work appear to be an unread completed result. In normal use, queued or follow-up work made this combination frequent enough to obscure the intended attention signal.

## Decision

The Agent rail suppresses the unread terminal-result dot while a Session is running.

- The server-side unread boundary remains unchanged.
- The running spinner remains visible.
- When the Session returns to idle, the dot is shown again if its unread boundary still exists.
- Terminal completion of the current Run continues to replace an older unread boundary by Run index.
- Read acknowledgement behavior, permissions, persistence, and API projections remain unchanged.

This supersedes only the Agent rail presentation aspect of [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-203). [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-204) remains the source of truth for durable shared unread-boundary semantics.

## Consequences

- Active work is represented by one unambiguous running affordance.
- No terminal result is discarded: the durable unread boundary is restored to view once execution is idle.
- Users can still identify unread terminal results after the active Run finishes.

## Alternatives Rejected

### Clear unread when a newer Run starts

Rejected because starting work does not prove that any workspace member reviewed the earlier terminal result.

### Continue rendering both indicators

Rejected because the combined treatment is frequently interpreted as a contradictory Session state.

## Migration provenance

- Historical source filename: `0181-suppress-unread-indicators-while-sessions-run.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
