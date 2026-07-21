---
title: "Apply-patch provider tool dialects release gate - 2026-07-21"
created: 2026-07-21
updated: 2026-07-21
tags: [architecture, backend, engine, operations, safety]
---

# Apply-patch provider tool dialects release gate - 2026-07-21

## Purpose

This record closes the implementation delivery plan for
[ADR-0179: Select Provider-Specific Tool Dialects for Apply-Patch](../adr/0179-apply-patch-provider-tool-dialects.md)
and its rollout-control correction in
[ADR-0180: Remove Percentage Rollout from Apply-Patch Custom Selection](../adr/0180-remove-apply-patch-custom-rollout.md).
It records the deployment constraints for the exact reviewed plaintext-custom route.
It does not add runtime configuration, a percentage, a cohort, or a feature flag.

## Permanent safety boundaries

- One prepared logical `apply_patch` declaration selects exactly one closed wire dialect.
- The exact reviewed provider, API-key authentication mode, Responses adapter, official endpoint,
  and model determine plaintext-custom selection. Session, tenant, and runtime configuration do not.
- A provider, route, model, endpoint, or configuration change cannot convert an admitted call to the
  other dialect.
- No log, metric label, telemetry field, fixture, operational evidence, or release record may include
  raw custom input, patch/source/replacement content, path values, call IDs, or tool output.

## Deployment requirements

The source release requires all of the following:

1. Every service and worker binary that can read delayed, recovered, compacted, exported, live, or
   historical client-tool events is at the dual-dialect reader floor.
2. Existing leases, delayed work, retries, and dead-letter records are drained or fenced to consumers
   at that floor.
3. The exact official provider route and model profile have reviewed evidence outside source input data.
4. Safe observability covers declaration selection, JSON fallback, failure category, continuation, and
   cancellation counts without sensitive labels.

## Release decision

There is no percentage rollout or feature flag for plaintext-custom `apply_patch`. The exact reviewed
route selects plaintext custom directly; every other route uses its independently verified JSON-function
fallback or omits `apply_patch`. Expanding plaintext-custom support requires a reviewed code change and
full lifecycle evidence.

## Verification record

The completed delivery includes current behavior in the living specs and an implementation audit at
[ADR-0179 implementation audit](./adr-0179-implementation-audit-2026-07-21.md). The release gate
preserves the durable dual-dialect reader requirement while removing rollout configuration from provider
dialect selection.
