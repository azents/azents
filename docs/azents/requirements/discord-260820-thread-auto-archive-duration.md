---
title: "Discord Thread Automatic Archive Duration Requirements"
created: 2026-08-20
updated: 2026-08-20
implemented: 2026-08-20
tags: [discord, external-channel, frontend, messaging]
document_role: primary
document_type: requirements
snapshot_id: discord-260820
---

# Discord Thread Automatic Archive Duration Requirements

- Snapshot: `discord-260820`
- Document reference: `discord-260820/REQ`

## Problem

Discord External Channel connections currently create every new Azents-managed Thread
with a one-hour automatic archive duration. Connection administrators cannot choose a
duration that matches how long their conversations should remain readily active, and
the current fixed value is shorter than the desired default.

## Primary Actor

An Agent administrator or Workspace Owner/Manager configuring a Discord Single App or
Multi App connection.

## Primary Scenario

The administrator selects a Discord Thread automatic archive duration while creating or
managing a Discord connection. Azents retains the selected value for that connection,
and every Discord Thread that Azents subsequently creates for any Agent route on that
connection uses the selected duration.

## Supporting Scenarios

- A newly created Discord connection starts with a one-day duration selected by default.
- An existing Discord connection is shown with a one-day duration unless an
  administrator has selected another supported value after this capability is
  available.
- An administrator changes only the Thread duration of an active Discord connection
  without re-entering credentials or reconnecting the App.
- Agent settings show an associated Workspace-managed Multi App as read-only context;
  duration management remains on the Workspace integrations surface.

## Goals

- Let administrators choose one of Discord's supported Thread automatic archive
  durations: one hour, one day, three days, or seven days.
- Use one day as the default for both existing and newly created Discord connections.
- Apply the connection's current selection to every Discord Thread Azents creates after
  the selection is saved.
- Support the same behavior for Discord Single Apps and Multi Apps.

## Non-Goals

- Existing Discord Threads are not edited, reopened, re-archived, or otherwise changed.
- The setting does not vary by Agent route, channel, Binding, Resource, or Session.
- This snapshot does not change Discord Thread titles, conversation routing, response
  modes, connection credentials, callback activation, Gateway ownership, or health
  behavior.
- The Select has no explanatory or helper text below it.

## Requirements

### REQ-1. Administrators can select a supported duration

Discord connection setup and management must offer exactly one of four Thread automatic
archive durations: one hour, one day, three days, or seven days.

**Acceptance criteria**

- Discord Single App setup and management expose the four choices.
- Discord Multi App setup and Workspace management expose the same four choices.
- Unsupported values cannot be saved through the product API.
- The Select renders without explanatory or helper copy below it.

### REQ-2. One day is the default

Discord connections without a previously selected duration must use one day.

**Acceptance criteria**

- A new Discord Single App or Multi App setup initially selects one day.
- Every Discord connection that existed before this capability is available reads and
  displays one day after deployment.
- New Discord Threads created from those connections use one day until an administrator
  selects another value.

### REQ-3. The setting applies to the whole connection

The selected duration must apply consistently to every Agent route and conversation
that uses the same Discord connection.

**Acceptance criteria**

- A Single App's subsequently created Discord Threads use its saved duration.
- Every route on one Multi App uses the same saved duration for subsequently created
  Discord Threads.
- Updating one connection does not affect another connection.
- Agent-facing read-only Multi App context does not provide a second conflicting edit
  surface.

### REQ-4. Duration-only changes preserve active connection behavior

An administrator must be able to save a new duration without replacing Discord
credentials or disrupting an otherwise active connection.

**Acceptance criteria**

- Saving only the duration does not require a Bot Token, Application ID, or Guild ID to
  be re-entered.
- Saving only the duration does not reconnect, reactivate, disconnect, or reset the
  connection's health.
- Existing routes, Bindings, Sessions, callback authority, and Gateway operation remain
  available after the change.

### REQ-5. Only newly created Threads use the current value

The saved duration is evaluated when Azents creates a Discord Thread and does not
retroactively mutate provider conversations.

**Acceptance criteria**

- A Thread created after a saved change uses the new duration.
- A previously created or reused Discord Thread is not updated when the setting changes.
- Thread reuse performs no automatic archive-duration mutation.

## Fixed Constraints

- Supported values are exactly 60, 1440, 4320, and 10080 minutes.
- Existing and newly created Discord connections default to 1440 minutes.
- The setting belongs to the Discord connection and is shared by all of its routes.
- Existing Discord Threads remain unchanged.
- Discord Thread creation continues through the adopted Discord SDK operation.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-20 with the direction to use a one-day default,
implement the agreed four-choice Select, remove the explanatory text below it, and
proceed with implementation.
