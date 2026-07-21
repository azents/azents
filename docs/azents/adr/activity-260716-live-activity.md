---
title: "Provider Tool Live Activity Historical Decision Reconstruction"
created: 2026-07-16
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: activity-260716
historical_reconstruction: true
migration_source: "docs/azents/design/provider-tool-live-activity.md"
---

# Provider Tool Live Activity Historical Decision Reconstruction

- Snapshot: `activity-260716`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/provider-tool-live-activity.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### activity-260716/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: CI policy

Required CI uses deterministic fixtures only and must fail on missing expected lifecycle observations, duplicate cards, stale retry activity, or durable/live handoff regression. Optional live-provider checks skip when credentials are absent and fail when credentials are present but the asserted provider behavior changes.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
