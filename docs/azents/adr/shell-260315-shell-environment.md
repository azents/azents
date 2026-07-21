---
title: "ShellEnvironment Historical Decision Reconstruction"
created: 2026-03-15
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: shell-260315
historical_reconstruction: true
migration_source: "docs/azents/design/shell-environment.md"
---

# ShellEnvironment Historical Decision Reconstruction

- Snapshot: `shell-260315`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/shell-environment.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### shell-260315/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Protection Policy

| Policy | Description | Implementation location |
|------|------|----------|
| **Cannot delete** | reject deletion for env with `is_default=True` | Repository layer (lock + check) |
| **Config editable** | allow domain setting change on default env | Service layer (return affected agent count) |
| **Default change allowed** | designate another env as new default | Service layer |
| **Guarantee WORKSPACE scope** | default env must have WORKSPACE scope | Service layer |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
