---
title: "Runtime Application Header Forwarding Decisions"
created: 2026-10-07
tags: [runtime, gateway, security]
document_role: primary
document_type: adr
snapshot_id: headers-261007
---

# Runtime Application Header Forwarding Decisions

Requirements: [headers-261007/REQ](../requirements/headers-261007-runtime-application-forwarding.md)

## ADR-D1. Consume proxy-owned fields and preserve application fields

The requester selected this boundary on 2026-10-07 for REQ-1 and REQ-2.
Consume exact platform cookie names, standard hop-by-hop fields, fields nominated
by Connection, local Host routing, and regenerated WebSocket handshake fields.
Forward all remaining application fields, preserving duplicate values and order.
Origin/Referer are application fields, not proxy authentication authority.

Rejected: drop all cookies; broadly filter application header/cookie prefixes;
rewrite application origins; omit all application headers on WebSocket 101.
These alternatives break the approved application contracts.
Also rejected: forwarding platform credentials or connection-local handshake
keys unchanged, which violates retained platform/transport responsibilities.

Risks: applications receive their own cookie/authorization secrets and must protect
them; app-controlled cookie names cannot collide with exact platform names;
Connection may intentionally nominate otherwise normal fields for hop consumption.
App CSRF/CORS remain app-owned under the prior transparent-policy decision.
No persisted-state or configuration changes are required.

## Coverage clarification for ADR-D1

The earlier Service-Worker/worker-destination ingress rejection is an application
browser-lifecycle policy, not proxy transport or authentication consumption.
Removing it follows REQ-1 and the already-selected ADR-D1 boundary; it introduces
no additional transport mechanism or authentication mode. Retaining it would be
an exception to the requester's explicit forwarding rule.

The original initial-release restriction was coupled to forced app no-store,
which the preceding transparency change removed. A Worker on a stable service
origin can persist and intercept app responses after re-exposure or app
replacement. That application-origin code/data-persistence risk is real and
app-owned. Distinct Main Web/broker origins, HttpOnly cookie visibility, and every
Gateway network authority check remain separate platform boundaries.
