---
title: "Temporary Runtime Web Services Phase 2 — Runtime Transport"
created: 2026-09-12
tags: [runtime, web, implementation, planning, backend, protobuf]
---

# Phase Execution Plan

- Phase: `2/5 — Runtime transport`
- Branch/base: `feat/runtime-web-gateway-2-transport` → `feat/runtime-web-gateway-1-authority`
- PR boundary: Trusted, bounded Gateway-to-Control-to-Runner byte transport without public browser admission or Gateway HTTP serving.
- Inputs: Approved `web-260912` Requirements, ADR D5–D7 and Design revision 2; committed Phase 1 authority interfaces.
- Deliverables: Typed Gateway/Control, Control/Control and Runner/Control bidirectional protocols; owner-routed tunnel coordination; PostgreSQL route leases; Runner loopback HTTP/SSE/WebSocket client; generation/deadline/nonce fencing; bounded in-memory queues and focused multi-replica tests.
- Non-goals: Public Gateway HTTP parsing, browser identity/cookie exchange, CORS policy, Main Web confirmation/UI, Helm exposure and product E2E.
- Interfaces: `RuntimeWebGatewayTransport`, `RuntimeWebControlRelay`, and `RuntimeRunnerWeb.ConnectWeb`; transport frames carry bounded metadata/body chunks only and never durable approval authority.
- Approved Design mechanisms: `M10, M11, M12, M13, M14`.
- Authority references: `web-260912/REQ-7`, `REQ-8`, `REQ-11`, `REQ-13`; ADR-D5, ADR-D6, ADR-D7; approved Design revision 2.
- Design delta: `None`.
- Removal obligations: Do not route bytes through Terminal, File Transfer, ordinary Runtime operation replies, Redis-only authority, transcripts or object storage. Do not add public HTTP listeners or browser auth behavior in this phase.
- Absence verification: Search protocol, Control and Runner diffs for Terminal/File Transfer reuse, durable body/chunk fields, public HTTP listeners, browser-cookie logic and Runtime-provided relay addresses; focused tests assert no application-byte persistence or automatic replay.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Protocol contracts | root | `proto/azents/runtime_control/v1/**`, `python/libs/azents-runtime-control/**` | Phase 1 IDs and generation fences | Generated bounded bidirectional stream messages and service stubs | protobuf generation, shared-library Ruff/type/tests |
| Runner loopback transport | root | `python/apps/azents-runtime-runner/**` | Generated Runner protocol | HTTP/SSE/WebSocket-capable loopback client with byte/deadline bounds | Runner unit/integration tests |
| Control ownership and relay | root | `python/apps/azents/src/azents/runtime/**`, `repos/runtime_web/**`, `services/runtime_web/**` | Protocol and Phase 1 route table | Owner registry, PostgreSQL route lease and one-hop inter-Control relay | server unit and forced cross-replica integration tests |
| Trusted Gateway transport edge | root | `python/apps/azents/src/azents/runtime/**` | Owner relay | Internal authenticated Gateway-facing stream without public HTTP admission | metadata/auth/generation/timeout tests |

- Integration order: protocol contracts and generated code → Runner loopback client → Control owner registry/route lease → inter-Control relay → Gateway-facing trusted transport service → focused loss/backpressure/generation tests.
- Direct implementation: root agent owns all implementation and integration. Delegation is limited to final read-only review.
- Independent review: verify one-hop owner routing, authentication boundaries, no byte persistence, exact generation/deadline fencing, bounded queues/timeouts, ambiguous mutation non-replay and Phase 2 scope.
- Final validation: protobuf generation; Python Ruff/format/type/tests for shared protocol, server and Runner; targeted two-Control relay integration; pre-commit; stacked PR creation with base Phase 1.
- Scope-drift check: Every changed contract must trace to M10–M14; reject Gateway browser admission, UI, Helm exposure, new approval authority, persisted application bytes, transport replay or Runtime-supplied routing.
- Context checkpoint: Phase completes when a trusted test client can stream HTTP/SSE/WebSocket-shaped frames through owner Control to the exact current Runner generation, including forced cross-replica rendezvous, without exposing a public Gateway listener.
