---
title: "Google Tool Group Consent Design"
created: 2026-10-22
implemented: 2026-10-22
document_role: primary
document_type: design
snapshot_id: googletools-261022
tags: [google, toolkit, oauth, security, frontend, backend]
---

# Google Tool Group Consent Design

Authority: [Requirements](../requirements/googletools-261022-tool-group-consent.md)
and [decisions](../adr/googletools-261022-tool-group-consent.md).

## Current Behavior and Gap

Main Web requests all supported scopes for enabled services. Saved configuration
has services, request scopes and timeout, but no selected tool-group ceiling.
Management and runtime derive tools from actual scopes. Presets and final group
results do not exist. Existing current-authority checks already reload service,
connection, owner and revision before each dispatched effect.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Service-specific editable tool groups and presets | REQ-1, REQ-2; ADR-D2 | required |
| M2 | Server-owned sufficient scope construction for selected tools | REQ-3; ADR-D2 | required |
| M3 | Final group projection from selection and actual grants | REQ-4; ADR-D1 | required |
| M4 | Persistent selection ceiling at exposure and execution | REQ-1, REQ-4; ADR-D1 | decided |
| M5 | Data-preserving explicit conversion for saved configs and attempts | fixed preservation constraints; ADR-D3 | derived |
| M6 | Calendar guest create/patch/result controls | REQ-5; ADR-D4 | required |
| M7 | Existing ownership, resource, refresh and no-replay boundaries | Google Connection Living Spec; fixed constraints | existing |

## Catalog and User Flow

A backend-owned closed catalog partitions supported model operations by user
capability, not by raw Google scope strings. Internal sender-verification methods
are prerequisites rather than separate user groups.

Candidate groups to validate against the full method catalog:

- Gmail: read mail/threads/attachments; labels; drafts; send/reply/forward;
  organize/trash/restore; filters and historical filter application.
- Calendar: calendar/event reads; availability and suggestions; event management
  and responses; status events; calendar creation.
- Drive: search/metadata/content/export; file and folder management/imports;
  sharing; ownership transfer.

Presets edit the visible group selection: read-only, everyday assistance, all
supported groups, or clear. Dangerous capabilities remain visible and removable.
Preset identifiers are not persisted runtime policy. No hidden all-access initial
selection is introduced for new connections.

The final review shows every selected group's usable operation count and
permitted/partial/unavailable state. An empty actual grant does not publish a
usable connection. A partial group does not fabricate authorization for its
unavailable members. Final user confirmation retains the existing explicit save
and uncertain-publication outcome lookup.

## Data, Interfaces and Runtime

Add an explicit closed selected-group field through connect input, encrypted
GoogleSetup, reviewed settings, saved Toolkit config and nonsecret status/review
outputs. Validate group service membership at request ingress. Construct request
scopes from the selected operations' supported sufficient method scopes, including
necessary argument-dependent prerequisites; remove redundant scopes only when the
existing compiled method policy still admits every intended method.
Drive write/sharing/ownership groups use sufficient `drive.file` scope, retaining
Google's app-authorized resource restriction; whole-Drive reading is a separate
read group. Existing broader grants remain unchanged and still require selected
operations.

Expose catalog metadata through a token-free management preparation surface or
an equivalently source-generated shared catalog. Do not trust Web-provided tool
lists, grant booleans or arbitrary scope lists as authority. Generated API clients
must be regenerated from source contracts.

For current saved configuration, runtime exposure is:

`enabled service AND selected group operation AND sufficient actual grants`.

Invocation admission and every pre-effect recheck apply the same selection ceiling
plus existing owner/client/resource/revision checks. Internal SDK prerequisites
must have actual grants but need not be exposed as independent model tools.
Concurrent local narrowing invalidates previously admitted operations through
current-state revalidation. It does not revoke Google credentials remotely.

Final confirmation is bounded by the exact reviewed selection; a broader provider
grant or resumed old review cannot add unreviewed groups. Group changes during
review can narrow the saved result. Group expansion needing new permissions uses
explicit reconnect, not automatic OAuth or token changes.

## Migration and Operations

A normal generated Alembic migration converts all existing Google Toolkit configs
to explicit groups preserving their previously exposed operations. Preserve saved
actual scope evidence and credentials. Treat encrypted pending setup, nested saved
targets and stored final-settings receipts consistently; validate and stage all
transformations before writes and use the existing transaction for atomicity.
No permanent missing-field legacy runtime mode is introduced.

Feasibility of encrypted pending-attempt conversion with deployment encryption
configuration must be verified before implementation. If unavailable, do not
silently discard attempts or introduce a fallback; report the specific blocker.
No live DB migration, reauthentication or deployment is part of code delivery.
Rollback must not reinterpret explicit selections as unconstrained authorization.

## Calendar Independent Delivery

Create adds required nullable strict booleans for guest modification, invitations
and guest visibility. Null omits the SDK field to retain Google's default. Patch
uses optional strict boolean keys and preserves omitted privileges. Responses
retain provider values and missing values remain unknown. No notification-control
changes. This mechanism is implemented and independently reviewed in the separate
Calendar worktree; the group feature does not depend on it.

## Removal and Replacement

| Existing unit | Removal authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| All-scope service request construction | REQ-3 | Selected-group sufficient scopes | group feature activation | request tests |
| Actual-grants-only operation exposure/admission | REQ-1, REQ-4, ADR-D1 | selection intersection with actual grants | same release | broad-grant negative authorization tests |
| Saved config without selection | preservation constraints, ADR-D3 | explicit backfilled group set | migration before new worker | migration integration tests |
| Service-only setup UI and copy | REQ-1, REQ-2, REQ-4 | group/preset selection and final review | same release | component contracts |
| Generated management schemas | affected interface contract | regenerated API clients | same PR | regeneration/typecheck |

## Test Strategy

- Representative existing shared/Agent/personal setup E2E paths prove the connect,
  callback, review and final-save integration with synthetic provider responses.
  Do not mutate live Google grants for CI.
- Component tests own preset editing, empty/custom selections, partial and missing
  grants, unavailable members, saved/reconnect and mobile states. Add meaningful
  stories to the authoritative required CI portfolio.
- Domain tests prove catalog coverage, sufficient scopes, no unrelated scope
  requests and selected-operation limits under broad actual grants.
- Repository/runtime integration tests prove persistence, publication subset rules,
  concurrent selection narrowing and old-data conversion while keeping secrets
  absent from evidence. Use actual PostgreSQL test infrastructure, not direct
  operational DB writes.
- Calendar tests prove true/false/null create serialization, strict patch/omission,
  actual model-handler SDK dispatch, provider response and unchanged notifications.
- Run Ruff, strict type checking, focused/full backend, generated-client checks,
  Web/Admin quality gates and current-SHA CI. Optional real-provider QA remains
  explicitly unverified without authorized prerequisites; synthetic tests are not
  live Google account verification.

## Feasibility and Verification

- Closed-catalog coverage and per-group/preset tests verify that sufficient scopes
  admit every selected operation and its argument-dependent prerequisites.
- Runtime tests verify broad grants cannot expose or invoke unselected writes and
  current group narrowing invalidates previously admitted operations.
- Real PostgreSQL tests verify selection persistence, confirmation subset limits,
  revision-fenced local changes, encrypted setup/target conversion, preserved
  create/reconnect receipts and atomic rollback without secret diagnostics.
- API contracts and public/admin Python and TypeScript clients are regenerated.
  Web tests and native component contracts cover selection, editable presets and
  final partial-group projection. Representative Required/Web E2E journeys use the
  new explicit fields and actual browser selections.
- Calendar M6 remains independently delivered in PR #2392; notification controls
  are unchanged. CI execution and any live-provider verification are reported
  separately from local checks. No operational migration is implied.

## Design Approval

- Mode: Collaborative, within the requester's explicit implementation/PR scope.
- Decision owner: requester for product scope; primary Agent for local implementation.
- Requester implementation instruction: 2026-10-22, excluding existing notifications.
- Revision/authority binding: revision 1, M1 through M7.
- Feasibility evidence covers the catalog, selected-operation ceiling, encrypted
  persistence conversion and generated contract checks above. Independent review
  covered authorization, migration preservation, credential boundaries and E2E
  propagation. This approval does not authorize live OAuth or deployment changes.
