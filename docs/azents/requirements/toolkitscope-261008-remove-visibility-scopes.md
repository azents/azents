---
title: "Remove Obsolete Toolkit Visibility Scopes Requirements"
created: 2026-10-08
implemented: 2026-10-08
tags: [toolkit, authorization, simplification, frontend, backend]
document_role: primary
document_type: requirements
snapshot_id: toolkitscope-261008
---

# Remove Obsolete Toolkit Visibility Scopes Requirements

- Snapshot: `toolkitscope-261008`
- Document reference: `toolkitscope-261008/REQ`

## Problem

Toolkit visibility retains a separately managed scope concept inherited from an earlier organizational model. The remaining visibility kind is the Toolkit's own Workspace, duplicating its existing Workspace ownership. Administrators must not manage a second visibility assignment merely to make a Workspace-shared Toolkit available.

## Primary Context

### Primary System Outcome

Toolkit discovery and shared attachment use the Toolkit's existing Workspace, ownership kind, enabled state, and requester authorization without a separately configured Toolkit visibility scope.

## Supporting Scenarios or Effects

- Workspace managers configure shared Toolkits without a scope-management section.
- Workspace members discover eligible enabled shared Toolkits without an extra Workspace visibility assignment.
- Existing Agent-only Toolkits remain isolated to their exact owning Agent and authorized administrators.

## Goals

- Remove the obsolete Toolkit visibility-scope concept completely rather than hiding its management UI.
- Preserve existing Toolkit data and meaningful ownership/authorization boundaries.
- Keep configured and granted provider OAuth permissions independent of this simplification.

## Non-Goals

- Removing OAuth scopes, provider feature selections, resource permissions, or credential controls.
- Removing Workspace ownership, Workspace membership, Agent ownership, Agent attachment, or management permissions.
- Changing Agent runtime Toolkit lifecycle, executable namespaces, or authorization grants.
- Introducing a replacement visibility policy, compatibility mode, or additional persisted policy version.
- Deploying the change or modifying live infrastructure as part of implementation.

## Requirements

### REQ-1. No separately managed Toolkit visibility scope

Administrators no longer create, list, edit, or delete an additional visibility assignment for a Toolkit.

**Acceptance criteria**

- Toolkit settings contain no visibility-scope section or associated controls.
- The application no longer requires, exposes, creates, or stores separately managed Toolkit visibility assignments.
- Removing the concept does not leave an inactive management path or an alternative legacy scope authority.

### REQ-2. Workspace-shared availability follows existing ownership

A Workspace-shared Toolkit's existing Workspace and enabled state determine its availability to authorized members of that Workspace.

**Acceptance criteria**

- Enabled Workspace-shared Toolkits are discoverable as attachment candidates by authorized members of their own Workspace without an extra visibility assignment.
- An enabled shared Toolkit with no former visibility assignment follows the same rule as every other enabled shared Toolkit after removal.
- Disabled Toolkits remain unavailable as new attachment candidates.
- Cross-Workspace discovery and attachment remain rejected.
- Attaching a Toolkit still requires the existing requester and Agent permissions.

### REQ-3. Preserve Agent-only isolation and management authority

The removal does not broaden Agent-only disclosure or mutation authority.

**Acceptance criteria**

- Agent-only Toolkits are excluded from Workspace-shared discovery and attachment.
- They remain usable only by their exact owning Agent through existing authorized paths.
- Existing Workspace Owner/Manager and explicit Agent administrator boundaries remain unchanged.
- Toolkit ownership labels remain meaningful; they are not the removed visibility concept.

### REQ-4. Preserve existing Toolkit resources

Existing Toolkit configurations remain valid after visibility-scope removal.

**Acceptance criteria**

- Configurations, encrypted credentials, OAuth grants, enabled state, Name/Slug values, Agent attachments, and reserved executable namespaces are preserved.
- Existing attached Toolkits remain attached and resolve through the existing ownership and runtime contracts.
- Former scope assignments are not converted into a new policy or copied into replacement Toolkit resources.
- Removing obsolete visibility state does not delete its Toolkit or stored credentials.

### REQ-5. Retain provider permission scopes

Provider-configured and granted OAuth scopes remain supported and visible through their current permitted surfaces.

**Acceptance criteria**

- MCP configured scopes and redacted granted OAuth scope summaries continue to behave as before.
- Authorization, reauthorization, credential redaction, and configured-versus-granted permission distinctions remain unchanged.
- Generic word-based removal must not affect unrelated transaction, runtime, memory, or lifecycle scope concepts.

## Fixed Constraints

- This is removal of the obsolete Toolkit visibility policy, not merely a label change.
- Workspace-shared and Agent-only ownership remain distinct.
- Existing authorization and sensitive-data handling remain authoritative.
- Implementation is delivered through reviewed changes and CI; merge and deployment require their existing authorization.

## Open Assumptions

- Live data counts and any operational rollout timing have not been inspected or approved by this Requirements document.

## Confirmation

Confirmed by the requester on 2026-10-08 after the repository Requirements and explicit visibility consequence were presented: the scope-based hiding feature and its specification are to be removed. Enabled Workspace-shared Toolkits with no former visibility assignment become discoverable under the same Workspace membership and ownership rules as other enabled shared Toolkits.
