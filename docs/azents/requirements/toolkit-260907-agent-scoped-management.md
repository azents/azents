---
title: "Agent-Scoped Toolkit Management Requirements"
created: 2026-09-07
updated: 2026-09-07
tags: [toolkit, agent, frontend, api, security]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260907
---

# Agent-Scoped Toolkit Management Requirements

- Snapshot: `toolkit-260907`
- Document reference: `toolkit-260907/REQ`

## Problem

An administrator preparing one Agent for work such as GitHub access must currently use
Workspace Toolkit management to create every Toolkit configuration and then return to
the Agent to attach it. A configuration and credential set needed by only one Agent is
therefore managed as a Workspace-shared resource, while creation and attachment are
split across different product locations.

The administrator needs to complete the Toolkit setup from the saved Agent's settings,
understand whether an existing Workspace-shared configuration or an Agent-only
configuration is appropriate, and know the resulting ownership, readiness, and change
impact without altering the experience of users who do not administer the Agent.

## Primary Actor

An explicit administrator of the Agent. A Workspace Owner has the same management
authority for this capability.

## Primary Scenario

The administrator opens a saved Agent's settings before using the Agent for GitHub work,
starts from the existing Toolkit section, chooses the GitHub Toolkit type, and either
attaches an existing Workspace-shared configuration or configures a Toolkit available
only to that Agent. The administrator completes any required authorization, confirms
that the Toolkit is ready, and can later change or remove it with the impact limited to
the ownership scope shown in the Agent settings.

## Supporting Scenarios or Effects

- The selected Toolkit type has no suitable Workspace-shared configuration, so the
  administrator creates an Agent-only configuration without leaving the Agent context.
- The administrator lacks the required authority and receives a clear explanation of
  the required role and the person who can complete the setup.
- Validation or provider authorization fails and the administrator retries without a
  separate draft-resource lifecycle.
- A Workspace-shared Toolkit is disabled or otherwise unavailable; its object remains
  managed through the existing Workspace Toolkit experience.
- A user who is not an explicit Agent administrator or Workspace Owner continues to use
  the current Agent, Chat, and Workspace Toolkit experiences without new Agent-only
  Toolkit information or actions.

## Goals

- Let an authorized administrator add and manage a Toolkit from a saved Agent's settings.
- Preserve explicit choice between reusing a Workspace-shared Toolkit and configuring an
  Agent-only Toolkit.
- Make Toolkit ownership scope, readiness, management authority, and change impact
  visible before and after setup.
- Keep Agent-only credentials and configuration isolated to the owning Agent.
- Preserve existing Workspace-shared Toolkit management and non-administrator behavior.

## Non-Goals

- Configuring Toolkits inside the initial Agent creation form.
- Detecting missing Toolkits or adding Toolkit management actions in Chat.
- Exposing Agent-only Toolkit existence, scope, or status to non-administrators.
- Adding Session-specific or user-specific Toolkit selection or credentials.
- Letting an Agent create credentials or attach Toolkits automatically while executing.
- Changing Workspace-shared Toolkit administration policy.
- Adding new Toolkit provider types.
- Adding a general draft or resumable incomplete-resource lifecycle.
- Converting or copying an Agent-only Toolkit into a Workspace-shared Toolkit.

## Requirements

### REQ-1. Toolkit setup from saved Agent settings

An authorized Agent administrator must be able to start Toolkit setup from the saved
Agent's existing Toolkit section.

**Acceptance criteria**

- The section and primary action use the established product terms `Toolkit`, `Add
  Toolkit`, and `Connect` in English and their existing localized equivalents.
- Setup begins by choosing one of the currently supported persisted Toolkit types, such
  as GitHub, rather than by choosing an ownership model.
- Toolkit setup remains optional and does not affect whether the Agent itself is saved.
- No Toolkit setup behavior is added to the initial Agent creation form.

### REQ-2. Reuse a Workspace-shared Toolkit

After choosing a Toolkit type, the administrator must be able to attach a suitable
Workspace-shared Toolkit without leaving the Agent settings.

**Acceptance criteria**

- Eligible existing Workspace-shared configurations for the selected type are shown as
  connection candidates.
- The candidate's Workspace-shared scope and management boundary are visible before
  attachment.
- Attachment requires an explicit administrator action; no candidate is selected or
  attached automatically.
- Creating or modifying the Workspace-shared Toolkit itself remains in the existing
  Workspace Toolkit management experience.

### REQ-3. Configure an Agent-only Toolkit

After choosing a Toolkit type, an explicit Agent administrator or Workspace Owner must
be able to configure a Toolkit whose configuration and credentials belong only to that
Agent.

**Acceptance criteria**

- The Agent-only setup starts and completes within the owning Agent's management
  context.
- The administrator can provide the same applicable configuration, credentials,
  connection tests, and provider authorization required for that Toolkit type in the
  existing Workspace Toolkit setup experience.
- The Agent-only Toolkit is not available for attachment to another Agent.
- The Toolkit is unavailable to Agent execution until its required saved configuration
  and authorization state are ready.

### REQ-4. Agent-only management authority

Only an explicit administrator of the owning Agent and a Workspace Owner may view or
perform Agent-only Toolkit management actions.

**Acceptance criteria**

- Workspace Manager or Member status alone does not grant Agent-only Toolkit management.
- An unauthorized direct management request does not reveal the Agent-only Toolkit's
  existence or configuration.
- Authorized administrators can create, update, enable or disable, reauthorize, test,
  and delete the Agent-only Toolkit as supported by its Toolkit type.
- Agent-only credentials are never returned through product API responses or rendered
  in the product UI.

### REQ-5. Ownership, readiness, and next-action feedback

The Agent Toolkit section must make each administrator-visible Toolkit's ownership scope
and operational readiness understandable.

**Acceptance criteria**

- Each connected Toolkit is labeled as `Workspace shared` or `This Agent only`.
- Ready, authorization-required or disconnected, validation or connection failure, and
  disabled or unavailable states provide text rather than relying only on color or an
  icon.
- A state that requires action identifies the available retry, edit, reconnect, detach,
  delete, or Workspace-management action.
- Insufficient authority identifies the required authority and the appropriate request
  target without exposing Agent-only Toolkit details to non-administrators.

### REQ-6. Cancellation, failure, and re-entry without drafts

Toolkit setup and authorization failures must remain recoverable without creating a new
draft-resource lifecycle.

**Acceptance criteria**

- Validation or connection errors before save remain in the current setup form and
  preserve entered values needed for correction.
- Leaving an unsaved setup discards its inputs and creates no Toolkit resource.
- A saved Toolkit whose external authorization is incomplete or failed uses the
  existing disconnected or authorization-required state and can be retried.
- The Agent cannot use the Toolkit before it reaches the applicable ready state.

### REQ-7. Scope-correct change and removal

Changing or removing a Toolkit from Agent settings must preserve the ownership boundary
shown to the administrator.

**Acceptance criteria**

- Updating, disabling, reauthorizing, or deleting an Agent-only Toolkit affects only its
  owning Agent.
- Deleting an Agent-only Toolkit requires confirmation that the Toolkit is removed from
  the Agent and its stored credentials are deleted.
- A Workspace-shared Toolkit can be detached from the Agent without modifying or
  deleting the shared Toolkit object.
- Workspace-shared Toolkit update, disable, reauthorization, and deletion behavior
  remains in Workspace Toolkit management.

### REQ-8. Agent-only isolation and execution

An Agent-only Toolkit must be isolated from Workspace-shared discovery and other Agents
while remaining usable by the owning Agent under the normal Toolkit runtime contract.

**Acceptance criteria**

- The Agent-only Toolkit does not appear in the Workspace Toolkit management list or in
  another Agent's available Toolkit candidates or management surfaces.
- The owning Agent resolves the Toolkit through the same normal enabled/ready execution
  boundary used for an attached persisted Toolkit.
- Disabling or deleting the Agent-only Toolkit removes its tools, prompts, credential
  exposure, and managed Toolkit resources from later owning-Agent runs under the
  existing Toolkit lifecycle rules.
- The feature does not add a new Toolkit provider type or a new Session- or user-level
  runtime selection mode.

### REQ-9. Non-administrator and Chat compatibility

The capability must not change the product experience for users outside the authorized
Agent-management context.

**Acceptance criteria**

- Non-administrators receive no new Agent-only Toolkit list item, ownership label,
  readiness state, management action, or permission prompt.
- Existing non-administrator Agent and Workspace Toolkit behavior remains unchanged.
- Chat gains no Toolkit status, missing-Toolkit detection, management link, or setup
  call to action for administrators or non-administrators.
- Existing Agent execution behavior remains unchanged except for the tools made
  available by an authorized, ready Agent-only Toolkit.

### REQ-10. Accessible and responsive management flow

The Agent Toolkit management flow must preserve the selected Toolkit type, ownership
scope, state, and primary action across supported layouts and input methods.

**Acceptance criteria**

- Keyboard users can choose a Toolkit type, choose a shared candidate, configure and
  save an Agent-only Toolkit, cancel, retry, reconnect, detach, and confirm deletion.
- Errors are associated with the relevant input and do not discard focus context after
  a failed save.
- Mobile layouts preserve the reading and action order: Toolkit type, ownership scope,
  readiness state, then primary action.
- Localized product copy retains the established Toolkit terminology rather than
  introducing a separate top-level integration concept.

## Fixed Constraints

- Agent-only management authority is exactly explicit Agent administrator or Workspace
  Owner.
- Workspace Manager and Member roles receive no Agent-only authority from their role
  alone.
- Existing Workspace Toolkit creation and object-management policy remains unchanged.
- Existing Agent creation and Chat behavior remains unchanged.
- No automatic attachment or automatic Agent-only Toolkit creation is permitted.
- No new Toolkit providers, general draft lifecycle, Session/user Toolkit mode, or
  Agent-only-to-Workspace conversion is introduced.
- Current Toolkit type and instance policies remain unchanged unless a later confirmed
  Requirements snapshot changes them.
- Credential secrecy and the existing encrypted-at-rest Toolkit credential contract
  remain mandatory.

## Open Assumptions

- The exact persistence representation, API route structure, ownership discriminator,
  slug namespace, and OAuth return routing are technical design decisions.
- Existing provider-specific setup forms and authorization flows can be reused or
  adapted without changing their user-visible credential requirements.
- The exact visual arrangement can be decided during implementation as long as the
  required information and action order remain observable.
- Completion usability will be validated through an end-to-end task walkthrough and,
  when available, post-release setup and retry signals.

## Confirmation

Confirmed by the requester on 2026-09-07 before ADR and design decisions began.
