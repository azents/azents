---
title: "Kubernetes inference resolver identity"
created: 2026-11-05
tags: [inference, security, infra]
document_role: primary
document_type: adr
snapshot_id: resolver-261105
---

# Decisions

## D1 — Projected workload identity

For [resolver-261105/REQ-1–4](../requirements/resolver-261105-kubernetes-identity.md),
use a dedicated Proxy ServiceAccount and audience-bound projected token, reviewed
online with the Kubernetes TokenReview API. Bind the accepted identity to the
exact release namespace and ServiceAccount. Read the projected token for each
request so Kubernetes rotation requires no restart. Never cache authorization.

The requester selected the previously recommended Kubernetes service-identity
approach and delegated implementation details on 2026-11-05. Automatically
creating another shared Secret was rejected: it retains secret distribution and
rotation ownership. Fixed default secrets and unauthenticated authority are unsafe.

TokenReview needs cluster-scoped create permission; grant it only to a dedicated
API server ServiceAccount when this mode is enabled. The Proxy has no RBAC grants.
Kubernetes API unavailability fails the call, never selects shared-key auth.
Non-Kubernetes explicit shared-key configuration remains supported and exclusive.

This choice requires a Kubernetes API roundtrip for each authority request and
keeps private TLS authority routing as a deployment prerequisite. TokenReview
availability is not a product Admin setting. No database state or migration is added.
