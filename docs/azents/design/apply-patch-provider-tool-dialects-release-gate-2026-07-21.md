---
title: "Apply-patch provider tool dialects release gate - 2026-07-21"
created: 2026-07-21
updated: 2026-07-21
tags: [architecture, backend, engine, operations, safety]
---

# Apply-patch provider tool dialects release gate - 2026-07-21

## Purpose

This record closes the implementation delivery plan for
[ADR-0179: Select Provider-Specific Tool Dialects for Apply-Patch](../adr/0179-apply-patch-provider-tool-dialects.md).
It defines the operational barrier for any future bounded plaintext-custom cohort.
It does not authorize a cohort or change the source default: new plaintext-custom selection remains disabled.

## Permanent safety boundaries

- One prepared logical `apply_patch` declaration selects exactly one closed wire dialect.
- Disabling future custom selection only prevents new admission. It does not relabel, discard, or make existing custom lifecycle records unreadable.
- A provider, route, model, endpoint, or configuration change cannot convert an admitted call to the other dialect.
- No log, metric label, telemetry field, fixture, operational evidence, or release record may include raw custom input, patch/source/replacement content, path values, call IDs, or tool output.

## Deployment barrier

An operator may consider a bounded custom cohort only after all of the following are independently verified:

1. Every service and worker binary that can read delayed, recovered, compacted, exported, live, or historical client-tool events is at the dual-dialect reader floor.
2. Existing leases, delayed work, retries, and dead-letter records are drained or fenced to consumers at that floor.
3. The exact official provider route and model profile have reviewed evidence outside source input data.
4. The global/profile rollout control is disabled by default and can only reduce exposure.
5. Safe observability covers declaration selection, JSON fallback, failure category, continuation, and cancellation counts without sensitive labels.
6. The bounded enablement procedure receives independent operational review.

## Release decision

This source delivery is complete while custom selection remains disabled. A future cohort enablement requires a separate operational approval and evidence review; it is not part of source merge, CI success, or this document.

## Verification record

The completed delivery includes current behavior in the living specs and an implementation audit at
[ADR-0179 implementation audit](./adr-0179-implementation-audit-2026-07-21.md). The release gate preserves the audit's result: source behavior is default-disabled, and durable custom lifecycle support must remain deployed before any new custom selection is allowed.
