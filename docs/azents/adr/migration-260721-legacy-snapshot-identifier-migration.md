---
title: "Legacy Snapshot Identifier Migration"
created: 2026-07-21
tags: [documentation, migration, architecture]
document_role: primary
document_type: adr
snapshot_id: migration-260721
---

# Legacy Snapshot Identifier Migration

- Snapshot: `migration-260721`
- Requirements: `migration-260721/REQ`
- Requester confirmation: approved on Tuesday, July 21, 2026 (KST).

## Status

Accepted for implementation on the migration branch.

## Decisions

### migration-260721/ADR-D1 — Reconstruct historical Requirements with provenance

Only explicit source ADR/Design text is recoverable. Unknown intent and absent confirmation remain explicit unknowns.

### migration-260721/ADR-D2 — Migrate primary snapshots and classify supporting records

One-to-one pairs and independent Design-only records use shared dated basenames. Many-to-one, secondary, audit, validation, QA, plan, phase, and scenario records retain descriptive names with explicit supporting roles.

### migration-260721/ADR-D3 — Resolve references without guessing

Contextually resolvable numeric references become typed snapshot references. Irreducible references point to exact anchors in the committed historical ambiguity manifest.

### migration-260721/ADR-D4 — Remove generic legacy acceptance after verification

The validator enforces canonical primary snapshots, explicit supporting exceptions, sibling relationships, implementation-date parity, and reference cleanliness.
