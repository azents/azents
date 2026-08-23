---
title: "azents Discord Integration Historical Decision Reconstruction"
created: 2026-03-10
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: azents-260310
historical_reconstruction: true
migration_source: "docs/azents/design/azents-discord-integration.md"
---

# azents Discord Integration Historical Decision Reconstruction

- Snapshot: `azents-260310`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/azents-discord-integration.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### azents-260310/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Gateway-Based Architecture

Slack receives events through HTTP callbacks, but Discord delivers normal message events only through the Gateway (WebSocket). The Interactions Endpoint (HTTP) can handle only limited events such as slash commands and buttons.

Therefore this design runs a separate Gateway process:

- **`azents-discord-gateway`** — Maintains a Discord Gateway WebSocket connection and receives events.
- Forwards received events to the Redis broker so the existing engine worker can process them.
- Also receives interactions such as slash commands through the Gateway; no separate Interactions Endpoint is operated.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
