---
title: "Runtime Profile Constraint Audit"
created: 2026-07-31
tags: [runtime, provider, profile, validation, audit]
document_role: supporting
document_type: supporting-audit
---

# Runtime Profile Constraint Audit

This note preserves the constraint audit that was paused to address the Home Runtime outage. The
open findings below are not an implementation plan and are not marked as fixed.

## Incident findings fixed in the accompanying change

1. The Profile cutover migration stored `legacy-provider-default` as a compatibility sentinel for
   the Provider-owned storage class. The Kubernetes Provider treated it as a literal Kubernetes
   `StorageClass`, causing immutable PVC patch failures. The Provider must lower this sentinel to
   its configured legacy storage class and PVC size.
2. Kubernetes Pod watch reports downgraded every Ready Pod to `starting` because the watch path did
   not carry trusted NetworkPolicy evidence. These synthetic reports could race with a verified
   command report and leave the Runtime indefinitely preparing. A verified command-policy cache
   now permits Ready watch reports only while both configuration evidence and the live
   NetworkPolicy still match; Provider restart and policy drift remain fail-closed.

## Confirmed excessive constraints

1. `RuntimeProviderCapabilityContract` requires every lifecycle operation even though the Provider
   requirements allow a valid ephemeral Provider to implement only the mandatory lifecycle core.
   The cutover migration duplicates the same all-operations check.
2. `DockerContainerProfileSpecV1.network_name` is nullable and the migration creates `null`, while
   the Docker Provider rejects `null` immediately before container creation.
3. Kubernetes Profile validation rejects empty node-selector label values and an empty toleration
   key with `operator=Exists`, although Kubernetes supports both representations. If this is an
   intentional safe subset, the contract and Admin surface need to state it explicitly.

## Adjacent under-validation

1. Helm `extraEgress` accepts arbitrary rule objects, but the Kubernetes Provider drops unsupported
   selector and port fields. A `matchExpressions`-only selector is lowered to an empty selector and
   can broaden the destination set. Unsupported fields must be implemented or rejected fail-closed.
2. The Admin Profile form coerces unknown toleration operators to `Equal` and unknown effects to
   `null` instead of rejecting the input, which can silently change Platform intent.

## Validation gaps

- The 2026-07-31 Runtime Profile validation report did not include a connected Kubernetes journey.
- No regression crosses migration-generated Docker `network_name=null` into the Docker Provider.
- No regression covers full Kubernetes `LabelSelector` or `NetworkPolicyPort` shapes in
  `extraEgress`.
