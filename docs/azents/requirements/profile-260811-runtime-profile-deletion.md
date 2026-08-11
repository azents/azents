---
title: "Runtime Profile Deletion Requirements"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, profile, workspace, lifecycle]
document_role: primary
document_type: requirements
snapshot_id: profile-260811
---

# Runtime Profile Deletion Requirements

- Snapshot: `profile-260811`
- Document reference: `profile-260811/REQ`

## Problem

Workspace Runtime Profiles cannot be permanently deleted. The current Runtime configuration model also retains immutable configuration revisions after they stop being relevant to the current or replacement Runtime. Profile deletion is therefore blocked by references whose lifetime exceeds the product need.

Workspace owners need to permanently remove a Runtime Profile without automatically substituting another Profile, deleting Agent Workspace data, or interrupting an already running Runtime. Runtime configuration state must exist only while it is needed to drive or describe the current Runtime lifecycle.

## Primary Actor

Workspace Owner.

## Primary Scenario

A Workspace Owner permanently deletes a Runtime Profile that is the Workspace default, is selected by one or more Agents, and has running Runtimes. The Profile immediately disappears from management and selection surfaces. The Workspace default and affected Agent selections become unconfigured without fallback. Existing running Runtimes continue with their currently applied configuration, but configuration-requiring lifecycle and Runner operations remain unavailable until an owner or Agent administrator selects another Profile. When a replacement Runtime configuration becomes applied, or when the Runtime is terminally deleted, obsolete configuration state is removed.

## Supporting Scenarios

- An owner deletes a Profile that has never been selected and can reuse its display name for a new Profile.
- An affected Agent selects a replacement Profile and recreates its Runtime without resetting or deleting Agent Workspace storage.
- A late Provider or Runner report for an overwritten configuration target is rejected without restoring stale state.
- A terminal Runtime deletion removes all remaining configuration state for that Runtime.

## Goals

- Permanently delete Workspace Runtime Profile records regardless of current references.
- Remove Profile selection authority without fallback or substitution.
- Preserve already running Runtime and Agent Workspace continuity until explicit replacement or terminal deletion.
- Retain only current desired and applied Runtime configuration state.
- Remove obsolete configuration state promptly at lifecycle boundaries.
- Preserve exact stale-report fencing without permanent configuration revisions.

## Non-Goals

- Deleting Provider-owned infrastructure Profiles.
- Automatically choosing a replacement Profile.
- Resetting or deleting Agent Workspace storage during Profile deletion.
- Retaining a historical catalog of Runtime configuration revisions.
- Preserving deleted Profile documents through tombstones or archive lifecycle states.
- Deleting Agents, Sessions, or running Runtimes solely because their Profile was deleted.

## Requirements

### REQ-1. Permanent Runtime Profile deletion

A Workspace Owner must be able to permanently delete a Workspace Runtime Profile.

**Acceptance criteria**

- The Profile record is physically removed from authoritative persistence.
- Subsequent list and get operations do not return the deleted Profile.
- The deleted Profile cannot be selected, updated, restored, or used as a recreation target.
- The deleted Profile's display name may be reused by a newly created Profile.

### REQ-2. Exact reference removal without fallback

Deleting a Runtime Profile must remove its current Workspace and Agent selection authority without selecting a substitute.

**Acceptance criteria**

- A matching Workspace default becomes unconfigured.
- Every affected Agent selection becomes unconfigured and advances its selection version.
- No Workspace default, Provider default, or other Profile is automatically substituted.
- Concurrent selection and deletion settle to one exact committed result without a dangling current reference.

### REQ-3. Running Runtime continuity

Deleting a selected Profile must not by itself terminate an already running Runtime or remove its Agent Workspace storage.

**Acceptance criteria**

- The running Runtime may continue using its currently applied configuration.
- Stop and terminal Runtime deletion remain available.
- Create, start, restart, reset, recreate, and Runner-dependent operations that require a current Profile are unavailable until a replacement Profile is selected.
- Profile deletion does not reset, erase, or relocate Agent Workspace storage.

### REQ-4. Current configuration state only

Runtime configuration persistence must retain only the state required for the current desired target and the currently applied Runtime.

**Acceptance criteria**

- A Runtime has at most one desired configuration state and one applied configuration state.
- Creating a new desired target removes the previous desired state.
- Promoting a new applied target removes the previous applied state.
- Terminal Runtime deletion removes the Runtime's remaining configuration state.
- The product exposes no permanent Runtime configuration revision history.

### REQ-5. Exact configuration fencing

Removing configuration revisions must not weaken rejection of stale Provider or Runner evidence.

**Acceptance criteria**

- Every desired configuration target has an exact freshness identity within its Runtime.
- Provider and Runner acknowledgement is accepted only for the exact current Runtime generation, configuration identity, and digest.
- Returning to a previously used configuration document does not reuse authority from its earlier use.
- An overwritten or deleted configuration target cannot become applied.

### REQ-6. Stale state removal

Obsolete Runtime configuration state must be removed at the earliest lifecycle boundary that no longer requires it.

**Acceptance criteria**

- Overwritten desired state is removed immediately.
- The previous applied state remains only until the replacement target is exactly applied or the prior Runtime is terminally deleted.
- Completed replacement does not retain the superseded configuration document as product history.
- Configuration state is removed with its owning Runtime.

### REQ-7. Controlled destructive authority

Runtime Profile hard deletion must be a bounded Workspace-owner operation with explicit impact visibility.

**Acceptance criteria**

- Workspace Managers and Members cannot hard delete Runtime Profiles.
- The operation reports how many Agent selections, running Runtimes, and active recreation operations are affected.
- The operation is atomic from management and selection surfaces: the Profile is either current or absent, never partially deleted.
- Failures do not produce an implicit fallback, partial selection rewrite, or partial Profile deletion.

### REQ-8. Replacement recovery

Affected Agents must recover through explicit replacement Profile selection.

**Acceptance criteria**

- Selecting a replacement Profile creates a new exact desired configuration target.
- Existing Agent Workspace storage remains available after Runtime recreation.
- The replacement target becomes applied only after exact Provider and Runner evidence.
- The former applied configuration is removed after replacement promotion.

## Fixed Constraints

- PostgreSQL remains authoritative for Profile deletion, current configuration state, reconciliation, and recreation correctness.
- Redis availability or persistence is not required for correctness.
- Profile deletion never creates fallback or compatibility selection behavior.
- Existing implemented Requirements, ADRs, and Designs remain immutable historical records.
- Runtime and Provider reports remain untrusted and must be generation-fenced.

## Open Assumptions

- The current Provider and Runner configuration evidence contract can express exact target freshness without retaining permanent configuration history.
- A synchronous destructive operation is sufficient for ordinary Workspace Profile fan-out; implementation may use a durable bounded operation if verified scale requires it.

## Confirmation

Confirmed by the requester on 2026-08-11. The requester explicitly required hard deletion, rejected permanent configuration revision retention, required stale configuration removal after Runtime replacement, and selected continuity for already running Runtimes.
