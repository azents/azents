---
title: "Discord Agent App Routing phase 5: Gateway Worker"
created: 2026-07-26
tags: [discord, external-channel, gateway, worker, rollout]
document_type: implementation-plan
snapshot_id: discord-260726
---

# Discord Agent App Routing phase 5: Gateway Worker

## Scope

This phase introduces the dedicated, lease-fenced Discord Gateway Worker role. It owns
Gateway protocol state only: Hello, Identify, Resume, heartbeat, reconnect, resumable
checkpoint state, and visible gap state.

## Source documents

- Requirements: [discord-260726/REQ](../requirements/discord-260726-agent-app-routing.md)
- ADR: [discord-260726/ADR-D1](../adr/discord-260726-agent-app-routing.md)
- Design: [discord-260726/DESIGN](../design/discord-260726-agent-app-routing.md)
- Stack plan: [Discord Agent App Routing Implementation Plan](discord-agent-app-routing-implementation-plan.md)

## Delivery boundaries

- Use `external_channel_ingress_leases` as the only Discord Gateway ownership record.
- Claim, renew, release, gap, configuration access, and checkpoint writes require the
  current lease owner and generation plus matching connection configuration and App
  claim generations.
- Decrypt a Bot Token only after the Worker verifies all current ownership fences.
- Encrypt resumable Gateway session state before writing it to PostgreSQL.
- Keep the role opt-in through the existing Discord rollout gate and the Helm
  `server.discordGateway.enabled` deployment gate.
- Deploy the Gateway Worker separately from the Agent Worker and API processes.

## Exclusions

- No Ed25519 interaction endpoint, interaction acknowledgement, component routing, or
  thread provisioning. Those belong to phase 6.
- No message normalization, history hydration, attachment processing, or canonical
  message admission. Those belong to phase 7.
- No outbound message delivery, Web UI, real Discord credentials, or live provider E2E.

## Verification

- Deterministic Gateway protocol tests cover Identify, READY checkpoint persistence,
  Resume, sequence advancement, invalid sessions, and malformed Dispatch rejection.
- Backend Ruff and Pyright validate protocol, worker, and repository wiring.
- Helm render tests validate that the Gateway deployment is opt-in and uses its own
  worker command and health port when a Helm binary is available.
