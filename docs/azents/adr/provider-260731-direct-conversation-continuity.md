---
title: "Direct Provider Conversation Continuity"
created: 2026-07-31
tags: [architecture, external-channel, slack, discord, mailbox, persistence]
document_role: primary
document_type: adr
snapshot_id: provider-260731
---

# provider-260731/ADR: Direct Provider Conversation Continuity

## Context

The confirmed
[provider-260731/REQ](../requirements/provider-260731-direct-conversation-continuity.md)
requires one provider-history ingestion to become one canonical Session input without
retaining parallel External Channel message, revision, invocation-batch, admission,
provisioning, or wake-dispatch owners.

The earlier `channel-260729` snapshot established synchronous provider-history ingestion
but retained several preexisting persistence units as implementation mechanisms. This
snapshot replaces those mechanisms without modifying the implemented historical
snapshot.

## Decision Backlog

All hard-to-reverse decisions were fixed by the requester before this ADR was recorded:

1. **Accepted:** mailbox item identity owns accepted input idempotency and wake recovery.
2. **Accepted:** access requests and interactions retain content-free replay boundaries.
3. **Accepted:** obsolete inbound tables and enums are removed through a guarded cutover.
4. **Accepted:** file keys carry provider coordinates directly and provider permissions
   authorize downloads.

## Decisions

### provider-260731/ADR-D1 — The mailbox item is the accepted invocation identity

One deterministic idempotency key derived from connection, conversation position,
trigger provider message key, and trigger position identifies the canonical mailbox
item. Mailbox acceptance and conversation-position advancement occur in one transaction.
The pending mailbox item is also the recoverable Session wake identity.

This applies to `provider-260731/REQ-1` and `REQ-2`.

A separate invocation batch and wake-dispatch ledger are rejected because they duplicate
the mailbox's accepted-input and pending-work responsibilities.

### provider-260731/ADR-D2 — Replay owners retain typed boundaries, not content

Selector state is stored in the owning interaction projection. Approval state is stored
in the access request. Both retain provider message identity, conversation position,
range start, trigger position, principal, resource, and selected route where applicable.
Replay reloads and validates those owners before pulling provider history.

This applies to `provider-260731/REQ-3`.

Retaining message or revision rows for replay is rejected because provider history is the
content authority and the typed boundary is sufficient to recover the request.

### provider-260731/ADR-D3 — Legacy inbound persistence is removed in one guarded cutover

The migration first verifies that no in-flight provisioning or undispatched legacy wake
would be lost. It then backfills access-request provider message keys, converts open
selector admissions into interaction projections, and drops the retired tables and DB
enums. Data-bearing downgrade is rejected because removed provider content and batch
membership cannot be reconstructed safely.

This applies to `provider-260731/REQ-4`.

Keeping empty compatibility models or tables is rejected because it preserves false
ownership and invites new runtime dependencies on retired state.

### provider-260731/ADR-D4 — File keys directly contain provider request coordinates

The existing file-key contract is replaced in place. Discord keys contain binding,
channel, message, and attachment identity; Slack keys contain binding and provider file
identity. Discord download uses those coordinates directly. The active provider
connection's credentials and permissions remain the authorization boundary.

This applies to `provider-260731/REQ-5`.

Session-event attachment lookup, a new locator version, and a legacy fallback are
rejected as unnecessary indirection and compatibility complexity.

## Consequences

- Provider history, mailbox items, Session events, positions, access requests, and
  interactions have non-overlapping durable responsibilities.
- Existing persisted file keys using the replaced shape are not supported.
- Migration failures report only aggregate blocker counts and no provider identities or
  content.
- The runtime and schema become smaller, but cutover requires the legacy in-flight state
  checks to pass.
