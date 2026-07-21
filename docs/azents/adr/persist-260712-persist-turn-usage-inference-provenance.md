---
title: "Persist Inference Provenance on Turn Usage Markers"
created: 2026-07-12
tags: [architecture, chat, engine, frontend, observability, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: persist-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0142-persist-turn-usage-inference-provenance.md"
---

# persist-260712/ADR: Persist Inference Provenance on Turn Usage Markers

## Context

A durable `turn_marker` stores provider-reported token usage and the producing `run_id`. The chat token indicator can currently show model/profile context only while a matching live Run projection is available. After terminal cleanup, reload, or live-state parse failure, the durable usage remains but its model target, reasoning effort, model display, and effective limits become unavailable.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-73) keeps resolved inference provenance owned by AgentRun and rejects mutating or republishing user-message history events as Run state changes. That decision correctly protects append-only transcript ordering, but it leaves immutable per-turn usage facts without the inference snapshot needed to interpret them later.

## Decision

Persist an immutable applied inference provenance snapshot directly on each `turn_marker` payload when the marker is created.

The snapshot contains only safe fields needed to interpret the model step:

- model target label;
- raw nullable reasoning effort;
- nullable user-facing `model_display_name` already allowed by the public applied-profile projection;
- effective context window tokens;
- effective automatic compaction threshold tokens.

`run_id` remains the link to the owning AgentRun. The turn snapshot is copied from the Session inference state applied to that model call and never changes afterward.

Historical markers without the snapshot remain valid and display provenance as unavailable. Readers do not infer missing provenance from current Agent, Session, Composer, or live Run state.

This decision narrows [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-74) only for immutable per-turn usage facts. AgentRun remains the owner of mutable run lifecycle and full internal resolved provenance. User-message events remain free of mutable Run summaries and are not republished.

## Rejected Options

### Keep provenance available only while the Run is live

Rejected. Durable usage must remain interpretable after terminal cleanup and reload.

### Store the snapshot only in browser persistence

Rejected. Browser state is not authoritative and does not survive device changes or storage loss.

### Join every historical marker to AgentRun on read

Rejected. The marker describes one immutable model call, while Run and Session state may span multiple turns. A copied allowlisted snapshot is simpler and cannot drift after the fact.

### Attach resolved provenance to user messages again

Rejected. Usage belongs to a model turn, and reintroducing event-to-Run mutation would repeat the ordering and duplication problems superseded by [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-75).

## Consequences

- `TurnMarkerPayload` and the public canonical event schema gain nullable provenance fields.
- Historical payload decoding remains backward compatible through nullable fields.
- The token indicator can render stable historical model/profile context without live Run state.
- Per-turn storage duplicates a small allowlisted subset of the applied Session inference snapshot.
- Physical provider/model identifiers, credentials, and full provider selection snapshots remain excluded from public transcript payloads.

## Migration provenance

- Historical source filename: `0142-persist-turn-usage-inference-provenance.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
