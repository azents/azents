---
title: "Slack/Discord/Scheduled Event Subscription Migration Historical Decision Reconstruction"
created: 2026-05-08
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: event-260508
historical_reconstruction: true
migration_source: "docs/azents/design/event-subscription-routing-2026-05-08.md"
---

# Slack/Discord/Scheduled Event Subscription Migration Historical Decision Reconstruction

- Snapshot: `event-260508`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/event-subscription-routing-2026-05-08.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### event-260508/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: 1. Output policy

**Decision: keep explicit output tool target**

Do not restore Slack/Discord thread/channel auto-reply adapter. When Agent needs to answer on external platform, it explicitly calls Slack/Discord toolkit target.

With this decision, event subscription owns only input routing, and output routing is separated into tool contract.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
