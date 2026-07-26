---
title: "Discord Agent App Routing phase 6: Interactions and routing"
created: 2026-07-26
tags: [discord, external-channel, interactions, routing, security]
document_type: implementation-plan
snapshot_id: discord-260726
---

# Discord Agent App Routing phase 6: Interactions and routing

## Scope

This phase adds Discord outgoing HTTP interaction ingress. The public API verifies the
Ed25519 signature over the bounded raw body, accepts PING, durably admits supported
message commands and control callbacks, and returns the initial Discord response within
the request boundary.

## Source documents

- Requirements: [discord-260726/REQ](../requirements/discord-260726-agent-app-routing.md)
- ADR: [discord-260726/ADR-D2](../adr/discord-260726-agent-app-routing.md)
- Design: [discord-260726/DESIGN](../design/discord-260726-agent-app-routing.md)
- Stack plan: [Discord Agent App Routing Implementation Plan](discord-agent-app-routing-implementation-plan.md)

## Delivery boundaries

- Select the configured Discord connection using an opaque callback selector before
  trusting interaction payload identity.
- Verify Discord Ed25519 signatures against the selected connection public key and the
  exact timestamp-prefixed raw body.
- Retain interaction/source/principal facts through canonical admission before returning
  a non-PING response.
- Treat interaction tokens, webhook URLs, and immediate response capabilities as
  request-local only. Never persist, log, broker, or retry them.
- Resolve a Single route or valid Multi default through canonical routing state, but do
  not create a provider thread before a route is fixed.

## Exclusions

- Gateway message normalization, Message Content capability, history hydration, and
  attachment handling remain phase 7.
- Provider thread creation/reconciliation and access continuation remain deferred until
  their canonical source/resource handling is available.
- Outbound reply delivery and Web UI remain later phases.

## Verification

- Focused tests cover PING, signature tampering, expired/malformed requests, opaque
  selector routing, duplicate interaction convergence, and request-local token
  redaction.
- Routing tests cover Single, Multi default, unavailable catalogs, and concurrent
  compatible admission behavior without provider-thread mutation.
