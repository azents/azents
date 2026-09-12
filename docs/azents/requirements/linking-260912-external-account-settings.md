---
title: "External Account Linking and Conversation Settings Requirements"
created: 2026-09-12
implemented: 2026-09-12
tags: [external-channel, security, frontend]
document_role: primary
document_type: requirements
snapshot_id: linking-260912
---

# External Account Linking and Conversation Settings Requirements

- Snapshot: `linking-260912`
- Document reference: `linking-260912/REQ`

## Problem

A participant using both Azents and an external conversation cannot currently use their Azents-authorized model choices from that conversation. Identifying the same person must not replace existing external guest permissions, imply administrative authority, or disclose personal account state to other participants.

## Primary Context

### Primary Actor

An existing Azents Workspace member participating in a Slack or Discord conversation.

### Primary Scenario

The participant opens private Conversation settings, optionally connects their own external identity to their Azents account for that Workspace, returns to the conversation, and explicitly changes the shared conversation model within the same authority and choices available on the web.

## Supporting Scenarios or Effects

- An unlinked guest continues using all currently permitted conversation and setup controls.
- A user reviews and disconnects their Workspace-specific external accounts from personal settings.
- Participants recognize shared-setting scope, concurrent edits, and when a model change takes effect.
- A user safely recovers from expiry, account mismatch, missing membership, and existing-link conflicts.

## Goals

- Add optional identity linking and same-target Azents-authorized settings.
- Preserve existing guest authorization and canonical execution identity.
- Keep personalized content private and shared results understandable.

## Non-Goals

- Personal tools, personal approval inboxes, broad consent, personal memory injection, billing tiers, or quotas.
- Automatic Workspace membership, account merging, cross-provider grant migration, or offboarding revocation.
- A linked-users-only access mode, new generic roles, or changes to existing access defaults.
- Personalized settings fallbacks through public messages, direct messages, or a separate web conversation-settings surface.
- Reattribution of historical messages, personal Session ownership, or execution credentials.

## Requirements

### REQ-1. Optional linking preserves existing permissions

Linking adds capabilities and is not a prerequisite for existing external-channel functionality.

**Acceptance criteria**

- Unlinked, skipped, cancelled, declined, disconnected, and Azents-permission-lost users retain independently valid external invocation, response-mode, conversation-location, and initial setup permissions.
- Existing open access, Agent/Session grants, blocks, target checks, and defaults remain unchanged; blocks still win.
- Linking neither expands nor transfers a guest grant and does not change Team Session execution identity.

### REQ-2. Explicit Workspace-scoped identity ownership

A link represents the same human's proven external and Azents accounts for one Workspace.

**Acceptance criteria**

- The confirmation experience displays the external identity and server/team, target Workspace, and current Azents account; switching Azents account and cancelling are available.
- Both accounts are proven; matching names/emails, administrator input, or possession of a forwarded link alone cannot complete linking.
- An external-account mismatch, expired flow, or replay cannot create or replace a link.
- Only a current member can activate a Workspace link; nonmembers receive participation/invitation guidance without automatic membership or loss of guest access.
- Other Workspaces require independent confirmation and are not disclosed by this flow.

### REQ-3. Unique links and safe conflict recovery

**Acceptance criteria**

- An external identity links to at most one Azents User per Workspace.
- An Azents User may link one Discord account per Workspace and one Slack account per Slack team per Workspace.
- Conflicts do not overwrite links or disclose the existing owner's Azents name/email.
- Changing external display names does not change ownership; bots and system authors cannot become linked human actors.
- Relinking requires fresh proof after disconnection; another user's link cannot be reassigned by an administrator.

### REQ-4. Private-only personalized settings

**Acceptance criteria**

- User-specific link state, capabilities, available model options, and account prompts appear only in a provider-native surface visible to that user.
- Providers without such a surface omit personalized settings while preserving existing common controls.
- Failure to guarantee private delivery never falls back to public output, direct messages, or web conversation settings.
- Public controls remain identical for all participants and contain no viewer-specific state.

### REQ-5. Quiet persistent invitation

**Acceptance criteria**

- An unlinked user's private settings always contain a small, nonblocking account-link invitation explicitly labelled optional.
- Existing settings remain usable without linking; saving, closing, ignoring, and reopening do not require acknowledgement.
- No forced popup, separate notification, direct message, or per-response reminder is introduced.
- Linked users see current link state and management access instead of repeated invitations.

### REQ-6. Additional controls use current same-target authority

**Acceptance criteria**

- Model changes require both valid external participation and the linked user's current web-equivalent authority for that exact Session.
- A linked ordinary member may use the same model choices as on the web when permitted; a Workspace role is not silently substituted for AgentAdmin.
- Only existing Agent-registered model options and their supported reasoning/execution options are offered; no new model entitlement policy is created.
- Authority and model availability are rechecked at application, not merely when rendering the screen.
- Disconnected conversations, removed options, revoked membership, disabled accounts, and external blocks reject stale edits.
- Missing additional authority does not cause repeated linking prompts or narrow existing guest controls.
- Natural-language requests cannot bypass the same action authority, and linking does not replace shared execution credentials with personal credentials.

### REQ-7. Exact shared scope and explicit application

**Acceptance criteria**

- The screen identifies current conversation, exact thread, or parent future-conversation scope as applicable.
- A thread model edit affects its actual Session, not Agent defaults or sibling Sessions.
- A parent configured to create threads offers no model edit for a nonexistent Session; a connected parent conversation may edit its own Session.
- Draft selection, cancellation, and link completion do not apply pending settings automatically.
- Before application, the user sees that the selection affects the whole conversation and takes effect for new model calls after saving, including later calls within an ongoing Run.
- Already started model calls continue unchanged; no automatic stop/restart or new conversation is introduced.

### REQ-8. Concurrent edits and honest save outcomes

**Acceptance criteria**

- If the shared model setting changed since the screen was opened, a stale save does not silently overwrite it; the user sees current values and must review again.
- A successful save remains committed when its confirmation delivery fails; reopening shows authoritative current state.
- Duplicate submissions do not create repeated changes or bypass fresh authorization.
- Unlinking or permission loss does not revert a shared model choice already committed by a then-authorized actor.

### REQ-9. Personal management and safe disconnection

**Acceptance criteria**

- Personal settings list the user's Workspace-scoped external links, provider/team, external display identity, link time, and state, with an explicit disconnect action.
- Disconnect confirmation explains the affected Workspace and loss of link-dependent functionality without suggesting guest access or messages will be removed.
- Disconnection immediately removes link-based authority for future changes while preserving history, shared configuration, guest grants, and blocks.
- Blocked or unauthorized external participants can reach their own linking/management experience without disclosure of conversation details.
- Account suspension or lost authorization prevents link-based editing and provides appropriate recovery guidance, rather than inviting replacement with another person's account.

### REQ-10. Privacy-preserving shared results and accountability

**Acceptance criteria**

- A successful shared model change produces a concise common notice containing external display identity, changed setting, and effective timing.
- Common output never includes Azents email, private role, personal tool state, or another user's model-option list.
- Management records identify the actual change actor and the link used at that time without rewriting historical message authorship.
- Saving and notification delivery are distinguishable outcomes.

### REQ-11. Return and recovery

**Acceptance criteria**

- The user can return to the original conversation after linking or cancellation; reopening expired settings reflects current link state and permissions.
- Any web Session navigation requires current access to the exact Session; linking grants no other Session access.
- Errors distinguish expiry, mismatch, conflict, and missing Workspace participation without claiming a link succeeded.
- The flow remains operable by keyboard, labels state in text, and keeps account pair, Workspace scope, and final confirmation legible on mobile.

## Fixed Constraints

- Preserve existing provider principal, grant/block, Agent, Workspace, and Session boundaries.
- Linking proves identity, not administrative elevation or consent for personal resources.
- Private state must remain private even on provider delivery failure.
- Existing web behavior is the authority for additional same-target settings, not an invented administrator-only policy.

## Open Assumptions

- Real-user comprehension and linking completion rates remain unmeasured; concept review is not user validation.
- Provider identity-proof and private-surface feasibility must be validated during technical design without changing these outcomes.

## Confirmation

The requester approved the complete product definition revision 4 on 2026-09-12 and explicitly requested autonomous technical design through an implementation PR. This document transcribes that approved scope into public-safe repository requirements; technical delegation does not authorize new product policy. No additional product outcomes are inferred from the delegation. Material scope changes require new requester confirmation before design or implementation.
