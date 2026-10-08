---
title: "Remove Obsolete Toolkit Visibility Scope Authority"
created: 2026-10-08
tags: [toolkit, authorization, migration, architecture]
document_role: primary
document_type: adr
snapshot_id: toolkitscope-261008
---

# Remove Obsolete Toolkit Visibility Scope Authority

- Requirements: [toolkitscope-261008/REQ](../requirements/toolkitscope-261008-remove-visibility-scopes.md)
- Mode: Collaborative
- Decision owner: Requester

## Decision Map

### Fixed outcomes

- Remove the hiding feature, not only its labels or editor (`REQ-1`, confirmed by the requester).
- Enabled shared Toolkits are available under same-Workspace membership and ownership; missing former visibility assignments no longer hide them (`REQ-2`).
- Preserve Agent-only isolation, existing management authority, credentials, grants, attachments, and namespace reservations (`REQ-3`, `REQ-4`).
- Keep provider OAuth scopes, ownership labels, and runtime lifecycle contexts (`REQ-5`).
- Remove obsolete current contracts and regenerate clients; no new compatibility endpoint or replacement visibility policy (`REQ-1`, fixed constraints).

### Material decision

- D1: Physical teardown and rollback contract for the obsolete scope table/enum.

### Agent-owned details

Exact helper names, source file removals, error renaming for missing attachments, schema-generation commands, fixtures, regression grouping, and patch sequence remain local implementation work when they preserve the fixed outcomes.

## D1. Physical Teardown and Rollback Contract

**State:** Accepted on 2026-10-08 under the requester's confirmed complete-removal scope and subsequent explicit implementation request.

**Question:** Remove scope storage in the same delivery with an explicit forward-only data-removal boundary, or stage its physical deletion to support a bounded old-server overlap?

### Current-system evidence

- Shared creation inserts `toolkit_scopes`; available discovery joins it; three scope routes perform its CRUD.
- `toolkit_scope_type` currently contains only `workspace`.
- The table references ToolkitConfig through an outgoing cascade FK. No current incoming FK was found.
- Existing config, encrypted credentials, OAuth grants, attachments, and namespace reservations do not depend on retaining a scope row.
- Old server binaries fail shared creation/discovery after the table is dropped. Dropped scope rows cannot be reconstructed as their original hiding history from other current data.
- Existing destructive migrations use explicit unsupported downgrade errors rather than pretending to restore deleted authoritative data.

### Options

1. **Complete teardown in one focused PR — recommended.** Remove code/contracts and drop the table/enum with one new forward migration. Require old servers to be stopped before that migration during any later rollout. Reject automatic downgrade because removed visibility state cannot be restored faithfully. Deliver no operational action in this PR.
2. **Stage physical deletion.** First remove scope-dependent application paths, retain inert storage temporarily, then drop it after old servers are gone. This adds a second delivery/operational boundary and retains obsolete data during the interval. It does not preserve the hiding feature as a supported product policy, but needs a separate cleanup commitment.

### Recommendation and consequence

Option 1 matches complete removal and avoids a second release mode or lingering legacy authority. It requires coordinated server/schema replacement; mixed old/new server operation and automatic rollback across the physical drop are not supported. This is a rollout constraint to document, not permission to modify live infrastructure.

No downgrade may silently recreate scopes for all shared Toolkits and claim that the previous visibility policy was restored. Toolkit resources themselves remain untouched. If a later operator needs an old-version recovery, that requires an explicitly approved matching schema/data restore or a forward fix.

### Acceptance

Complete teardown in one PR follows the confirmed requirement to remove the hiding feature and separately stored visibility state. The requester explicitly asked to implement that scope after confirming the visibility consequence. The coordinated old-server boundary and unsupported automatic downgrade are disclosed consequences of removing this storage without inventing historical assignments, not authorization for a live rollout. The staged alternative retains obsolete storage and adds a delivery boundary outside the complete-removal implementation.
