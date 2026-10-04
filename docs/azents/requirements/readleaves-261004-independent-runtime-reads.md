---
title: "Independent Runtime Reads Requirements"
created: 2026-10-04
tags: [concurrency, runtime, read-paths]
document_role: primary
document_type: requirements
snapshot_id: readleaves-261004
---

# Independent Runtime Reads Requirements

- Snapshot: `readleaves-261004`

## Primary System Outcome

Independent descriptive reads of Provider revisions, Runtime Profiles and retained
configuration state tolerate lag without serializing against writers.

## Requirements

### REQ-1. Read-only independent getters

Immutable contract/configuration revision and infrastructure/workspace Profile and
retained configuration-state lookups require only read capability.

**Acceptance criteria**

- These getters have no row-lock option and work in a DB read-only transaction.
- Workspace/resource predicates and existing result shapes remain intact.
- A reader returns committed evidence while a writer holds or changes the row;
  an absent reference remains an absent result.

### REQ-2. Narrow mutation guarantees remain

Do not remove claim, one-time authentication consumption or critical obsolete-result
write fencing as part of this leaf-read phase.

**Acceptance criteria**

- Actual Runtime/configuration attachment and evidence mutation retain their
  version/generation validation and necessary mutation serialization.
- No cache authority, retry mode or new public API behavior is introduced.

## Scope and Confirmation

This is the first independent-getter phase of the requester-approved defensive
lock-removal sequence. The requester confirmed lag-tolerant reads and the three
mutation exceptions on 2026-10-04, then requested implementation after the
foundation migration. Broad owner gates, model preparation, catalog/Memory and
management/lifecycle phases remain separate work. No live deployment is authorized.
