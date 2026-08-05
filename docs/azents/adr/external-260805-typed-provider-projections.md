---
title: "External Channel Typed Provider Projections"
created: 2026-08-05
tags: [external-channel, slack, discord, architecture, backend]
document_role: primary
document_type: adr
snapshot_id: external-260805
---

# external-260805/ADR: External Channel Typed Provider Projections

- Snapshot: `external-260805`
- Requirements: [external-260805/REQ](../requirements/external-260805-typed-provider-projections.md)

## Decision Context

The current External Channel runtime uses public Discord SDK objects at the Gateway
boundary and Slack SDK clients for signature verification and Web API operations.
Provider facts then become generic JSON mappings for persistence and replay. Recreating
SDK objects from those mappings would require private SDK constructors, live cache
state, or fields deliberately omitted from bounded projections.

## Accepted Decisions

### external-260805/ADR-D1 — Persist Azents-owned typed projections, not SDK objects

**Affected requirements:** external-260805/REQ-1, REQ-2, REQ-3, REQ-4.

Azents will define provider-specific typed projection contracts at the boundary between
provider ingress or SDK responses and durable JSON. The contracts will validate and
normalize the bounded facts required by canonical processing, serialize to the existing
JSON carriers, and restore from those carriers during replay.

The live SDK remains the owner of provider transport behavior. Signed raw HTTP bodies
remain request-local for signature verification. Durable records will not contain SDK
objects, SDK private state, credentials, raw bodies, or Gateway frames.

**Rejected alternatives**

- Reconstruct SDK objects from stored JSON: Discord constructors require process-local
  connection state and provider context, while Slack has no complete inbound-event
  object model. Stored bounded projections are not complete SDK payloads.
- Retain generic mappings and use broad type suppressions: this leaves application
  validation and replay contracts implicit.
- Add a database migration for a new serialized format: existing JSON has the required
  semantics, so a schema change would add rollout risk without a product benefit.

**Consequences**

- Provider-specific parsing is explicit and independently testable.
- Replay remains independent from a live provider SDK session.
- Existing JSON values must continue to decode through the new contracts.

## Decision Record

- Decision owner: requester
- Accepted on: 2026-08-05
