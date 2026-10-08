---
title: "GitHub User Account Toolkit Requirements"
created: 2026-10-08
document_role: primary
document_type: requirements
snapshot_id: github-261008
tags: [github, toolkit, oauth, security]
---

# GitHub User Account Toolkit Requirements

- Snapshot: `github-261008`
- Document reference: `github-261008/REQ`
- Confirmed by the requester on 2026-10-08 before material technical decisions. Implementation still requires approved ADR/Design and a separate implementation request.

## Problem

A Toolkit manager can currently delegate GitHub App installation authority to an Agent, but cannot connect a GitHub user account through either the platform-provided App or a manager-provided App and retain that account as the Agent's execution authority. Manually supplied tokens create unnecessary setup effort, while installation-only execution does not follow the connected user's repository authority. Deployments without a configured Platform App must still support manager-provided Apps without presenting unavailable platform choices.

## Primary Context

### Primary Actor

An existing Workspace Toolkit manager or authorized administrator of an Agent, providing their GitHub account's authority to a Toolkit. The actor may be a GitHub organization owner, repository administrator, or ordinary organization member independently of their Azents management authority.

### Primary Scenario

The manager connects their GitHub account without copying a token, prepares access to personal and multiple organization repositories, confirms the Toolkit's existing sharing scope, and lets authorized participants use the connected Agent to perform GitHub work under the connected account's authority. Participants do not need to supply their own GitHub accounts.

## Supporting Scenarios

- An actor with GitHub installation authority completes App installation, repository selection, and personal authorization in one coherent setup journey.
- An ordinary GitHub organization member authorizes their account, requests missing App access through GitHub, and continues using repositories that are already available.
- A personal-account owner installs the selected GitHub App for private repositories without requiring organization approval.
- A deployment without a configured Platform App offers PAT and bring-your-own-App setup, including user-account authorization with the provided App.
- One Agent works with repositories owned by a personal account and multiple organizations in the same task.
- Existing installation-authority Toolkits continue operating unchanged.

## Goals

- Add user-account authority for both Platform and bring-your-own Apps alongside their existing installation authority.
- Delegate the connected account to the Toolkit's existing Agent-only or Workspace-shared use scope.
- Make execution identity, usable targets, partial readiness, and recovery understandable.
- Preserve current integration modes, access controls, and existing resources.

## Non-Goals

- Requester-relative personal credential selection or a general personal-tool system.
- A global credential hub, generic delegation engine, per-request personal approvals, or a new organization-request service.
- New Azents roles or a credential-contribution flow for users lacking current Toolkit management authority.
- A separate OAuth App, automatic PAT generation, or organization-policy bypass.
- An additional Toolkit-specific repository security allowlist.
- Automatic conversion of existing credentials or fallback from user authority to App authority.
- Removing existing PAT or bring-your-own-App integrations.
- Changing existing External Channel or Scheduled Task participation policies.

## Requirements

### REQ-1. Two explicit GitHub App execution authorities

Both Platform and bring-your-own GitHub App integrations support user-account and App-installation execution authority as explicitly distinct options.

**Acceptance criteria**

- A manager can distinguish the two authorities before connecting and in the saved Toolkit.
- Existing App Toolkits retain their credentials, targets, attachments, and execution authority.
- Selecting the new option does not migrate or reconnect unrelated existing resources.
- User authorization failure does not silently use App-installation, PAT, or another account's authority.

### REQ-2. Connected-account delegation, independent of participants

A manager connects a GitHub account for the Toolkit's existing sharing scope. Authorized Agent participants can use it without connecting their own GitHub account.

**Acceptance criteria**

- Another authorized participant's GitHub request uses the account connected to that Toolkit, rather than the message author's account.
- The connected account and Agent-only or Workspace-shared use scope are visible before confirmation.
- Setup explains that authorized participants and existing automatic execution can use the Toolkit and that repository content may enter the Agent's ordinary conversation/output context.
- Connecting a Toolkit grants no new Agent, Session, Workspace, or External Channel participation authority.
- GitHub execution identity and the person requesting an Azents action are not misrepresented as the same actor.

### REQ-3. Personal and multi-organization repository access

One user-account Toolkit can access available repositories across a personal account and multiple organizations where the same selected GitHub App is installed, whether platform-provided or manager-provided.

**Acceptance criteria**

- A single Agent task can use a personal repository and repositories in two organizations without requiring separate Toolkits or duplicate account authorizations per organization.
- The UI identifies targets by repository owner and presents readiness without an exclusive active-organization filter.
- Existing App mode retains multi-installation access and its current CLI default-installation behavior.
- Removing or losing access to one target does not disable independently usable targets, unless the account authorization itself becomes invalid.

### REQ-4. Repository authority follows the connected user and App

User-account operations respect the connected account's current authority and the App's permitted resources and actions.

**Acceptance criteria**

- App write permission does not allow a user-account operation to write where the connected user has read-only permission.
- A participant's broader permissions do not enlarge the connected account's execution authority.
- Repository policies such as branch protection remain applicable.
- Repository-readiness lists are not presented as a stronger token-level allowlist than the integration actually enforces.

### REQ-5. Coherent installation and authorization setup

Setup connects the account without requiring user-token strings or per-organization user authorizations. Platform setup does not require managers to supply App credentials. Bring-your-own-App setup requires the manager to configure their own App's necessary registration and credentials rather than depending on the platform's App.

**Acceptance criteria**

- GitHub installation and personal authorization form one understandable setup journey with a return to the originating Toolkit context.
- Already-installed targets do not require redundant installation.
- GitHub organization installation authority and Azents Toolkit management authority remain distinct.
- A GitHub administrator installing the App for a member does not replace that member's connected execution account with the administrator's account.
- A personal-account owner can prepare private-repository access through their account's App installation.

### REQ-6. Partial readiness and administrator requests

Account authorization and repository availability are separate states with actionable recovery.

**Acceptance criteria**

- An unavailable organization does not prevent use of ready personal or other organization repositories.
- Missing targets have a GitHub install/configure/request or access-recheck path appropriate to available evidence.
- Opening a request page is not reported as a submitted request or approval-wait state.
- Organization request restrictions receive a useful administrator handoff instead of an impossible action.
- Inaccessible private resources are not fabricated or exposed in readiness listings.
- Unknown access failures are not invariably labeled as App-not-installed failures.

### REQ-7. Setup authority and cancellation safety

User-account setup obeys existing Toolkit management boundaries and preserves the currently saved connection until a replacement is confirmed.

**Acceptance criteria**

- Workspace-shared and Agent-only setup follow their existing management boundaries.
- Expired, replayed, mismatched, or unauthorized setup completion does not connect credentials to another user, Toolkit, Workspace, or Agent.
- A changed Azents login, changed management authority, or changed selected App during setup cannot silently attach the result to a different context.
- Cancelled, denied, failed, or merely requested installation attempts do not overwrite a working saved connection.
- Browser callback/popup failure offers recovery rather than displaying a misleading success.

### REQ-8. Non-expiring user-account authorization

New Platform and BYOA user-account connections use GitHub App user access tokens without a scheduled expiration. Their App registration must opt out of user-to-server token expiration. This feature does not implement expiring user credentials or automatic refresh-token rotation.

**Acceptance criteria**

- Setup explains the required GitHub App expiration setting and does not request a per-authorization override that forces expiring tokens.
- The returned authorization is checked before activation; expiring user-token responses receive actionable App-configuration guidance and do not replace a working saved connection.
- Accepted user connections do not require periodic refresh, a refresh owner, or a renewal process.
- Concurrent shared-Toolkit use and a concurrent reconnect/disconnect do not corrupt the saved credential or publish a result for a replaced connection.
- A token without scheduled expiry may still be revoked or lose access. Definite authentication failure offers reauthorization, while transient provider failures do not automatically delete the connection.
- Target-specific permission or SSO problems are distinguished from account authorization failure as far as evidence allows.
- No failure automatically substitutes App-installation authority or another account's credential.
- Existing installation-token expiration/reissuance and existing unrelated OAuth integrations retain their behavior.

### REQ-9. Account replacement and disconnection scope

Managers can distinguish reauthorizing the same account, changing the execution account, disconnecting a Toolkit, and detaching it from one Agent.

**Acceptance criteria**

- Reauthorization of the same account preserves applicable Toolkit configuration.
- Account or authentication-mode replacement shows the affected scope and requires explicit confirmation.
- Disconnecting a shared Toolkit explains its impact on Agents using that Toolkit.
- Detaching a shared Toolkit from one Agent does not disconnect other Agents' use.
- A local Toolkit disconnection does not silently uninstall the App for an organization or disconnect unrelated user authorizations or Toolkits.
- Disconnecting or deleting a user-account Toolkit revokes its user token at GitHub; confirmed replacement revokes the superseded token, and cancelled or rejected setup revokes any token issued for the discarded candidate. Merely removing local credential data is not sufficient cleanup.
- Token cleanup is specific to the affected token, not cancellation of the account's entire App authorization. Provider cleanup failure is surfaced as incomplete cleanup rather than reported as successful revocation, while the retired credential remains unavailable for Agent execution.
- No claim is made that disconnection reverses completed GitHub writes or erases already imported conversation content.
- The Design must state the enforceable cessation boundary for credentials already used by an in-flight external request or optional Runtime process; instant retroactive cancellation is not assumed.

### REQ-10. Existing GitHub execution surfaces and safe disclosure

User-account authority is usable through the existing GitHub Toolkit operation surface and optional Runtime Git/GitHub CLI integration, without changing existing modes' defaults or disclosure contracts.

**Acceptance criteria**

- GitHub tool calls and, when the existing optional Runtime integration is enabled, Git/CLI commands use the selected execution authority consistently.
- Optional Runtime credential use retains explicit opt-in and its existing leakage-risk disclosure; it is not enabled by default by account connection.
- Tokens, OAuth codes, refresh credentials, private keys, and provider credential payloads do not enter public API descriptions, UI state summaries, or operational logs.
- Unprivileged participants or public channels do not receive private connection-management lists as status messages.
- App identity changes cannot silently reuse a connection issued for a different App; unchanged-App credential rotation remains distinguishable from identity replacement.

### REQ-11. Operable UI and observable verification

Setup and recovery are understandable across supported product locales and desktop/mobile presentation.

**Acceptance criteria**

- Connection identity, sharing scope, readiness, and actionable recovery are not conveyed through color alone.
- Keyboard operation and mobile layout preserve confirmation information and cancellation/recovery actions.
- Automated verification covers user authority, non-expiring-token acceptance and expiring-token rejection, existing App mode, personal plus multi-org access, partial readiness, management checks, concurrent replacement, and disconnection.
- Fixture evidence and live-provider evidence are reported separately; a concept mock is not claimed as an authenticated product test.

### REQ-12. Hide unconfigured Platform choices

When System Settings has no configured Platform GitHub App, Platform-based authentication is absent from selectable setup choices.

**Acceptance criteria**

- New Toolkit setup and replacement-method choices omit both Platform App-installation and Platform user-account options when the Platform App is not configured.
- The same rule applies in Workspace-shared and Agent-only Toolkit setup.
- PAT and bring-your-own-App options remain selectable and are not hidden because of missing Platform configuration.
- A saved Platform Toolkit whose platform configuration is subsequently absent retains its saved identity and settings and explains the missing configuration; it is not deleted, misrepresented as a different method, or silently converted.
- Availability presentation reveals no System Settings secrets and gives ordinary Toolkit managers no Admin API or System Settings mutation authority.
- This requirement concerns missing Platform configuration; it does not authorize treating every transient provider-health error as an unconfigured platform or hiding unrelated methods.

### REQ-13. Bring-your-own-App user authorization

A manager can use their own registered GitHub App for user-account Toolkit delegation without configuring the platform-wide App.

**Acceptance criteria**

- Bring-your-own-App setup offers both the existing App-installation authority and the new OAuth user-account authority.
- User-account setup explains the required App registration, OAuth client credentials, and callback configuration and provides actionable validation before claiming the connection is ready.
- A BYOA user connection uses that App's authorization and the connected user's authority, never the platform App's OAuth credentials.
- Personal and multiple organization repositories where that same provided App is installed can be used together in one Toolkit.
- Connected-account delegation, partial readiness, non-expiring-token validation, replacement, disconnection, management checks, and safe disclosure have the same required outcomes as REQ-2 through REQ-11.
- Existing BYOA installation credentials continue to work without being required to acquire user-OAuth configuration.
- Provider registration mistakes or unsupported App settings do not silently use a Platform App or another credential source.
- Tests cover BYOA user authorization and multi-org execution in an environment with no Platform App configured, alongside existing BYOA-installation and Platform-mode regression cases.

## Fixed Constraints

Requester-confirmed direction: delegate the connected user's authority through the Toolkit; support both App and user modes for Platform and bring-your-own Apps; support personal plus multiple organizations simultaneously; hide unconfigured Platform choices while retaining PAT/BYOA choices; leave requester-relative personal tools for separate future work.

Current management, sharing, participation, secret-handling, and optional Runtime integration contracts remain the baseline unless a confirmed requirement explicitly changes them.

The UI baseline is the current Toolkit catalog and compact connection-list flow in main `279db5f1fb52c634570d3d5eff6a669d2becdfd3`, refreshed at the requester's direction. Preserve its new/workspace catalog tabs, compact saved-connection cards with details, immediate Toolkit mutation semantics independent of parent Agent save, and distinction between persisted Toolkit addition and completed external authorization. Missing Platform configuration removes only the Platform authentication choices, not the GitHub catalog tile needed for PAT/BYOA. Provider readiness and actual account/repository permissions must not be inferred from catalog presence, toolset selection, or successful Toolkit creation.

### Provider failures rather than a new contributor-offboarding policy

The requester confirmed that the integration should surface actual authentication or authorization errors instead of introducing a separate automatic disconnection policy tied to the contributor's Azents Workspace departure or suspension. Membership changes continue to govern who may manage or use Azents resources through existing authority boundaries; they do not by themselves disconnect this delegated GitHub credential.

If GitHub authority remains valid, a saved Toolkit may continue operating. If GitHub approval is revoked or repository access is lost, REQ-4 and REQ-8 govern the resulting failure and recovery. Non-expiring user-token selection does not change the existing App-installation token reissuance contract or authorize silent fallback.

## Open Assumptions and Feasibility Limits

- Repository discovery and permission metadata can support useful readiness summaries, but not complete diagnosis of resources that GitHub intentionally conceals.
- The selected Platform or provided App exposes the necessary approved actions; actual registration, callback compatibility, and authenticated live use require implementation-time verification.
- Non-expiring user access requires the selected App's supported registration setting; no refresh-token owner, token-rotation claim, schema-version feature, or renewal service is part of this user-connection scope.
- Runtime process credentials and provider token revocation have real in-flight limits. The Design must provide an accurate, testable recovery/cessation contract rather than assuming immediate credential recall.

## Confirmation

The requester approved REQ-1 through REQ-13 on 2026-10-08 after the Platform-availability and BYOA-user additions were incorporated, then clarified provider-error behavior without a new contributor-offboarding policy. The former OP-1 is resolved by the fixed constraint above. Requirements confirmation does not approve an unpresented storage architecture, renewal protocol, Runtime authentication mechanism, ADR, Design, or implementation.

The requester subsequently selected non-expiring user-account tokens on 2026-10-08. REQ-8 and the related verification and constraints above replace the previous expiring-token/renewal hypothesis before implementation. The non-expiring choice applies to Platform and BYOA user mode; existing installation mode remains unchanged.

The requester then explicitly required GitHub token revocation on cleanup on 2026-10-08. REQ-9 records that outcome. An unobserved possibility of token reuse does not justify substituting local-only removal for provider revocation.
