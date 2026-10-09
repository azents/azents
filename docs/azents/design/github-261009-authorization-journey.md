---
title: "GitHub Toolkit Authorization Journey Design"
created: 2026-10-09
implemented: 2026-10-09
document_role: primary
document_type: design
snapshot_id: github-261009
tags: [github, toolkit, oauth, frontend, backend, security, testenv]
---

# GitHub Toolkit Authorization Journey Design

Authority: [Requirements](../requirements/github-261009-authorization-journey.md) and [ADR](../adr/github-261009-authorization-journey.md). One focused PR, root-owned implementation and integrated validation. Design delta: None from the requester-confirmed correction brief.

## Current Behavior and Required Replacement

Current setup requires an existing Toolkit ID, so creation commits an unauthenticated Toolkit and exits the form before authorization. Callback exchange leaves a static result page. An untouched Platform-user discriminator is misread as a registration edit. Visible source labels differ. Replace those boundaries without altering existing token authority, management/participation policy or fail-open revocation.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Automatic exact-surface return and server-review resumption without browser secrets or automatic confirmation | REQ-1, ADR-D2; existing OAuth binding | decided |
| M2 | Encrypted bounded new-creation authorization attempt with no published Toolkit | REQ-2, ADR-D1 | decided |
| M3 | Confirmation transaction creates Toolkit/current account/Agent-owned namespace together and rejects ordinary unauthenticated user-mode create | REQ-2/3, ADR-D1; current transaction/namespace rules | derived |
| M4 | Exact current authority, App/source/callback, one-use state/PKCE, expiry and captured token fail-open cleanup retained | REQ-2/3; current Toolkit Spec | existing |
| M5 | Same-registration edit inherits current account and blank write-only credentials; uniform localized source names | REQ-3/4 | required |

## Architecture and Interfaces

New-creation attempts are separate from Toolkit-bound reconnect attempts so existing saved Toolkit identity remains non-null and unambiguous. The attempt stores exact manager/auth Session/Workspace/optional owning Agent, encrypted submitted Toolkit create data plus registration/callback/PKCE/state, encrypted reviewed candidate, status and ten-minute expiration. It is never returned by Toolkit lists, attached to an Agent or resolved by Worker execution.

Creation preparation reuses the existing Toolkit identifier/config/credential validation and current Platform registration resolver outside repository transactions. Supported SDK App binding and token exchange/identity checks remain unchanged. A creation-specific connect/exchange/review/cancel/confirm surface follows both shared and exact Agent routes. Ordinary create rejects the two GitHub user-account discriminators; update remains unchanged for existing connections.

Every creation operation validates current management scope and exact initiating authentication context. Exchange claims the pending state once before provider effects; reviewed publication rechecks binding/expiry/current Platform generation. Confirmation rereads the candidate and desired Toolkit under lock, validates current authority/registration, then creates ToolkitConfig/current connection and the existing namespace reservation in one database-only transaction. A failed transaction publishes neither. Public review exposes desired nonsecret display/configuration and verified identity, never registration credentials or token material. Confirmation returns the created Toolkit ID for ordinary reads/navigation.

The creation form keeps the user in authorization rather than declaring a saved configuration. New authorization can navigate in the same browser context, preserving only nonsecret scope/attempt identity. Callback detects saved reconnect versus new creation and automatically restores review in the originating new form/Agent configuration surface. The final confirmation completes the parent form and invalidates normal queries. Existing edit callbacks retain popup notification and exact server review, and untouched edits keep the current connection ID.

## Failure, Migration and Rollout

Cancel, rejected exchange and expired access remove or terminally reject the pending attempt; any known issued candidate is captured for bounded awaited exact-token revocation after the local write. Cleanup failure does not publish a Toolkit or introduce retry/completion state. Cancellation propagates; unexpected defects remain visible. Browser reload resumes only the same scoped pending creation; no credential is copied into browser storage. No in-flight request/token-copy recall is claimed.

Add the creation-attempt persistence using an Alembic-generated linear migration. Existing Toolkits, connections and reconnect attempts are not converted or deleted. The API creation restriction and new flow ship together with generated clients and UI; all old creation fixtures for user mode must use the new real authorization flow. Rollback must not expose creation attempts as Toolkits. Production schema/application rollouts retain ordinary deployment practices; no operational write is performed by this implementation task.

## Removal and Replacement

| Obsolete behavior | Authority | Replacement | Boundary | Absence evidence |
| --- | --- | --- | --- | --- |
| New user mode saved before authorization | REQ-2, ADR-D1 | M2/M3 | shared/Agent UI and API | unauthenticated create rejects; cancel/failure leaves no Toolkit |
| Static callback requiring manual original-tab discovery | REQ-1, ADR-D2 | M1 | callback/return hosts | real browser automatic URL/surface review |
| False Platform registration-dirty predicate | REQ-3 | M5 | form edit | same-type/blank inputs preserve connection |
| Mixed source terminology | REQ-4 | M5 | all four locales/stories/details | same source prefixes and no visible BYOA mismatch |

Existing saved-disconnected Toolkits and PAT/installation flows remain supported. Old implemented snapshots are immutable; current behavior belongs to Living Specs.

## Test Strategy

E2E-first: real browser new shared and Agent-owned creation, automatic callback return, no saved item before final confirmation, cancellation without published Toolkit, same-registration edit inheritance and existing modes. Credential-free local GitHub SDK/MCP/browser fixture and synthetic App/account data only; no live GitHub action or registration change. Repository PostgreSQL tests cover atomic rollback, exact scope/owner/auth Session, replay/expiry, current Platform generation and no namespace exposure before publication. Provider/service tests cover non-expiring validation and fail-open candidate cleanup. Pure frontend/Storybook tests cover source labels, dirty predicates, resumed scope, invalid/error states. Run full affected quality/types, regenerate clients, documentation validation, one independent read-only review and entire PR CI. Root owns all implementation and validation directly.

## Authority and Feasibility

Requirements map to M1..M5 and each mechanism has confirmed source authority. Existing encrypted payloads, management scope checks, namespace repository, SDK operations and local synthetic fixture support the design. A separate creation attempt is necessary to avoid nullable or fabricated saved Toolkit identities. All new provider effects remain outside transactions. Remaining live-provider/Safari acceptance is reported separately, not inferred from Chromium fixture tests.

## Design Approval
Implementation evidence: root-owned backend quality/Ty and 174 focused tests,
frontend quality/types and 433 Node tests, and five assembled product E2E tests
passed. Product E2E covers existing callback/edit inheritance, mobile-sized shared
and Agent-owned authorization-before-create, and Platform/BYOA delegated
Worker/MCP/Runtime execution. The exact independent reviewer
`/root/github-user-reviewer` reviewed the stable integrated tracked/untracked diff
and found no critical or warning issues. Candidate/rollback/replay/scope/expiry
and current Platform generation are covered at repository/service boundaries.
All GitHub evidence uses synthetic credential-free fixtures; no live provider
issuance, iPhone Safari, deployment or merge is claimed.

- Mode: Collaborative.
- Decision owner: requester.
- Approved on: 2026-10-09.
- Approved Design revision: `1`.
- Approved authority IDs: `M1, M2, M3, M4, M5`.
- Approved scope: the bounded confirmation brief explicitly approved UI/API authorization-before-create, encrypted short-lived attempt only, atomic confirmed publication, automatic return, inherited edit authorization and consistent naming; immediate implementation was requested. No saved-draft lifecycle, credential fallback, merge/deployment or live provider mutation is authorized.
