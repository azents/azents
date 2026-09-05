---
title: "Discord Moving Activity Tracker Decisions"
created: 2026-09-05
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260905
---

# discord-260905/ADR: Discord Moving Activity Tracker Decisions

- Snapshot: `discord-260905`
- Document reference: `discord-260905/ADR`
- Requirements:
  [`discord-260905/REQ`](../requirements/discord-260905-moving-activity-tracker.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Discord currently projects conversational Channel Work into one standalone retained
message. Editing that message preserves its chronological position, so long-running
Work can leave the current Tracker above later conversation. The current lifecycle
already treats progress as a provider projection of canonical Work and records the
current provider message identity.

## Decisions

### discord-260905/ADR-D1. Host the Tracker on the latest progress message

**Affects:** `discord-260905/REQ-1`, `REQ-2`, `REQ-4`

When a Discord Action delivers a conversational message and changes desired progress,
the delivered reply becomes the next Tracker host. A message-only Action does not move
the Tracker, and a state-only Action retains or creates the standalone host.

This ties movement to meaningful communication without introducing timer, heartbeat,
or channel-activity policy.

### discord-260905/ADR-D2. Remove before attaching

**Affects:** `discord-260905/REQ-1`, `REQ-3`

Relocation removes or detaches the current Tracker before attaching the complete latest
Tracker to the new reply. Temporary absence is accepted; visible duplication is not
part of the normal successful path.

Creating the replacement first was rejected because two simultaneous Trackers make the
current state ambiguous. Blocking conversational message delivery on Tracker cleanup
was also rejected; the reply is delivered first without the Tracker.

### discord-260905/ADR-D3. Keep Tracker recovery best-effort

**Affects:** `discord-260905/REQ-3`, `REQ-4`

Canonical Work and conversational replies retain strong ownership. Tracker mutations
remain immediate one-attempt effects whose failed or ambiguous outcomes are repaired by
a later complete progress projection when possible. The feature adds no durable retry
queue, provider outbox, or exactly-once relocation coordinator.

A persistent removal failure may keep the current Tracker at its older position. This
is preferred to creating a visible duplicate and is surfaced through the existing
provider effect outcome.

### discord-260905/ADR-D4. Attach after reply creation

**Affects:** `discord-260905/REQ-1`, `REQ-2`

The reply is created without Tracker presentation. After all reply parts are confirmed
delivered and previous Tracker removal is confirmed, Discord edits the final reply to
attach the Tracker Embed and controls.

This preserves ordinary reply delivery independently from Tracker projection and avoids
including the Tracker in the create request that triggers the reply notification.

### discord-260905/ADR-D5. Serialize Actions per Binding in one executor

**Affects:** `discord-260905/REQ-1`, `REQ-3`

One `ExternalChannelActionService` serializes complete Action execution for the same
Binding. Different Bindings remain independent. This closes parallel foreground Tool
calls inside one Session executor without adding a distributed lock, durable provider
queue, or cross-process exactly-once guarantee.

The existing single Session-owner generation remains the cross-Worker execution fence.
An older progress effect also revalidates its exact desired revision before provider
I/O so later canonical progress supersedes queued work.

## Consequences

- Tracker host identity can represent either a standalone message or a conversational
  reply.
- Updating a reply-hosted Tracker must preserve the reply content and attachments.
- Finishing or relocating a reply-hosted Tracker removes only Tracker presentation,
  not the conversational message.
- Provider-effect ordering needs explicit dependencies and access to a prior reply's
  confirmed message identity.
- A failed attachment after successful removal leaves the Tracker absent until a later
  progress update.
