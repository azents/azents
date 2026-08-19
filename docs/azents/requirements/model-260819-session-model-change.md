---
title: "Session Model Change Requirements"
created: 2026-08-19
updated: 2026-08-19
tags: [model, session, chat, frontend]
document_role: primary
document_type: requirements
snapshot_id: model-260819
---

# Session Model Change Requirements

- Snapshot: `model-260819`
- Document reference: `model-260819/REQ`

## Problem

A Session's model can currently be changed only by opening its web chat and sending a message with a selected inference profile. This couples a Session setting change to message creation and prevents Discord, Slack, Scheduled Tasks, and other execution paths from naturally using a newly selected Session model until a qualifying web-chat input updates the Session. In addition, an Agent model option can change while existing Sessions continue using an older resolved snapshot behind the same label. Browser-local model selection persistence further competes with the server-owned Session state and can restore an unapplied or stale choice.

## Primary Actor

A user working in an existing root Session through the web Composer.

## Primary Scenario

The user selects a different model profile from the Composer's existing picker. The Composer visually indicates that the selection is pending. If the input contains text, the user presses Send and the selected profile is applied to the Session together with sending the message. If the input is empty, the same action control becomes a model-change action and applies the selected profile without creating a message or starting model execution. The next model turn, regardless of which supported trigger causes it, uses the Session's applied label and the Agent's current configuration for that label.

## Supporting Scenarios

- An Agent administrator changes the physical model or model-scoped settings behind an existing label, and Sessions using that label use the updated Agent configuration from their next model turn without requiring a web-chat message.
- A Discord, Slack, Scheduled Task, command, continuation, or other supported trigger starts the next Session execution and naturally uses the Session's already applied model profile.
- The user reloads the page or opens the Session in another browser and sees the server-owned applied Session profile rather than a browser-local remembered model choice.
- A model-setting change occurs while a provider call is already in progress; the active call finishes with its prepared snapshot and the same Run uses the updated setting from its next model-turn boundary.

## Goals

- Let users apply a Session model change without sending a chat message.
- Keep the existing model picker in its current Composer location.
- Make an unapplied model change visually apparent and connect it to the action that will apply it.
- Keep the Session's selected label stable while resolving that label through the Agent's current model configuration at subsequent model turns.
- Ensure every execution path uses the same applied Session model state.
- Remove browser-local model-profile memory so the Session is the user-visible source of truth.

## Non-Goals

- Adding model pickers or model-selection commands to Discord, Slack, or Scheduled Task configuration.
- Adding one-execution-only model overrides to external invocations or Scheduled Tasks.
- Moving or redesigning the overall Composer layout or relocating the model picker.
- Allowing clients to submit physical model snapshots, provider identifiers, credentials, or Agent model-option settings.
- Changing lightweight or compaction model selection through the Composer.
- Changing the existing root-versus-subagent authority boundary for human model selection.
- Defining migration or fallback behavior for an Agent model-option label that is deleted or renamed.

## Requirements

### REQ-1. Pending model selection

Changing the model label or reasoning effort in the existing Composer picker must create an unapplied selection without immediately changing the Session's applied model profile.

**Acceptance criteria**

- The picker remains in its current location.
- The picker displays the newly selected label and effort before application.
- The Session's applied profile remains unchanged until the user activates the Composer action control.
- Returning the picker to the applied Session profile removes the pending-change state.

### REQ-2. Visual pending-change nudge

The Composer must communicate a pending model-profile change primarily through visual state rather than explanatory copy.

**Acceptance criteria**

- When no model change is pending, the picker and action control retain their normal visual treatment.
- When a model change is pending, the picker and the applicable action control share the same accent glow so they are perceived as one action.
- The pending state remains distinguishable in both the message-send and model-only application cases.
- The agreed visual baseline is the reviewed V2 mock: a blue picker outline and status point, with the same light-blue outer glow on the picker and action control.

### REQ-3. Apply and send with text

When the input box contains text and a model-profile change is pending, activating Send must apply the selected profile to the Session and send the message as one user action.

**Acceptance criteria**

- The action control continues to use the Send icon.
- The accepted message is associated with the selected label and effort.
- The model turn caused by that message uses the newly applied Session profile.
- The user is not required to perform a separate model-application action before sending.

### REQ-4. Apply without a message

When the input box is empty and a model-profile change is pending, the Composer action control must apply only the model change.

**Acceptance criteria**

- The action control changes from the Send icon to the reviewed check-style model-application icon.
- Activating it updates the Session's applied label and effort.
- No user message, command, or other transcript input is created.
- Applying the change alone does not start a Run or provider call.
- After successful application, the pending-change visual treatment clears.

### REQ-5. Shared Session model state across triggers

All supported execution paths must use the Session's applied model profile when they next produce inference.

**Acceptance criteria**

- Web chat, Discord, Slack, Scheduled Tasks, commands, continuations, and other implicit Session execution paths observe the same applied Session label and effort.
- A model-only application performed in the web Composer affects a later external or scheduled execution without an intervening web-chat message.
- External execution paths do not require their own model picker or per-invocation override for this capability.

### REQ-6. Label-based synchronization with Agent configuration

A Session must retain its selected label intent while the physical model and model-scoped settings behind that label remain synchronized with the Agent's current configuration.

**Acceptance criteria**

- Changing the Agent's main/default label does not overwrite an existing Session's selected label.
- When an administrator changes the physical model or settings mapped to a label, an existing Session using that label uses the updated mapping from its next model turn.
- No chat message or repeated label selection is required to refresh the Session after the Agent label mapping changes.
- The client continues to submit and display Agent-owned labels rather than physical model snapshots.

### REQ-7. Turn-boundary application

A model-profile or Agent label-mapping change must affect the next model turn without mutating a provider call that has already started.

**Acceptance criteria**

- A provider call already in progress completes using the snapshot prepared for that call.
- If the same Run reaches another model turn after the change, that next turn uses the latest applied Session profile and current Agent mapping.
- No special delayed-application, queued-switch, or new-Run user-visible state is introduced.

### REQ-8. Remove browser-local model memory

The browser must not persist model label or reasoning-effort selection as Composer memory.

**Acceptance criteria**

- The separate last-selected inference profile is no longer stored or restored from local storage.
- An unapplied model label or effort is not stored inside the local Composer draft.
- Text and selected-action draft persistence remain available without model-profile fields.
- Reloading or reopening an existing Session restores the server-owned applied Session profile.
- Reloading before applying a pending model change discards that pending model change.

### REQ-9. Preserve model-profile safety boundaries

The feature must retain the existing model-option authority and validation boundaries unless separately changed by a later confirmed requirement.

**Acceptance criteria**

- Users can select only labels currently owned by the Agent.
- Reasoning effort remains limited to the selected label's supported explicit values or model default.
- Invalid or unsupported profiles fail safely without corrupting the previously applied Session profile.
- Human model-profile changes remain unavailable in read-only subagent Sessions.

## Fixed Constraints

- The Session remains the durable owner of the applied model label and reasoning effort used across clients and triggers.
- Agent-owned selectable labels remain the only client-visible model-routing intent.
- A Session label is resolved against current Agent configuration at a model-turn boundary; clients do not resolve physical models.
- The current provider call is immutable after preparation.
- The reviewed V2 Composer treatment is the visual baseline for pending model changes.
- No backward-compatibility behavior is required for removed browser-local model-profile persistence.

## Open Assumptions

- Removing model selection from local storage includes both the separate last-selected profile and the inference profile currently embedded in an unsent draft; only text and selected-action draft state remain.
- Agent label deletion or rename behavior remains outside this snapshot and continues to follow existing safe-failure behavior.
- Existing attachment and input-action behavior remains unchanged; their interaction with the action control follows the same message-versus-empty-input rules where applicable.

## Confirmation

Confirmed by the requester on 2026-08-19 before ADR and design decisions began. The requester explicitly delegated all remaining material design decisions and final Design approval to Autonomous mode.
