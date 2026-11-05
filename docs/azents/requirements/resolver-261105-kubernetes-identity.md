---
title: "Kubernetes inference resolver authentication requirements"
created: 2026-11-05
tags: [inference, security, infra]
document_role: primary
document_type: requirements
snapshot_id: resolver-261105
---

# Kubernetes resolver authentication

## Primary system outcome

Enable the Kubernetes inference Proxy without asking an administrator to generate,
copy or register an internal resolver shared key.

## Requirements

- **REQ-1:** Kubernetes supplies renewable service identity automatically. Initial
  deployment and credential rotation need no human secret preparation.
- **REQ-2:** Only the intended resolver workload may reach inference authority;
  Agent-token authorization, private verified TLS and issuer separation remain.
  Wrong identity, audience, expired credentials and verification failure deny access.
- **REQ-3:** Kubernetes deployment has sensible identity defaults and narrow
  privileges. Internal credentials are not editable product settings in Admin.
  Existing product configuration remains owned by its existing Admin/public APIs.
- **REQ-4:** Preserve explicit non-Kubernetes shared-key deployments in this scoped
  change, without fallback between authentication methods. No automatic merge or
  live infrastructure mutation is included.

## Confirmation and scope

The requester selected Kubernetes first on 2026-11-05 and explicitly requested
implementation without further repeated questions. Implementation details are
assigned to the implementing agent. General-deployment automatic bootstrap and
new Admin product settings are outside this focused correction.
