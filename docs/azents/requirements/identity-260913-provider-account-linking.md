---
title: "Provider Account Linking Requirements"
created: 2026-09-13
updated: 2026-09-13
tags: [external-channel, identity, oauth, security]
document_role: primary
document_type: requirements
snapshot_id: identity-260913
---

# Provider Account Linking Requirements

- Snapshot: `identity-260913`
- Document reference: `identity-260913/REQ`

## Problem

Connecting a Slack or Discord identity to an Azents account currently requires a
multi-step browser code exchange that moves the user between Azents and the provider,
and the provider-native entry can fail without a visible result. The resulting link
is scoped to one Workspace even though the external identity belongs to the Azents
User and should not require reconnection for each Agent, Channel, Session, or
Workspace.

## Primary Context

### Primary Actor

An authenticated Azents User who also owns a Slack or Discord account and wants
Azents to recognize that external identity.

### Primary Scenario

The User opens External accounts in Azents, chooses Slack or Discord, authorizes the
provider account, and returns to Azents with that identity connected. The same
connection is then recognized from any Agent, Channel, Session, or Workspace where
that provider identity appears, while each requested action still uses the current
resource-specific authorization rules.

## Supporting Scenarios or Effects

- An unlinked Slack or Discord participant opens private Conversation settings and
  follows one direct link to the Azents Web connection experience.
- A system administrator configures the Slack and Discord Applications that Azents
  uses for account authorization, including applications already used for External
  Channels.
- A User manages and disconnects linked provider identities from Azents account
  settings.
- A provider identity already owned by another Azents User cannot be transferred or
  disclosed through the connection flow.
- Existing Workspace-scoped links are migrated without assigning an ambiguous
  provider identity to the wrong Azents User.

## Goals

- Replace provider code exchange with one-pass provider authorization from Azents Web.
- Make the Azents User and provider identity relationship global and reusable.
- Manage provider account-authorization applications through Admin System Settings.
- Preserve all existing guest External Channel behavior and resource-specific
  authorization boundaries.
- Provide explicit, recoverable success and failure outcomes without dead controls.

## Non-Goals

- Granting Workspace membership, Session access, Agent permissions, External Channel
  grants, or cross-provider authority through account linking.
- Implementing personal tools, provider API actions, broad provider consent, token
  refresh, or future user-brought-tool authorization.
- Matching identities by email, display name, manually entered provider ID, or
  administrator assertion.
- Moving conversation history, messages, shared settings, grants, blocks, or external
  principals between identities.
- Unifying Slack and Discord into one cross-provider grant or identity.

## Requirements

### REQ-1. One-pass Web connection

Azents account settings must let an authenticated User connect a Slack or Discord
account through that provider's authorization experience without a browser-generated
code or a second Azents confirmation after the provider returns.

**Acceptance criteria**

- External accounts provides distinct Connect Slack and Connect Discord actions when
  the corresponding provider is available.
- A successful provider authorization returns to Azents and shows the connected
  provider identity without requiring the User to return to Slack or Discord, enter a
  code, poll status, or confirm the same pair again.
- Cancellation, provider rejection, and recoverable provider failures return a clear
  outcome and allow the User to retry from External accounts.
- Connecting one provider never requests or connects the other provider.

### REQ-2. Direct provider-native entry

A private Slack or Discord Conversation settings surface for an unlinked participant
must provide one direct Web link for account connection rather than a stateful native
interaction.

**Acceptance criteria**

- Activating the native Connect control immediately opens the Azents Web connection
  entry for the matching provider.
- The control does not depend on a provider callback, deferred message update, code
  modal, or provider-side connection state mutation before navigation.
- The private settings surface contains one connection prompt and does not display
  `optional` or duplicate a disconnected status message.
- Ignoring the connection prompt leaves every existing guest control usable.

### REQ-3. Global identity ownership and reuse

The connection must belong to the Azents User and the provider identity, not to a
Workspace, Agent, Channel, Session, external connection, or conversation.

**Acceptance criteria**

- A provider identity connected once is recognized without reconnection in every
  Agent, Channel, Session, and Workspace where that identity is encountered.
- One active provider identity can belong to only one Azents User at a time.
- One Azents User may connect multiple Slack identities and multiple Discord
  identities.
- Slack identities retain their Slack team context; Discord identities use the
  provider's account identity.

### REQ-4. Identity does not create authority

A linked identity must only identify the Azents User. Every operation must continue to
apply the current authorization rules for its target Workspace, Agent, Session,
Binding, conversation, and External Channel principal.

**Acceptance criteria**

- Linking alone never grants Workspace membership, Session access, Agent permissions,
  External Channel grants, or access to another provider.
- Link-dependent actions fail when the linked User lacks current authority for the
  exact target, even if the same identity is authorized elsewhere.
- Existing grants, blocks, open-access behavior, response-mode controls, conversation
  location controls, messages, history, and shared settings behave the same for linked
  and unlinked participants unless the action specifically requires a linked Azents
  identity.
- Account disconnection does not revoke or modify those existing guest capabilities or
  historical state.

### REQ-5. Verified, session-bound, nondisclosing connection

A connection must be created only from provider-verified account ownership and the
same live Azents authentication Session that initiated the attempt.

**Acceptance criteria**

- Manual provider IDs, display-name or email matching, native button activation, and
  possession of a copied URL are insufficient to create a link.
- Tampered, expired, replayed, already completed, wrong-provider, and wrong-auth-Session
  attempts create no link.
- A provider identity already linked to another Azents User returns a generic conflict
  without revealing that User, their email, their Workspaces, or other ownership
  details.
- Provider authorization credentials are used only to verify identity for this flow
  and are not retained for provider API access, refresh, or future personal-tool
  consent.

### REQ-6. Global account management and disconnection

External accounts must present the current User's linked Slack and Discord identities
as global account relationships and let the owner disconnect them.

**Acceptance criteria**

- Each connected identity displays its provider, provider-visible account label, and
  Slack team context when applicable, without presenting a Workspace as the link
  owner.
- Disconnecting removes future linked-identity recognition globally for that provider
  identity.
- Disconnecting does not delete prior messages, history, shared settings, audit
  snapshots, grants, blocks, or guest access.
- A disconnected provider identity can be connected again only through a new provider
  authorization.

### REQ-7. Safe legacy transition with no parallel flow

Existing Workspace-scoped account links must transition to the global ownership model
without preserving the browser-code connection path as a fallback.

**Acceptance criteria**

- Legacy active links for the same provider identity that all identify one Azents User
  become one reusable global link.
- Legacy active links for the same provider identity that identify different Azents
  Users do not automatically select an owner or grant global linked-identity authority.
- Historical model-setting and audit records remain interpretable after the transition.
- Browser-origin, candidate, code-entry, status-polling, and final-confirmation product
  surfaces are removed, and no legacy or parallel connection route remains available.

### REQ-8. Explicit availability and deterministic verification

The product must expose whether Slack or Discord connection is available and must be
verifiable without live end-user provider credentials.

**Acceptance criteria**

- If a provider cannot currently start account authorization, External accounts shows
  an unavailable outcome instead of an active control that silently fails.
- Native private settings do not present a dead Connect link for an unavailable
  provider.
- Required automated coverage verifies successful connection, cancellation, conflict,
  expiry, replay rejection, auth-Session substitution rejection, provider mismatch,
  global reuse, target authorization denial, disconnection preservation, and legacy
  transition behavior using deterministic provider fakes.

### REQ-9. Admin-managed provider application settings

System administrators must manage the Slack and Discord application credentials used
for account authorization through Admin System Settings.

**Acceptance criteria**

- Admin System Settings provides independent Slack and Discord account-authorization
  configuration and reports whether each provider is ready, incomplete, invalid, or
  unavailable.
- An administrator may configure the same Slack App or Discord Application that is
  already used for External Channels; Azents does not require a separate identity-only
  provider application.
- OAuth client secrets are write-only after submission, encrypted at rest, and changed
  only through explicit replace or clear actions.
- Configuration mutation uses optimistic concurrency and appends metadata-only audit
  events without secret values, ciphertext, or comparable secret fingerprints.
- Changing or clearing one provider's configuration affects new attempts for that
  provider without changing existing global identity ownership or the other provider's
  availability.
- An attempt started under an older effective provider configuration cannot complete
  after the relevant configuration changes; the User must restart that provider's
  connection.
- Deployment-only environment configuration and Workspace External Channel connection
  credentials are not the authority for this account-authorization configuration.

## Fixed Constraints

- Existing External Channel principal admission and guest authorization remain
  independent of linked Azents identity.
- Personal linked-account and link-dependent settings remain private to the acting
  participant; lack of a private provider surface does not authorize a public or DM
  fallback.
- Provider tokens, authorization codes, Azents auth tokens, cookies, OAuth state, and
  secrets must never appear in logs, user-visible diagnostics, durable external-channel
  state, or generated evidence.
- Slack team context is part of Slack identity disambiguation. Discord identity is not
  scoped to a Discord Guild, Channel, Agent, or Workspace.
- Provider account-authorization client configuration is stored and managed through
  Admin System Settings. It may describe the same provider application used by an
  External Channel connection, but it is not owned by that connection.
- The replacement must not retain a legacy connection mode or compatibility fallback.

## Open Assumptions

- Administrators can register the displayed Azents callback URLs in the chosen Slack
  App and Discord Application before enabling each provider.
- Provider-visible account and team labels are presentation metadata and may be
  refreshed after a later successful authorization without changing stable ownership.

## Confirmation

Confirmed by the requester on 2026-09-13 before ADR and design decisions began,
including the Admin-managed System Settings amendment confirmed the same day.
