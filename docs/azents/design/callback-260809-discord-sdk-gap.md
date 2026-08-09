---
title: "Discord Callback SDK Gap Design"
created: 2026-08-09
updated: 2026-08-09
implemented: 2026-08-09
tags: [external-channel, discord, sdk, callback, backend, testenv]
document_role: primary
document_type: design
snapshot_id: callback-260809
---

# callback-260809/DESIGN: Discord Callback SDK Gap

## System Boundary

`DiscordAPIClient` continues to own Application activation coordination. SDK sessions
remain authoritative for Application metadata, Bot identity, and preservation-safe
command reconciliation. A new narrow callback transport owns only the provider
Interaction Endpoint mutation that the adopted SDK cannot currently perform.

## Mechanisms

### M1. Operation-specific callback transport

Define `DiscordInteractionEndpointTransport` with one `configure()` operation accepting
only the Bot token and endpoint URL. Its production implementation issues one
`PATCH` to the current Application route using the existing bounded Discord API base
selection and maps credential, configuration, rate-limit, transport, and server
responses to established `DiscordAPIError` categories.

### M2. Explicit composition without fallback

Inject the callback transport into `DiscordAPIClient`. The callback method calls only
that transport; it does not first call the SDK or retry through a second path.
Application metadata and command operations remain on their existing SDK boundaries.

### M3. Closed allowlist and deterministic evidence

The repository boundary check names callback configuration as an approved direct gap.
Unit tests inspect the exact method, route, authorization, and JSON field. Existing
Discord provider fake routes record only Application identity and retain the callback
URL only in volatile fixture state needed to deliver signed interactions.

### M4. Removal condition

When an adopted `discord.py` release sends `interactions_endpoint_url` through its
public Application edit API, replace M1 with that SDK call, remove its dependency and
route allowance, and retain only the SDK-facing deterministic fixture.

## Failure and Security

The transport performs one attempt and preserves current activation classification:
401/403 is invalid credentials, other 4xx is invalid callback configuration, and 429,
transport errors, or 5xx is provider unavailable. The Bot token remains request-local;
logs and deterministic evidence contain neither the token nor callback selector.

## Test Strategy

1. Unit-test exact request construction and safe response mapping.
2. Run Discord activation, API adapter, SDK boundary, and endpoint tests.
3. Run the focused deterministic Discord activation journeys.
4. Run Ruff, format, `ty`, generated documentation validation, and complete PR CI.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | One fixed callback configuration transport | `callback-260809/REQ-1`, `REQ-2`, `REQ-3`; `callback-260809/ADR-D1`, `ADR-D2` | `decided` |
| M2 | Explicit transport composition without an SDK/direct fallback | `callback-260809/REQ-2`, `REQ-3`; `callback-260809/ADR-D2` | `decided` |
| M3 | Closed static allowlist and deterministic request/evidence coverage | `callback-260809/REQ-3`, `REQ-4`; `callback-260809/ADR-D2` | `derived` |
| M4 | Delete the gap when the adopted public SDK becomes usable | `callback-260809/REQ-3`; `callback-260809/ADR-D2` | `decided` |

## Feasibility

Feasible. `discord_api.py` already composes an operation-specific direct transport and
the deterministic provider fake already serves the exact callback route. The change
requires no database, public API, event, configuration, or credential-lifecycle
change.

## Design Approval

- Mode: Collaborative
- Decision owner: Requester
- Approval status: Approved
- Approved on: 2026-08-09
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approval evidence: the requester explicitly classified the broken SDK operation as
  unsupported; the remaining transport interface, error mapping, fixture wiring, and
  removal mechanics are local consequences of that decision and existing contracts.
