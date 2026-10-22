---
title: "Google Tool Group Consent Requirements"
created: 2026-10-22
updated: 2026-10-22
implemented: 2026-10-22
document_role: primary
document_type: requirements
snapshot_id: googletools-261022
tags: [google, toolkit, oauth, calendar, permissions]
---

# Google Tool Group Consent Requirements

- Snapshot: `googletools-261022`
- Document reference: `googletools-261022/REQ`

## Problem

Users cannot reliably select partial permissions on every Google consent surface.
Automatically requesting every supported permission does not express which tool
capabilities the user actually wants. Calendar operations also need explicit
control over guest privileges.

## Primary Actor

A user authorized to manage a Google Toolkit in its existing ownership context.

## Primary Scenario

The user selects useful groups of tools within Google services, optionally applies
a preset and customizes its selections, authorizes the permissions needed for the
chosen tools, and sees the final usable groups after Google returns its actual
grant.

## Supporting Scenarios or Effects

- An Agent creates or modifies Calendar events with the requested guest privileges.

## Goals

- Make intended tool capabilities understandable before OAuth authorization.
- Request permissions for selected tools rather than every supported capability.
- Truthfully show the usable result after partial consent.
- Expose Calendar guest controls through supported tools.

## Non-Goals

- Guarantee Google displays independently selectable consent checkboxes.
- Change existing Calendar update-notification controls, which already support
  suppressing update notifications.
- Bypass Google account, organization, resource or organizer restrictions.
- Change live credentials, revoke grants, alter cloud configuration or deploy as
  part of requirements/design work.

## Requirements

### REQ-1. Service-specific tool group selection

Users can select the groups of tools they want for each supported Google service.

**Acceptance criteria**

- Groups communicate their supported user-facing capabilities.
- Users can inspect the tools included in each group.
- The selection flow works in existing Workspace, Agent and personal contexts.

### REQ-2. Useful customizable presets

Presets automatically select and deselect relevant tool groups. Users can adjust
the resulting selection rather than being locked to a preset.

**Acceptance criteria**

- Applying a preset updates the visible selection truthfully.
- Further group-level changes remain possible.
- Changing a preset does not independently grant Google permissions.

### REQ-3. Permissions follow selected tools

OAuth requests correspond to the permissions needed for the selected tools,
rather than unconditionally requesting all supported service permissions.

**Acceptance criteria**

- The requested capabilities match the user's selected groups.
- Unselected capabilities do not independently cause permission requests.
- The workflow does not promise Google offers partial selection in every context.

### REQ-4. Final usable groups after consent

The final connection step shows the resulting usable tool groups based on the
requested selection and the permissions actually granted by Google.

**Acceptance criteria**

- Partial consent produces a truthful final result without assuming every
  requested permission was granted.
- Unavailable capabilities and the reason they are unavailable are visible.
- The user sees the final usable result before the connection flow ends.

### REQ-5. Calendar guest privileges

Calendar event creation and modification support controlling whether guests can
modify the event, invite other guests, and see other guests.

**Acceptance criteria**

- An Agent can explicitly enable or disable each supported guest privilege.
- Modifying an unrelated event field preserves unspecified guest privileges.
- Google organizer and resource restrictions remain authoritative.

## Fixed Constraints

- Preserve existing Toolkit ownership and access boundaries.
- Preserve existing actual-grant verification and uncertain-operation no-replay
  semantics.
- Do not silently reconnect, expand or revoke existing Google grants.
- Keep historical implemented Requirements, ADRs and Designs immutable.

## Confirmed Scope and Open Assumptions

- Selected groups limit exposure and execution even when Google returns broader
  permissions; actual grants and existing resource/owner checks remain necessary.
- Existing saved connections retain their current usable capabilities during the
  introduction of explicit selections; no silent reconnect or privilege expansion.
- Exact group membership and preset contents are grounded in the current supported
  tool catalog. Partial groups show their usable and unavailable members truthfully.
- Initial selection must not silently request full access; users explicitly choose
  a preset or groups before beginning OAuth.

## Confirmation

The requester supplied REQ-1 through REQ-5 on 2026-10-22 and explicitly requested
implementation and PR creation after excluding the already-supported notification
control. Concrete catalog, authorization and preservation decisions are recorded
in the matching ADR and Design under that implementation scope.
