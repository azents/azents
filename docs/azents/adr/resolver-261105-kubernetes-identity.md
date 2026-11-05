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

## D2 — Preserve the configured server workload identity

Review identified that replacing the API server ServiceAccount would discard
consumer cloud workload-identity associations and externally managed accounts.
Keep `server.serviceAccount` unchanged and bind resolver TokenReview-create to
that configured server identity instead. This supersedes D1's dedicated API
ServiceAccount mechanism, not its projected Proxy identity or verification.
The account may be shared with other server workloads, which consequently also
have TokenReview-create permission. TokenReview cannot issue or modify tokens;
the exact Proxy subject and audience checks remain mandatory and unchanged.
The Proxy account still receives no Kubernetes API grants. Requiring new consumer
cloud associations or silently copying only some account annotations was rejected.
