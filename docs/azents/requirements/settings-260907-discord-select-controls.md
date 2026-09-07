---
title: "Discord Conversation Settings Select Controls Requirements"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, settings, session-navigation]
document_role: primary
document_type: requirements
snapshot_id: settings-260907
---

# Discord Conversation Settings Select Controls Requirements

- Snapshot: `settings-260907`
- Document reference: `settings-260907/REQ`

## Problem

Discord Conversation settings currently present mutually exclusive location and response-mode values as equal-weight buttons. The resulting surface becomes crowded when Session navigation is also needed, and settings opened from different Discord entry points should present the same compact controls.

## Primary Actor

A Discord participant opening Conversation settings for a connected parent channel or thread.

## Primary Scenario

The participant opens Conversation settings from any supported Discord entry point, sees each independent setting as a Select with its current value selected, changes one value immediately, and retains access to the same settings surface and the current Session when an exact connected Session exists.

## Supporting Scenarios

- Parent-channel settings expose both response location and response mode.
- Connected-thread settings expose only response mode.
- A parent channel configured for threads may have no single connected Session.
- First-time conversation setup still asks the participant to choose a location before a Session exists.
- Settings may be opened from the slash command, message command, joined-presence control, or conversational Activity Tracker.

## Goals

- Present mutually exclusive Discord settings as compact, clearly grouped selections.
- Use one consistent settings surface across every Discord Conversation settings entry point.
- Keep the settings surface usable after each immediate selection.
- Expose Session navigation whenever the current conversation has one exact connected Session.

## Non-Goals

- Changing Slack Conversation settings.
- Changing first-time Discord setup choices.
- Changing location or response-mode semantics.
- Creating a Session only to show a navigation control.
- Adding persistence, configuration, migration, or new authorization policy.

## Requirements

### REQ-1. Use Select controls for connected Discord settings

Every connected Discord Conversation settings surface must present each independent mutually exclusive setting as a single-selection control rather than separate choice buttons.

**Acceptance criteria**

- Parent-channel settings expose one location selection and one response-mode selection.
- Connected-thread settings expose one response-mode selection and no location selection.
- Each selection identifies its setting category and shows the current canonical value as selected.
- The same presentation is used regardless of which supported Discord entry point opened settings.

### REQ-2. Apply selections immediately and keep settings available

Selecting a setting value must immediately apply the existing canonical mutation and refresh the same settings surface.

**Acceptance criteria**

- No separate Save action is required.
- A successful selection refreshes all controls from the committed canonical state.
- The participant can change another setting without reopening Conversation settings.
- Stale, invalid, unavailable, or unauthorized selections retain bounded failure behavior.

### REQ-3. Provide exact Session navigation

A connected Discord Conversation settings surface must expose View session when the current conversation has one exact connected Session.

**Acceptance criteria**

- The control opens the canonical Workspace, Agent, and Session route.
- Connected-thread settings expose the thread Binding's Session.
- Parent-channel settings expose Session navigation only when the parent channel has an exact connected Binding.
- Settings omit Session navigation when no exact connected Session exists.

### REQ-4. Preserve setup and provider boundaries

The presentation change must preserve existing setup, authorization, and provider behavior outside connected Discord settings.

**Acceptance criteria**

- First-time Discord setup retains its existing location-choice buttons and continuation behavior.
- Existing signed scope, current-state fences, actor authorization, and provider interaction authentication remain authoritative.
- Conversation settings entry controls remain available on their existing Discord surfaces.
- Slack behavior remains unchanged.

## Fixed Constraints

- Discord component identifiers must remain within provider limits.
- Select values must be validated against the setting represented by their signed scope.
- Session navigation must be derived from current canonical Binding authority rather than persisted in provider controls.
- The feature introduces no database migration, compatibility fallback, or rollout flag.

## Open Assumptions

- Supported Discord clients render single-selection String Select components consistently in ephemeral interaction responses.

## Confirmation

Confirmed by the requester on 2026-09-07. The requester approved Select-based Discord settings with a View session control and then explicitly extended the same presentation to every Discord Conversation settings entry point.
