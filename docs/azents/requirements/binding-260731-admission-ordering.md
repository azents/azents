---
title: "External Channel Binding and Admission Ordering Requirements"
created: 2026-07-31
updated: 2026-07-31
implemented: 2026-07-31
tags: [external-channel, binding, ingress, delivery]
document_role: primary
document_type: requirements
snapshot_id: binding-260731
---

# External Channel Binding and Admission Ordering Requirements

- Snapshot: `binding-260731`
- Document reference: `binding-260731/REQ`

## Problem

External Channel session bindings and outbound delivery are currently coupled to transient provider-ingress health. A brief Discord Gateway disconnect can make an established binding appear unavailable and reject REST delivery. Initial binding, provider progress creation, and mailbox admission can also complete out of order, allowing Agent execution before the provider-visible session and progress projections exist.

## Primary Actor

A participant who invokes an Agent from an established Slack or Discord conversation and expects the conversation relationship and replies to remain available until an explicit disconnect.

## Primary Scenario

1. An eligible provider message starts or continues an External Channel conversation.
2. Azents creates or reuses the persistent Session binding.
3. For a new binding, Azents delivers the one-time Session link, then creates the initial provider progress projection.
4. Only after the required provider deliveries succeed does Azents admit the canonical mailbox input, mark the Session runnable, and wake Agent execution.
5. The binding remains usable across Gateway disconnects, reconnects, lease changes, and other ingress-health transitions.
6. Agent replies use the provider REST API independently from persistent-ingress runtime health.

## Supporting Scenarios

- A transient Discord Gateway disconnect does not reject a reply from an existing bound Session.
- A required Session-link or initial-progress delivery failure prevents mailbox admission and Agent execution for that provider event.
- Retrying an interrupted admission reuses its durable binding and delivery identities without duplicating provider projections or mailbox input.
- An explicit binding or connection disconnect ends future use without reactivating the historical relationship.
- A newly created Discord conversation channel or thread uses the current Agent name as its default title.

## Goals

- Keep Channel binding identity stable until explicit disconnect.
- Make binding, initial provider projection, and mailbox admission observably ordered.
- Separate persistent-ingress health from outbound REST delivery authority.
- Prevent Agent execution when its required initial provider projections were not completed.
- Give new Discord conversation channels a useful Agent-derived default title.

## Non-Goals

- Sending provider requests while a database transaction is open.
- Retrying an ambiguous provider mutation by issuing an uncorrelated duplicate request.
- Renaming existing Discord channels or automatically renaming a channel after the Agent name changes.
- Making an explicitly disconnected connection deliver without credentials.
- Changing provider authentication or user access policy.

## Requirements

### REQ-1. Persistent binding relationship

A Channel binding must remain a valid relationship until an explicit disconnect operation terminates it.

**Acceptance criteria**

- Binding lifecycle has no transient active or inactive state.
- Gateway health, lease ownership, reconnect state, and provider-ingress availability do not enable or disable an existing binding.
- Explicit disconnect records the terminal relationship boundary and prevents future admission and delivery through that binding.
- Historical binding identity is not reactivated after disconnect.

### REQ-2. Ordered initial admission

A new or repaired binding must complete its required provider-visible initialization before its triggering message reaches Agent execution.

**Acceptance criteria**

- Session binding completes before initial progress creation begins.
- Initial progress creation completes before canonical mailbox input is admitted.
- Session running transition, wake dispatch, and conversation-position advancement occur only after the required initial deliveries succeed.
- Existing bindings with completed initialization do not repeat the one-time Session-link projection.

### REQ-3. Provider I/O outside database transactions

Provider delivery must remain outside database transactions while the ingestion operation waits synchronously for each required step.

**Acceptance criteria**

- Database transactions persist durable binding, delivery intent, and final mailbox state without awaiting Slack or Discord network I/O.
- The ingestion orchestrator awaits provider delivery between the binding transaction and the mailbox-finalization transaction.
- A crash or retry reuses durable identities and does not create duplicate bindings, initial progress projections, or mailbox inputs.

### REQ-4. Fail-closed mailbox admission

A required Session-link or initial-progress delivery that is failed, unknown, unavailable, or incomplete must prevent mailbox admission.

**Acceptance criteria**

- No mailbox item, Session wake, or Agent execution is produced before required delivery completion.
- The provider event is not reported as successfully handled when a required initial delivery is incomplete.
- The durable delivery result remains inspectable without retaining provider payloads, credentials, or raw identifiers in diagnostics.

### REQ-5. Outbound delivery independent from Gateway health

Outbound Slack and Discord delivery must use provider REST APIs independently from persistent-ingress runtime health.

**Acceptance criteria**

- Discord Gateway and Slack Socket lifecycle state is used only for inbound ownership, health, and diagnostics.
- Transient degraded, reconnecting, gap, lease, or heartbeat state does not reject an outbound provider API attempt.
- Outbound authority continues to require a non-disconnected binding, current Agent/Session/route authority, configured credentials, and provider capability.
- Provider API outcomes remain the source of truth for delivered, failed, or unknown delivery results.

### REQ-6. Agent-derived Discord channel title

A newly created Discord conversation channel or thread must default to the current Agent name.

**Acceptance criteria**

- The default title is derived from the Agent bound to the new conversation at creation time.
- Existing provider channels and threads are not renamed.
- A later Agent rename does not automatically rename an existing provider channel or thread.
- The title remains bounded and valid for Discord.

## Fixed Constraints

- Provider payloads, credentials, raw identifiers, and URLs must not be exposed in logs or operational evidence.
- Durable admission and provider delivery remain idempotent and fenced.
- Ambiguous provider writes are not blindly replayed.
- Explicit disconnect remains terminal for the historical binding.
- Slack HTTP acknowledgement and persistent transport handling must report success only after the ordered ingestion operation reaches its completed outcome.

## Open Assumptions

- The current Agent name at Discord channel creation time is the authoritative default when the provider supports a channel or thread title.
- Existing explicit provider titles remain authoritative and are not overwritten.

## Confirmation

Confirmed by the requester on 2026-07-31 before ADR and design decisions began.
