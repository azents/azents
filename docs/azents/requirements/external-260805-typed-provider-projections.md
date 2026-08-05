---
title: "External Channel Typed Provider Projection Requirements"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [external-channel, slack, discord, backend]
document_role: primary
document_type: requirements
snapshot_id: external-260805
---

# External Channel Typed Provider Projection Requirements

- Snapshot: `external-260805`
- Document reference: `external-260805/REQ`

## Problem

Slack and Discord ingress, provider-history, and delivery code retain bounded
provider facts as generic JSON mappings. Later processing repeatedly reinterprets
those mappings, so valid provider data lacks a stable application-owned type contract
at the persistence and replay boundary.

## Primary Actor

The External Channel ingestion and replay runtime processing a Slack or Discord
conversation.

## Primary Scenario

After an authenticated provider callback or typed SDK event is admitted, Azents
serializes its bounded provider projection, later restores that projection through an
application-owned typed contract, and produces the same canonical message, interaction,
or delivery behavior without requiring a live provider SDK object.

## Supporting Scenarios

- Slack Web API and Discord REST history responses are narrowed before they enter
  provider normalization.
- Signed Slack and Discord HTTP bodies remain available only for request-local
  verification and parsing.
- Existing durable External Channel triggers and interactions remain replayable after
  deployment.

## Goals

- Give bounded Slack and Discord projections application-owned typed decode and encode
  boundaries.
- Preserve provider ingress, canonical message, interaction, history, replay, and
  delivery behavior.
- Remove the remaining backend `ty` diagnostics in the External Channel code paths.

## Non-Goals

- Reconstructing `discord.py` objects from persisted JSON.
- Replacing signed HTTP ingress with an SDK-specific HTTP server.
- Persisting raw signed bodies, provider SDK state, credentials, tokens, or Gateway
  frames.
- Changing public APIs, database schema, provider configuration, or provider message
  semantics.

## Requirements

### REQ-1. Typed durable provider projections

Azents must own the typed contract used to serialize and restore bounded Slack and
Discord provider projections needed by ingestion and replay.

**Acceptance criteria**

- A projection can be decoded after persistence without a live provider SDK client,
  cache, or private SDK state.
- A malformed projection fails through the existing bounded provider-invalid path.
- Stored projections retain the same JSON meaning required by existing canonical
  ingestion and interaction behavior.

### REQ-2. Ingress security and SDK boundaries

Signed provider HTTP bodies and live Discord Gateway SDK objects must retain their
current ownership and lifetime boundaries.

**Acceptance criteria**

- Slack and Discord signatures continue to be verified against request-local raw
  bytes before payload admission.
- Discord Gateway messages continue to use public typed `discord.py` callbacks.
- Raw bodies, credentials, tokens, SDK private state, and Gateway frames remain
  non-durable.

### REQ-3. Behavior-preserving provider processing

Typed projection adoption must preserve existing provider-neutral behavior.

**Acceptance criteria**

- Existing valid Slack and Discord callbacks, history records, interactions, files,
  and delivery projections retain their current canonical results.
- Existing durable records remain processable without a database migration.
- Provider errors remain classified through their existing domain error paths.

### REQ-4. Type-checking completion

The External Channel projection paths must have no remaining backend `ty` diagnostics.

**Acceptance criteria**

- `uv run ty check --error-on-warning` reports no diagnostics in
  `services/external_channel/`, `repos/external_channel/`, or
  `engine/events/external_channel_rendering.py`.
- Targeted provider ingress, history, interaction, delivery, and replay tests pass.

## Fixed Constraints

- The External Channel Living Specs remain the authority for ingress, security,
  persistence, replay, and provider behavior.
- The database JSON carrier remains the durable representation; this snapshot does not
  add a schema migration.
- SDK objects are process-local transport adapters, not durable application records.
- Existing public contracts and provider-visible behavior remain unchanged.

## Open Assumptions

- Existing stored projection JSON contains the bounded fields required by the current
  canonical processing paths.

## Confirmation

Confirmed by the requester on 2026-08-05 before ADR and design decisions began.
