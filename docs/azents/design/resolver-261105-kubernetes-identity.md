---
title: "Kubernetes inference resolver authentication design"
created: 2026-11-05
tags: [inference, security, infra]
document_role: primary
document_type: design
snapshot_id: resolver-261105
---

# Design

## Design Authority

Revision r1; authority: [Requirements](../requirements/resolver-261105-kubernetes-identity.md)
and [ADR-D1](../adr/resolver-261105-kubernetes-identity.md).

- M1 (decided, ADR-D1): projected Proxy token with audience `azents-llm-resolver`;
  read per call and verify through bounded online TokenReview, exact audience and
  namespace/ServiceAccount subject. Authentication precedes Agent lookup.
- M2 (derived, REQ-2 and ADR-D1): fail closed with no method fallback, sanitized
  errors, no token/body logs, unchanged verified authority TLS and Agent checks.
- M3 (decided, ADR-D1): chart defaults to workload identity, dedicated Proxy/API
  ServiceAccounts, TokenReview-create-only API role, projected token file only in
  Proxy; existing explicit shared-key mode for non-Kubernetes consumers remains.

## Removal and Replacement

Replace resolver shared-key references in the default Kubernetes path with M1/M3.
Remove the mandatory manual secret-preparation instructions for this path. Existing
shared-key tests remain relevant to the explicitly selected non-Kubernetes mode.
Home activation must use a chart/image containing this implementation; no live
mutation or unverified old-chart enablement. No data migration or credential copies.

## Failure and lifecycle

Kubernetes manages projected token lifetime/rotation. Missing/unreadable tokens,
wrong identity/audience, revoked/expired tokens and API failures deny the call.
Each verification owns and closes its SDK client, bounded by a request timeout.
Restart/replica changes carry no locally cached authority. Rollback requires
returning to explicit existing-secret deployment configuration; never auto-fallback.

## Test Strategy

The existing assembled Proxy journey remains the product E2E; exercise workload
identity at the real HTTP route and Proxy HTTP transport with Kubernetes API as
the external boundary fixture. Verify token rotation, exact subject/audience,
rejected verification, TLS/no redirects and Agent lookup ordering. Render real
Helm manifests to verify projection and narrow RBAC. Run relevant full unit suites,
static checks and final-SHA CI. No extra E2E combinations or paid inference/login.
Live rollout validation is pending deployment authorization and published images;
render/unit evidence is not live authentication proof.

## Feasibility

Feasible: both services already have a private authority channel; backend already
uses the official Kubernetes async SDK for TokenReview. No new dependency or DB
schema is necessary. Chart owns workload manifests and can derive exact identity.
## Design Approval

Mode: scoped implementation delegation; decision owner: implementing agent.
The requester selected Kubernetes first and delegated implementation details on
2026-11-05; approved scope r1, authority IDs M1, M2, M3, is the focused correction
described above.
