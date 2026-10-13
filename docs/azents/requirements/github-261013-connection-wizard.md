---
title: "GitHub Toolkit Connection Wizard Requirements"
created: 2026-10-13
implemented: 2026-10-13
document_role: primary
document_type: requirements
snapshot_id: github-261013
tags: [github, toolkit, frontend, security]
---

# GitHub Toolkit Connection Wizard Requirements

- Snapshot: `github-261013`
- Document reference: `github-261013/REQ`
- Confirmed on: 2026-10-13, before ADR decisions.

## Problem

Managers currently face authentication implementation types and integration settings together. They need to understand whether GitHub work runs as their GitHub account or a GitHub App, choose an available authentication method, verify the connection, and understand the final execution scope before publishing a Toolkit. Presenting identity, credentials, toolsets, and Runtime token exposure as unrelated fields obscures those choices.

## Primary Context

### Primary Actor

An authorized Toolkit manager creating a GitHub Toolkit within an existing Agent-owned or Workspace-shared management context.

### Primary Scenario

The manager starts a new GitHub connection, selects its execution identity and an available authentication method, completes the applicable connection checks, chooses the exposed GitHub features and optional Runtime token injection, reviews the actual identity and ownership scope, and explicitly publishes a usable Toolkit with those final settings.

## Supporting Scenarios or Effects

- Return from external GitHub authorization to the originating setup context.
- Reset connection setup or close it before publication without creating an executable Toolkit.
- Recover from unavailable registration, provider denial, invalid credentials, or expired setup.
- Preserve existing saved Toolkits and existing detail/edit/disconnect behavior outside this new-creation flow.

## Goals

- Separate execution identity from authentication method and Toolkit ownership.
- Make the applicable settings appear progressively on one setup surface.
- Save the settings actually chosen after connection verification.
- Preserve explicit publication, ownership boundaries, credential safety, and existing execution authority.

## Non-Goals

- Automatically create a GitHub App on GitHub or introduce a manifest-based App creation flow.
- Add an authentication mode, credential fallback, token-refresh actor, or new GitHub permission.
- Redesign existing saved-Toolkit editing, disconnected-state management, or Workspace sharing policy.
- Redesign other Toolkit types, introduce durable user-facing setup drafts, or add a product versioning feature.
- Remove supported GitHub feature groups because the concept illustration shows only a subset.
- Change Worker execution semantics or claim that local cancellation reverses GitHub installations, approvals, external writes, or copied credentials.
- Production deployment, live credential changes, or merge without separate explicit authorization.

## Requirements

### REQ-1. Progressive single-surface creation

New GitHub Toolkit creation must use one setup surface where completing a choice reveals the applicable next section below it. Earlier sections remain available for review and correction. External GitHub authentication may navigate outside the setup surface.

**Acceptance criteria**

- The visible flow is identity, authentication method, connection verification/input, GitHub feature selection, Runtime option, and final review.
- The flow is not a sequence of separate internal step pages.
- Shared and Agent-owned creation entry points use the same behavioral model while retaining their ownership context.
- Changing an upstream identity or authentication choice invalidates dependent connection evidence and prevents final publication using stale evidence.

### REQ-2. Identity-centered wording

The first choice distinguishes the manager's GitHub account from GitHub App execution, without presenting ownership scope as identity.

**Acceptance criteria**

- The Korean localized title is `GitHub에 어떻게 연결할까요?`.
- The personal choice is `내 GitHub 계정으로 연결`, described as `내 계정으로 GitHub 작업을 수행합니다.`.
- The App choice is `GitHub App으로 연결`, described as `개인 계정 대신 GitHub App으로 작업을 수행합니다.`.
- The next section uses `인증 방법을 선택하세요` in Korean; equivalent natural wording is supplied in every supported locale.
- Selecting a personal identity does not imply private Toolkit ownership or change who may execute an existing shared connection.

### REQ-3. Applicable authentication choices

Offer only methods applicable to the selected identity and confirmed registration availability.

**Acceptance criteria**

- Personal identity supports a configured Platform App, a self-managed GitHub App, and PAT.
- App identity supports a configured Platform App and a self-managed GitHub App; it never offers PAT.
- A Platform App confirmed unusable for the chosen identity is omitted; loading and request errors are represented as loading/retry, not as absence.
- The Platform choice is localized as `GitHub App · <actual App name>` rather than hardcoding an example App name.
- The self-managed choice is `새로운 GitHub App 등록`, is first-class rather than hidden under advanced settings, and accepts information for an App already created on GitHub.
- App registration help distinguishes user-account authorization from installation authority.

### REQ-4. Truthful connection verification

Connection input and verification must match the selected authentication mode and disclose the actual verified identity and relevant targets without claiming universal access.

**Acceptance criteria**

- PAT uses token input and a connection check; it does not display OAuth return instructions.
- User-account App authorization verifies and displays the GitHub account and selected App/source before final publication.
- App execution displays the actual App separately from selected installation accounts or organizations.
- Opening an installation or request link does not count as verified installation or approved repository access.
- Invalid credentials and denied, failed, expired, or incompatible setup do not appear as a successful usable connection.
- Tokens, client secrets, private keys, and unredacted credentials are absent from display, browser-persisted setup context, logs, and verification evidence.

### REQ-5. Feature selection after verification

The manager selects which GitHub feature groups are exposed after connection verification.

**Acceptance criteria**

- All currently supported feature groups remain configurable, including groups omitted from the concept illustration.
- The UI explains that feature selection does not grant GitHub repository permissions.
- Changing feature choices before final publication changes the settings actually saved without changing the verified execution identity.

### REQ-6. Explicit Runtime token opt-in

Runtime token injection remains optional and off by default for new connections.

**Acceptance criteria**

- The manager can continue without Runtime token injection.
- Enabling it discloses that Agent processes can read or copy the token and requires acknowledgment of the exposure risk before publication.
- Final review and the saved setting agree with the final opt-in choice.
- The new setup flow preserves the existing subsequent-command injection and non-recallability of already admitted or copied credentials.

### REQ-7. Final review and explicit publication

Only the final explicit action publishes a new executable Toolkit, using the settings the manager last reviewed.

**Acceptance criteria**

- Final review shows connection name, actual execution identity/App, Agent-owned or Workspace-shared scope, selected feature groups, and Runtime injection choice.
- Shared scope makes clear that authorized participants and existing automatic execution may use the same saved execution account.
- No saved or attachable/executable Toolkit is published merely by selecting an identity, checking credentials, or returning from GitHub.
- Name and other supported setup settings changed after authorization are reflected in the final saved result without silently reverting to pre-authorization values.
- Publication failure does not leave a partially published user-account Toolkit or imply success.

### REQ-8. Reset and close before publication

The connection result for both identities provides a recognizable reset button. Closing the setup window is the cancellation affordance; the final review has no duplicate cancel button.

**Acceptance criteria**

- Korean reset wording is `연결 다시 설정`, styled as a visible button for personal and App execution.
- Reset re-enters connection setup and invalidates the previous candidate or verification; it does not delete/disconnect an existing saved connection.
- Explicit close before final publication abandons the unpublished setup and clears local secrets; late callbacks cannot publish it automatically.
- Cancellation/cleanup failure is not described as proof of provider revocation.
- Only while an already-dispatched final publication outcome is pending, temporarily prevent setup close/reset and communicate the in-progress result. Restore applicable controls after the authoritative success or failure outcome. Pending OAuth authorization or candidate review alone does not hide the close control.

### REQ-9. Security and existing authority

The new flow preserves the existing exact management scope and five authentication execution modes.

**Acceptance criteria**

- Agent-owned setup remains limited to the exact authorized Agent; shared setup retains its existing Workspace management requirements.
- Wrong-user, wrong-authentication-session, wrong-Workspace, wrong-Agent, stale attempt, changed App, and incompatible callback requests fail closed.
- PAT, installation, and user-account credentials are not converted or substituted for one another.
- Existing saved connections, namespaces, feature settings, and Runtime defaults remain intact when the new creation UI is introduced.

### REQ-10. Accessible, responsive, and recoverable controls

The flow is operable on desktop and mobile, by keyboard and assistive technology, and across supported locales.

**Acceptance criteria**

- At desktop and a 390px-wide mobile viewport, choices, inputs, reset, close, and final confirmation remain usable without horizontal overflow or clipped primary controls.
- Newly revealed sections, connection progress, errors, and next actions are understandable without relying on color alone.
- Error/retry remains distinguishable from confirmed absence and from successful connection verification.
- Returning from GitHub restores the exact originating management context and permits feature/Runtime/final-review continuation without exposing authorization code or state in the final setup URL.

## Fixed Constraints

- Keep existing Toolkit-owned account authority, Workspace membership and exact Agent ownership boundaries.
- Keep final publication as the only creation authority; local UI connection evidence is not a reusable credential authority.
- Use current supported locales and product UI components rather than treating concept styling or sample identities as real product contracts.
- Keep existing non-expiring GitHub App user-token requirement and bounded fail-open provider cleanup; no refresh or new cleanup subsystem is requested.
- Implementation follows approval of the complete technical Design. Production credential changes, migration execution, deployment and merge remain separately authorized actions.

## Confirmed Scope Boundaries

- The approved current concept is a new-creation flow. Existing saved-Toolkit editing remains unchanged unless separately requested.
- The self-managed registration choice means entering an already-created App's information, consistent with the approved input screen; automatic GitHub App creation is excluded.
- REQ-8 publication-race policy: temporarily prevent close/reset only while the final save outcome is pending, then show the authoritative success or failure result. Pending OAuth candidates are not a reason to hide the close control.

## Confirmation

The requester explicitly confirmed the complete repository Requirements on 2026-10-13, including the scope boundaries and the policy that close/reset is temporarily prevented only while the final publication outcome is pending. Confirmation preceded acceptance of any ADR decision. The product interaction and localized wording were also approved on 2026-10-13. Later on the same date the requester expanded the execution request to implementation; that does not change REQ-1 through REQ-10 and remains subject to complete Design approval. Production deployment and merge were not requested.
