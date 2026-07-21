---
title: "xAI Grok OAuth Provider Historical Decision Reconstruction"
created: 2026-07-10
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: oauth-260710
historical_reconstruction: true
migration_source: "docs/azents/design/xai-oauth-provider.md"
---

# xAI Grok OAuth Provider Historical Decision Reconstruction

- Snapshot: `oauth-260710`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/xai-oauth-provider.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### oauth-260710/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: CI policy

Run Python unit tests for xAI OAuth service, credential mapping, model catalog projection, and runtime mapping. Run TypeScript typecheck after generated client updates and frontend changes. Run E2E only when the mock-provider fixture is available in this implementation phase; otherwise record it as planned follow-up validation.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
