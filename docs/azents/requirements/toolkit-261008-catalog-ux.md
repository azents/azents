---
title: "Agent Toolkit Catalog and Compact Connection Management Requirements"
created: 2026-10-08
implemented: 2026-10-08
tags: [toolkit, agent, frontend, ux]
document_role: primary
document_type: requirements
snapshot_id: toolkit-261008
---

# Agent Toolkit Catalog and Compact Connection Management Requirements

- Snapshot: `toolkit-261008`
- Document reference: `toolkit-261008/REQ`

## Problem

Administrators find it difficult to discover a service to configure for one Agent and to find existing Workspace-shared connections. The current type-first, then ownership-selection flow obscures those two tasks. Connection summaries also become difficult to scan when connection metadata, capability lists, and permission explanations are all shown together. Administrators need an unambiguous completion boundary: adding a Toolkit must persist the connection without another save of the parent Agent settings.

## Primary Context

### Primary Actor

An explicit administrator of a saved Agent, or a Workspace Owner with the same Agent Toolkit management authority.

### Primary Scenario

The administrator opens the saved Agent's Toolkit section, starts Add Toolkit, chooses either a new Agent-only service configuration or an existing Workspace-shared connection, completes that action, and immediately sees the persisted connection in a compact visual list. The administrator opens connection details only when configuration, capabilities, access information, or management actions are needed.

## Supporting Scenarios or Effects

- The administrator needs to create a Workspace-shared connection and follows the catalog's Workspace creation link.
- A configured Toolkit requires OAuth authorization or reconnection; its state and permitted next action remain understandable.
- The administrator performs the same journey on a narrow mobile viewport or with a keyboard.
- Users without Agent-only management authority retain their existing shared attachment experience without gaining disclosure or permissions.

## Goals

- Separate discovering a new service from reusing an existing Workspace connection.
- Make new Toolkit selection visually recognizable through service tiles.
- Make Toolkit addition independent of saving unrelated Agent settings.
- Keep connected Toolkit summaries compact and move detailed information into a dedicated detail view.
- Preserve current ownership, credential, authentication, and execution boundaries.

## Non-Goals

- Toolkit configuration inside initial Agent creation or management in Chat.
- Implementing new service-specific setup wizards in this snapshot.
- Automatically saving unrelated Agent settings.
- Changing Toolkit provider availability, credential requirements, grants, ownership, namespace behavior, or authorization policy.
- Agent-only to Workspace-shared conversion, new drafts, or user/Session-specific credentials.
- Live external-service health monitoring, external permission introspection, or new runtime tool discovery in management screens.
- User-uploaded Toolkit logos or a new icon-administration experience.
- A general redesign of Workspace Toolkit management or other integrations.

## Requirements

### REQ-1. Two-tab Toolkit catalog

Add Toolkit opens a catalog that separates new service configuration from Workspace connection reuse.

**Acceptance criteria**

- The catalog contains `New Toolkit` and `Workspace Toolkit` tabs using localized product copy.
- `New Toolkit` is the default on each new Add Toolkit entry.
- Users can switch tabs without creating or attaching a Toolkit.
- Empty, loading, and error states do not imply that a connection has succeeded.

### REQ-2. New service tiles and provider configuration

The default tab presents supported, user-configurable Toolkit types as tiles.

**Acceptance criteria**

- Each tile shows a recognizable service/type icon and the existing Toolkit name.
- Selecting a type directly opens its configuration view for an Agent-only Toolkit; there is no intervening shared-versus-owned selection step.
- The current applicable provider configuration, credentials, tests, and authorization controls remain available; the redesign does not replace them with speculative wizard behavior.
- The setup view is distinct from the catalog so a later provider-specific wizard need not alter the catalog's meaning.
- Canceling unsaved configuration creates no Toolkit and provides a return to the catalog or Agent context.

### REQ-3. Workspace connection tiles and creation navigation

The Workspace tab presents eligible existing shared Toolkit instances rather than provider-type choices.

**Acceptance criteria**

- Tiles identify the saved connection by its Name and Toolkit type/icon.
- Candidates retain current eligibility and exclude connections already attached to the Agent.
- Choosing an eligible connection attaches that exact instance to the current Agent.
- The last catalog entry provides `Add Workspace Toolkit` navigation to existing Workspace Toolkit creation.
- Navigation does not create a Workspace Toolkit implicitly or grant creation permission to an unauthorized requester.
- The feature does not add automatic post-creation return or implicit attachment.

### REQ-4. Immediate durable addition

A successful addition is already persisted and does not require saving the parent Agent settings again.

**Acceptance criteria**

- Completing a new Agent-only Toolkit's setup saves it and adds it to the connected list.
- Choosing an existing Workspace Toolkit saves its attachment and returns to the connected list.
- Reloading after successful completion preserves the addition without any parent Agent save.
- Unrelated unsaved Agent settings are neither submitted nor discarded by Toolkit addition.
- Pending submission is visible and repeated clicks do not initiate duplicate additions.
- A failed save/attach is not displayed as a successful persisted connection, and the requester can correct or retry the failed action.
- A saved Toolkit awaiting OAuth remains added with its truthful authorization-required state; successful persistence is not represented as completed external authorization.

### REQ-5. Compact visual connection list

The Agent Toolkit list uses compact service-oriented cards rather than dense, detail-heavy summaries.

**Acceptance criteria**

- Cards show service icon, saved Name, Toolkit type, short description where available, ownership scope, and a concise text readiness indicator.
- Connection metadata, configured capability groups, detailed access explanations, and technical identifiers are not expanded in every list card.
- Every administrator-visible item has a clear detail entry point.
- Applicable authorization/reconnection remains reachable from an authorization-required item without obscuring the main list.
- Persisted readiness retains its current meaning and is not presented as a live connection-health guarantee.

### REQ-6. Detail view with ownership-correct management

A connection detail view provides the information intentionally removed from the list and retains the applicable management actions.

**Acceptance criteria**

- The detail view identifies the exact selected Toolkit and its ownership scope.
- It shows available non-secret connection/configuration information and configured capabilities/access explanations that are supported by existing data.
- Missing external account or grant information is not invented. Selected capability groups are distinguished from permissions actually granted by the external service.
- Credential values, access/refresh tokens, client secrets, and private keys are never shown, including through generic raw configuration dumps.
- Agent-only details retain edit, enable/disable, authorization/test, and confirmed deletion through the existing authorized paths.
- Workspace-shared details retain local detach and authority-correct navigation to Workspace management; shared objects are not edited or deleted as Agent-owned resources.
- Closing details returns to the same list without losing connection state.

### REQ-7. Consistent service recognition and accessible responsive behavior

Service identity and the flow remain consistent across catalog, connected list, and detail view.

**Acceptance criteria**

- One Toolkit type uses the same icon treatment across new-type tiles, saved-instance tiles, list cards, and details.
- Icons complement readable names; icon or color alone does not convey service identity, readiness, or an action.
- Desktop and mobile preserve the same two-tab selection model and ownership boundaries.
- Narrow layouts keep tiles and inputs readable, allow necessary vertical scrolling, and avoid horizontal overflow.
- Keyboard users can select tabs/tiles, complete or cancel setup, open/close details, and invoke permitted management actions.
- Existing supported locales and light/dark themes remain supported.

### REQ-8. Existing policy and data preservation

The presentation change preserves unaffected product behavior and existing configuration.

**Acceptance criteria**

- Existing Toolkit configurations, attachments, encrypted credentials, grants, enabled state, Name/Slug values, and runtime namespaces are unchanged.
- Agent-only management remains restricted to the exact Agent's explicit administrator or Workspace Owner.
- Workspace Manager status alone does not grant Agent-only disclosure or management authority.
- Existing non-administrator/shared attachment behavior remains unchanged.
- OAuth popup callback validation, permission revalidation, credential redaction, and incomplete-authorization recovery retain their current contracts.

## Fixed Constraints

- The confirmed catalog flow and compact list/detail separation are the baseline, not alternative product proposals.
- Provider-specific forms remain the initial setup experience; future wizard work is separate.
- Toolkit addition is independent of parent Agent form submission.
- Displaying additional detail does not create new access authority or require exposing credentials.
- Current saved-Agent-only entry and unchanged non-administrator behavior remain in force.

## Open Assumptions

- Icon source/asset ownership is a technical decision after Requirements confirmation; no source library or remote URL contract is selected here.
- Responsive container geometry and equivalent component decomposition are implementation details when they preserve the approved flow and controls.
- The short description uses existing persisted description or established provider purpose; missing instance descriptions need not create new stored data.
- Actual provider grant enumeration is outside scope. Detail presentation is bounded by currently available non-secret data.

## Confirmation

Confirmed by the requester on 2026-10-08 after the complete repository Requirements document was presented. The requester approved the catalog and compact list/detail concepts, required immediate persisted addition, and confirmed proceeding through the complete implementation Design. The requester subsequently approved proceeding through complete Design and implementation on the same date.
