---
title: "Discord Bot Role Mention Invocation"
created: 2026-08-02
tags: [discord, external-channel, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260802
---

# discord-260802/ADR: Discord Bot Role Mention Invocation

## Context

The confirmed
[discord-260802/REQ](../requirements/discord-260802-bot-role-mention-invocation.md)
requires a mention of the connected Discord Bot's own managed role to enter the same
explicit-invocation path as a direct Bot-account mention. It excludes arbitrary,
manually created, assigned, and other-Bot roles while preserving every downstream
authorization and execution boundary.

Discord Gateway ingress already uses typed public `discord.py` objects. The event
projection retains mentioned user identities, and Discord normalization compares
those identities with the connection's validated `provider_bot_user_id`. The shared
synchronous ingestion service consumes only the resulting provider-neutral
`invocation` boolean.

The Requirements fix the user-visible behavior and exact ownership boundary. No
additional requester decision remains.

## Decision Backlog

1. **Accepted: invocation classification boundary** — classify the connected Bot's
   managed-role mention in the typed Discord Gateway projection and retain the shared
   provider-neutral admission authority.

Role projection field names, helper names, and test fixture identifiers remain
reversible implementation details.

## Decisions

### discord-260802/ADR-D1 — Typed Discord projection verifies managed-role ownership

The typed Discord Gateway projection reads each mentioned role's provider-owned Bot
tag and projects only the bounded role identity and owning Bot identity required for
normalization. Discord normalization classifies the message as an explicit invocation
when either:

- a mentioned user identity equals the connection's validated Bot user identity; or
- a mentioned managed role declares that same Bot user identity as its owner.

The provider adapter does not use role display names, ordinary membership, assigned
permissions, or a configured role identifier. It performs no provider REST lookup and
persists no role configuration. After normalization, the existing
provider-neutral `invocation` boolean remains the only response-mode and admission
input.

This decision applies to `discord-260802/REQ-1`, `REQ-2`, and `REQ-3`.

Matching role names is rejected because names are mutable and non-unique. Accepting
every role assigned to the Bot is rejected because administrators commonly assign
shared permission roles that do not express invocation intent. Persisting a role ID
is rejected because Discord already supplies authoritative Bot ownership and a stored
identifier would add activation, reconciliation, and stale-configuration lifecycle.

## Existing Decisions Preserved

- Discord Gateway ingress continues to use public typed SDK objects rather than raw
  frame parsing or private SDK state.
- Shared synchronous ingestion remains the sole authority for response mode,
  authorization, canonical mailbox admission, Session wake, and execution.
- The connection's validated `provider_bot_user_id` remains the canonical connected
  Bot identity.

## Risks

- A provider event without resolved role state cannot prove managed-role ownership
  and must remain a non-invocation rather than falling back to role text.
- Projecting arbitrary role metadata would broaden the provider-data boundary without
  improving invocation authority.
- Provider-fake E2E must include realistic Guild role state so the typed SDK resolves
  the role mention exactly as production does.
