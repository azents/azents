---
title: "Discord Message Invocation"
created: 2026-07-26
tags: [discord, external-channel, architecture, security]
document_role: primary
document_type: adr
snapshot_id: external-260726
---

# Discord Message Invocation ADR

- Snapshot: `external-260726`
- Document reference: `external-260726/ADR`
- Requirements: [external-260726/REQ](../requirements/external-260726-discord-message-invocation.md)

## Context

The existing Discord Gateway admits and normalizes eligible human messages, but the
Discord processor stops after canonical message persistence. It does not resolve a
route, project pending context, enforce access policy, create a binding or invocation
batch, wake an Agent Session, or create an authorization prompt. Discord delivery for
Agent Channel Actions already exists, but no released input reaches that boundary.

The previous [discord-260726/ADR](discord-260726-agent-app-routing.md) established the
provider-neutral canonical model, Discord principal provenance boundary, durable
approval continuity, and dedicated Gateway ownership. This follow-up records only the
missing end-to-end message invocation decisions.

## Accepted Decisions

### external-260726/ADR-D1. Reuse canonical access and invocation ownership

**Affected requirements:** `external-260726/REQ-1`, `external-260726/REQ-2`,
`external-260726/REQ-3`, `external-260726/REQ-5`.

Discord message processing reuses the existing connection, route, resource, principal,
access request, grant, block, binding, pending context, invocation batch, mailbox, and
Channel Work records. It follows the existing connection → route → resource → binding
lock order and does not add Discord-specific Session, binding, grant, or invocation
tables.

A Discord principal remains provider provenance and access-policy subject matter only.
A valid existing grant or an authenticated Allow decision is required before an Agent
invocation is released.

**Rejected alternative:** Implicitly grant or derive execution identity from a Discord
user ID. This violates the established authorization boundary and makes provider
identity an execution User.

### external-260726/ADR-D2. Deliver Discord approval controls through the durable ledger

**Affected requirements:** `external-260726/REQ-1`, `external-260726/REQ-2`,
`external-260726/REQ-3`, `external-260726/REQ-4`.

An ungranted eligible Discord mention creates the existing idempotent access request
and a `CONTROL_MESSAGE` delivery attempt. Discord lowers the control to bounded,
Agent-attributed text with a labelled Markdown link to the authenticated Azents Web
approval page. The control stores no credentials, tokens, or raw inbound body.

A final Allow, Deny, or Block decision creates an idempotent delete attempt for a
delivered Discord control message through the same delivery ledger. The provider
message identity is retained only as a normal delivery result.

**Rejected alternative:** Retain completed approval prompts forever. It leaves stale
authorization affordances in the provider conversation and differs from the existing
approval lifecycle.

### external-260726/ADR-D3. Activate Discord bindings without remote-history hydration

**Affected requirements:** `external-260726/REQ-1`, `external-260726/REQ-3`,
`external-260726/REQ-5`.

This focused follow-up does not add a Discord remote-history adapter. For Discord, a
binding authorized by an existing grant or Allow decision becomes active while holding
the resource lock. The transaction releases all currently persisted route/resource
pending context into one idempotent invocation batch and its wake-producing mailbox
item before commit. After commit, the Session wake-up is sent.

This avoids applying Slack's `WAITING_HYDRATION` transition to Discord resources,
where it would never complete because Discord history hydration is not implemented.
Events that arrive after the commit serialize behind the active binding and use the
ordinary subsequent-invocation path.

**Rejected alternative:** Reuse Slack's hydration gate. It creates a permanent
activation deadlock for Discord and prevents the retained source message from reaching
the Agent.

### external-260726/ADR-D4. Ensure active Channel Work before a Discord wake-up

**Affected requirements:** `external-260726/REQ-3`, `external-260726/REQ-4`.

The approval release path ensures the binding has active Channel Work before its
mailbox wake-up. This preserves the Channel Action tool boundary for the resulting
Agent run. Slack retains its existing initial-hydration flow; Discord creates no
provider-visible initial Tracker in this focused fix because its later Channel Action
projection already owns Discord Tracker pages.

**Rejected alternative:** Wake a newly authorized Discord Session without Channel
Work. The run would lack the binding-scoped publication state required for a safe
Channel Action response.
