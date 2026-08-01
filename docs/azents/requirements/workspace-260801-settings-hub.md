---
title: "Workspace Settings Hub Requirements"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [workspace, settings, frontend]
document_role: primary
document_type: requirements
snapshot_id: workspace-260801
---

# Workspace Settings Hub Requirements

- Snapshot: `workspace-260801`
- Document reference: `workspace-260801/REQ`

## Problem

Workspace settings currently open directly into a single LLM configuration surface that combines workspace default model settings and LLM provider integrations. This makes the settings entry point difficult to scan and leaves no clear information architecture for additional workspace-scoped settings. The experience is also inconsistent with the established Agent settings flow.

## Primary Actor

A Workspace member who needs to inspect Workspace configuration, with the Workspace Owner additionally able to change configuration according to the existing permission model.

## Primary Scenario

A Workspace member opens Workspace settings, scans a settings overview, selects either default model settings or LLM provider integrations, and reaches a focused detail surface without losing Workspace context. An Owner can perform the existing management actions, while another member can inspect the same settings in a read-only state and return to the settings overview.

## Supporting Scenarios

- A member follows the Workspace navigation back from settings without entering an Agent-specific context.
- A user opens a settings detail surface on a narrow viewport and can still identify the current Workspace, navigate back, and operate or inspect the page.
- Future Workspace-scoped settings can be added to the overview without restructuring unrelated Workspace navigation.

## Goals

- Make Workspace settings easy to scan before entering a specific configuration task.
- Give Workspace settings the same coherent hierarchy and navigation flow as Agent settings.
- Separate default model configuration from LLM provider integration management.
- Preserve the existing capabilities, data, and authorization behavior of both settings areas.

## Non-Goals

- Moving Members, Toolkits, External channels, Runtime execution, or My Profile into the Workspace settings overview.
- Changing Workspace roles or settings authorization rules.
- Changing the backend APIs, persistence model, or provider credential behavior solely for this layout work.
- Redesigning unrelated Workspace or Agent navigation.

## Requirements

### REQ-1. Settings overview

Workspace settings must open to an overview from which members can identify and enter each supported Workspace configuration area.

**Acceptance criteria**

- Opening Workspace settings shows an overview rather than opening an individual configuration form directly.
- The overview exposes separate entries for default model settings and LLM provider integrations.
- Each entry has a clear label and task-oriented description.
- Selecting an entry opens its focused settings surface.

### REQ-2. Focused settings navigation

Each Workspace settings area must preserve Workspace identity and provide an obvious path back to the settings overview.

**Acceptance criteria**

- The overview and detail surfaces identify the current Workspace.
- Each detail surface provides a visible action to return to the Workspace settings overview.
- Returning to the overview does not leave the current Workspace or enter an Agent-specific navigation context.
- Browser navigation and direct entry into a detail surface remain usable.

### REQ-3. Existing configuration capabilities

The reorganization must preserve the current default model and LLM provider integration capabilities.

**Acceptance criteria**

- The default model settings surface retains its existing values, validation, loading, error, submission, and catalog synchronization behavior.
- The LLM integration surface retains its existing list, creation, editing, enablement, deletion, OAuth or credential setup, usage display, loading, empty, and error behavior where currently applicable.
- Existing stored Workspace configuration remains available after the UI change without migration or re-entry.

### REQ-4. Existing permission behavior

All Workspace members must continue to be able to inspect Workspace settings, while management actions remain restricted according to the existing Owner-only settings permission behavior.

**Acceptance criteria**

- Every Workspace member who can currently open Workspace settings can open the overview and both detail surfaces.
- An Owner can perform all currently available management actions.
- A member without management permission sees the applicable configuration in a read-only state and is not offered controls that imply an unavailable action.
- The reorganization does not grant additional settings permissions or remove existing Owner permissions.

### REQ-5. Consistent settings experience

Workspace settings must use a visual hierarchy and interaction pattern consistent with Agent settings while remaining clearly Workspace-scoped.

**Acceptance criteria**

- The surfaces use a Workspace-specific identity header, overview hierarchy, focused detail layout, and return navigation that are recognizably consistent with Agent settings.
- Workspace settings do not display Agent identity, Agent status, or Agent-specific navigation.
- Content remains readable and operable on desktop and mobile viewports.
- Loading, error, empty, read-only, and overflow states do not obscure the current Workspace or the available navigation.

### REQ-6. Preserve unrelated Workspace navigation

The settings reorganization must not absorb or duplicate unrelated Workspace-level destinations.

**Acceptance criteria**

- Members, Toolkits, External channels, Runtime execution, and My Profile remain in their current Workspace navigation positions.
- The settings overview does not present those destinations as settings sections in this snapshot.
- The Workspace settings entry remains a single Workspace-level navigation item.

## Fixed Constraints

- `/w/{handle}/settings` becomes the Workspace settings overview entry point.
- Default model settings and LLM provider integrations are presented as separate detail destinations under the current Workspace.
- Existing Workspace shell ownership and Agent-focused shell ownership remain unchanged.
- Existing settings authorization remains the source of truth; frontend presentation must not substitute for backend authorization.
- Git-tracked product and engineering artifacts remain in English, with user-facing strings provided through the existing localization system.

## Open Assumptions

- The current Workspace data available to the frontend is sufficient to render a meaningful Workspace identity header without a new backend contract.
- No external integration depends on `/w/{handle}/settings` rendering the LLM integration form immediately rather than a settings overview.
- The existing default model and integration components can be separated without changing their user-visible behavior.

## Confirmation

Confirmed by the requester on 2026-08-01 before ADR and design decisions began.
