---
title: "Discord Callback SDK Gap Decisions"
created: 2026-08-09
tags: [architecture, external-channel, discord, sdk, callback]
document_role: primary
document_type: adr
snapshot_id: callback-260809
---

# callback-260809/ADR: Discord Callback SDK Gap

## Context

`callback-260809/REQ` preserves automatic callback configuration while the adopted
`discord.py` release removes `interactions_endpoint_url` from the public
`AppInfo.edit()` payload before transport. The existing
`external-260809/ADR-D1` defines SDK support by the ability to perform the required
provider effect, not by method presence alone.

## Decisions

### callback-260809/ADR-D1 — Classify callback edit as an adopted-SDK capability gap

Discord Interaction Endpoint configuration is not SDK-supported while the adopted
public API cannot transmit the endpoint field. Azents will not use SDK private HTTP
objects, mutate SDK internals, add a second SDK, or pretend an empty provider mutation
completed the effect.

This decision applies to `callback-260809/REQ-1`, `REQ-2`, and `REQ-4`.

### callback-260809/ADR-D2 — Use one fixed callback-configuration transport

One operation-specific transport owns `PATCH /applications/@me` with the Bot
credential and exact callback URL. It has no generic request method and is composed
alongside, not as a fallback behind, the SDK adapter. SDK ownership remains unchanged
for every usable public operation.

The transport is removed when an adopted `discord.py` release demonstrably transmits
the Interaction Endpoint through its public API. No compatibility mode retains both
paths.

This decision applies to `callback-260809/REQ-1`, `REQ-2`, `REQ-3`, and `REQ-4`.

## Consequences

- The direct-provider allowlist gains one exact Discord control-plane operation.
- Production callback configuration remains functional without private SDK access.
- Deterministic fixtures continue to exercise the real fixed route and callback
  evidence.
- A future dependency update must replace and delete the transport once the public SDK
  capability is usable.

## Approval

- Mode: Collaborative
- Decision owner: Requester
- Approved on: 2026-08-09
- Approval evidence: the requester confirmed that an SDK operation broken in the
  adopted implementation is not SDK-supported.
