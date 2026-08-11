---
title: "Runtime Profile Deletion"
created: 2026-08-11
tags: [runtime, profile, workspace, persistence, architecture]
document_role: primary
document_type: adr
snapshot_id: profile-260811
---

# Runtime Profile Deletion

- Snapshot: `profile-260811`
- Document reference: `profile-260811/ADR`
- Requirements: [Runtime Profile Deletion Requirements](../requirements/profile-260811-runtime-profile-deletion.md) (`profile-260811/REQ`)

## Decision Map

- [x] `profile-260811/ADR-D1` — Replace immutable configuration revisions with one current configuration state per Runtime.
- [x] `profile-260811/ADR-D2` — Fence configuration with a monotonic Runtime-scoped sequence, digest, and Runtime generations.
- [x] `profile-260811/ADR-D3` — Hard delete Workspace Runtime Profiles and clear current selection references without fallback.
- [x] `profile-260811/ADR-D4` — Preserve an already running Runtime until explicit replacement, stop, or terminal deletion.
- [x] `profile-260811/ADR-D5` — Keep hard deletion owner-only and atomically committed in PostgreSQL.
- [x] `profile-260811/ADR-D6` — Remove revision-shaped contracts and state rather than retain a compatibility or tombstone model.

## Context

The current Runtime Profile system persists every resolved Runtime configuration as an immutable `runtime_configuration_revisions` row. Agent Runtime desired and applied pointers, Provider and Runner acknowledgement, lifecycle dispatch, Runtime recreation items, APIs, and UI projections use the revision identifier as exact configuration evidence.

The revision record contains useful current desired or applied state, but the product does not require a permanent history of superseded Runtime configurations. Rows therefore outlive their lifecycle purpose and retain restrictive foreign keys to Workspace Runtime Profiles, infrastructure Profiles, Provider capability revisions, and Agent Runtimes. This prevents permanent Profile deletion and makes stale configuration cleanup depend on historical-record preservation that the requester explicitly rejected.

A configuration identity is still required to reject late Provider and Runner reports. Digest alone is insufficient because a configuration document may change from A to B and later return to A while a late acknowledgement for the first A remains in flight.

## Decisions

### profile-260811/ADR-D1: Replace immutable configuration revisions with one current configuration state per Runtime

**Affected requirements:** `profile-260811/REQ-4`, `REQ-6`

Each managed Runtime owns one current configuration-state record with one desired slot and one applied slot. The desired slot is overwritten whenever the authoritative target changes. The applied slot is overwritten only after exact Provider and Runner acknowledgement promotes the desired target. No superseded configuration row is retained as product history.

Configuration state is lifecycle state, not audit state. Profile, infrastructure, capability, policy, source-trace, resolved document, and acknowledgement data are retained only while present in the current desired or applied slot.

A separate one-to-one state record is used instead of expanding the frequently updated Agent Runtime lifecycle row with large desired and applied JSON documents.

### profile-260811/ADR-D2: Fence configuration with a monotonic Runtime-scoped sequence, digest, and Runtime generations

**Affected requirements:** `profile-260811/REQ-5`

Every authoritative desired target increments a Runtime-scoped `configuration_sequence`. Provider and Runner configuration evidence contains the exact configuration sequence, digest, and target desired generation. Admission additionally remains fenced by the authenticated logical Runtime and current Provider or Runner generation.

The accepted tuple is:

```text
runtime_id
runtime_desired_generation
configuration_sequence
configuration_digest
provider_generation or runner_generation
```

Returning to a previously used configuration document increments the sequence and cannot accept evidence from its earlier use. Digest remains document-integrity evidence and does not become the sole freshness authority.

### profile-260811/ADR-D3: Hard delete Workspace Runtime Profiles and clear current selection references without fallback

**Affected requirements:** `profile-260811/REQ-1`, `REQ-2`, `REQ-8`

Hard deletion physically removes the `workspace_runtime_profiles` row. In the same authoritative operation, a matching Workspace default is cleared and every matching Agent selection is cleared with an advanced selection version. No other Profile is selected automatically.

Affected Runtimes receive a new blocked or unconfigured desired state. Existing applied state is not a live Profile reference and contains no foreign key that prevents Profile deletion.

Profile display names become reusable after deletion. No Profile tombstone, archived lifecycle, or restorable deleted record is created.

### profile-260811/ADR-D4: Preserve an already running Runtime until explicit replacement, stop, or terminal deletion

**Affected requirements:** `profile-260811/REQ-3`, `REQ-6`, `REQ-8`

Deleting the selected Profile does not terminate an already running Runtime. Its applied configuration remains only as current physical-Runtime state. Configuration-requiring lifecycle and Runner operations are unavailable until an authorized actor selects a replacement Profile.

Stop and terminal deletion remain available. When a replacement Runtime becomes exactly applied, its configuration overwrites the prior applied slot. Terminal deletion removes the remaining configuration state. Profile deletion never resets or deletes Agent Workspace storage.

### profile-260811/ADR-D5: Keep hard deletion owner-only and atomically committed in PostgreSQL

**Affected requirements:** `profile-260811/REQ-7`

Workspace Runtime Profile hard deletion requires Workspace Owner authority distinct from ordinary Runtime Profile write authority. The operation locks the Profile, clears the Workspace default and Agent selections, invalidates or supersedes affected reconciliation and recreation work, records current desired-state changes, and deletes the Profile in one PostgreSQL transaction.

Set-based updates and durable reconciliation tasks bound downstream Runtime convergence. Redis is not involved in correctness. A later scale finding may replace the single transaction with one durable deletion operation, but it may not create a second product behavior or expose a partially deleted Profile.

### profile-260811/ADR-D6: Remove revision-shaped contracts and state rather than retain a compatibility or tombstone model

**Affected requirements:** `profile-260811/REQ-1`, `REQ-4`, `REQ-5`, `REQ-6`

The Runtime configuration revision table, desired/applied revision foreign keys, recreation-item expected revision foreign key, revision API models, revision UI terminology, and revision-specific tests are removed.

Provider and Runner protocol evidence is expressed as configuration sequence rather than retaining `revision_id` as a long-lived compatibility alias. Delivery coordinates the server, shared control contract, Providers, and Runners as one protocol cutover. Old protocol participants fail closed and do not create a legacy mode.

Completed operational results may retain bounded outcome metadata under their existing retention policy, but they do not retain full Runtime configuration documents or recreate a configuration revision history.

## Rejected Alternatives

### Retain revisions and add garbage collection

Rejected because the revision entity and its foreign keys remain the authority boundary, continue to complicate hard deletion, and preserve an unnecessary historical model even if most rows are later collected.

### Use configuration digest as the only evidence identity

Rejected because A-to-B-to-A changes could accept a late acknowledgement for the first A.

### Cascade-delete affected Runtimes and revisions

Rejected because Profile management would terminate running work and unnecessarily destroy Runtime continuity and Agent Workspace access.

### Archive or disable instead of hard delete

Rejected because the requester requires permanent deletion and reuse of the removed Profile's name.

### Retain deleted Profile tombstones

Rejected because current desired and applied configuration state is sufficient for Runtime convergence, while a Profile tombstone would preserve the deleted entity under another name.

## Consequences

- Runtime configuration persistence becomes bounded by the number of managed Runtimes rather than the number of historical configuration changes.
- Runtime Profile deletion no longer depends on historical configuration foreign keys.
- Existing APIs, generated clients, web technical details, protocol messages, migrations, and focused tests require coordinated replacement.
- Current Runtime continuity is preserved, but a deleted selection leaves the Agent intentionally unconfigured until explicit recovery.
- Rolling protocol compatibility is not retained; deployment must coordinate updated control-plane, Provider, and Runner components and fail closed during mismatch.
- Existing implemented Runtime Profile snapshot documents remain immutable historical records; current Specs change only after implementation and validation.
