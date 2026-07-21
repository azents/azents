---
title: "External Platform Account Linking Historical Decision Reconstruction"
created: 2026-03-15
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: account-260315
historical_reconstruction: true
migration_source: "docs/azents/design/account-linking.md"
---

# External Platform Account Linking Historical Decision Reconstruction

- Snapshot: `account-260315`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/account-linking.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### account-260315/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Mapping Policy

| Direction | Allowed | Rationale |
|------|------|------|
| 1 nointern user → Discord + Slack simultaneously | ✅ | natural multi-platform scenario |
| 1 platform account → 1 nointern user (per installation) | ✅ | `(installation_id, platform_user_id)` unique constraint |
| 1 platform account → N nointern users | ❌ | blocked by above unique constraint |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
