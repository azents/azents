---
title: "User & WorkspaceUser CRUD Document Historical Decision Reconstruction"
created: 2026-02-12
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: crud-260212
historical_reconstruction: true
migration_source: "docs/azents/design/user-crud.md"
---

# User & WorkspaceUser CRUD Document Historical Decision Reconstruction

- Snapshot: `crud-260212`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/user-crud.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### crud-260212/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Design Decisions

| Item | Decision | Rationale |
|------|------|------|
| User creation method | Automatically created during email verification | No explicit signup flow needed |
| Email unique scope | Global UNIQUE | Prevent multiple accounts with same email |
| User-Workspace relationship | N:M through WorkspaceUser | One person can participate in multiple organizations |
| WorkspaceUser unique | (workspace_id, user_id) | Prevent duplicate participation in same workspace |
| locale default | `ko-KR` | First target market is Korea |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
