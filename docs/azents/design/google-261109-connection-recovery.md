---
title: "Google Connection Recovery Design"
created: 2026-11-09
implemented: 2026-11-09
document_role: primary
document_type: design
snapshot_id: google-261109
tags: [google, frontend, security, testenv]
---

# Google Connection Recovery Design

Authority: [Requirements](../requirements/google-261109-connection-recovery.md)
and [decisions](../adr/google-261109-connection-recovery.md).

## Design Authority

Design revision: `3`.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Compact provider-owned Google editor replaces nested generic form | REQ-3 | required |
| M2 | Normal review automatically confirms; exceptional results expose reauthentication/cancel only | REQ-2, revised REQ-5, ADR-D4 | required |
| M6 | Every service exposes visible presets that affect only its own selection | revised REQ-3, ADR-D4, ADR-D5 | required |
| M3 | Explicit apply includes metadata atomically; recovery omits it and retains tab draft | REQ-4, ADR-D2 | derived |
| M4 | Standard authorized card recovery dispatches to Google and restores original context | REQ-1, ADR-D3 | required |
| M5 | Existing exact-attempt, renewal, scope, manager, target and no-replay fences remain | REQ-6, current Google connection Spec | existing |

## Architecture and Lifecycle

`GoogleSetup` owns the complete Google surface for both creation and editing;
`ToolkitForm` selects it before rendering generic preparation/review sections.
Container state and pure decision helpers determine dirty state, actual grant
coverage, exception reason, recovery vs apply intent and bounded draft restoration.
The existing typed backend catalog remains the tool-group authority. The editor
uses visible presets, service disclosures and an advanced metadata section with a reachable apply
footer. Existing Picker and local disconnect retain their controls and checks.

The normal path is SELECT -> AUTHORIZING -> VERIFYING -> CONFIRMING -> COMPLETE.
REVIEW is exceptional when the verified principal differs or selected operations
lack actual permission. Exceptional results preserve the existing connection
and expose one prominent Reauthenticate button plus cancellation. There is no
separate account-change action or partial-result publication control.
The controller preserves existing expiry and exact resume identity validation.
Uncertain publication is UNKNOWN and allows outcome observation, never automatic
resubmission. Cancellation is local and cannot revoke remote consent/effects.

Editor drafts contain only bounded token-free metadata, selected groups/services,
timeout and intent. Browser storage is tab-scoped, schema-decoded and exact-target
matched. Saved provider identity is compared with the verified review by issuer
and subject, not display email. Recovery uses saved selection and leaves the
editor draft untouched. Apply uses the selected draft and is the sole intent
allowed to include metadata. No metadata is accepted as credential authority.

Reuse the current revision-fenced service save to optionally apply metadata and
timeout in its database transaction. Reconnect confirmation optionally carries the
same explicit metadata and applies it with credential/config publication. Omitted
metadata preserves existing fields; no new schema/table or migration. Current
clients may continue sending the existing service/confirmation shape. Regenerate
clients from actual OpenAPI changes; do not hand-edit generated code.

The standard Agent action recognizes Google, retains owner-scope checks, and opens
its provider recovery directly. Shared targets use shared scope, not the current
Agent scope. Context restoration must not allow arbitrary redirects or authorize
a cross-owner connection. All provider reads/writes still reauthorize server-side.

## Removal and Replacement

| Obsolete unit | Authority | Replacement | Boundary and absence evidence |
| --- | --- | --- | --- |
| Google inside generic three-stage edit form | M1 | Complete compact Google form | Actual form render/story |
| Mandatory normal REVIEW/publish button | M2 | Auto confirm with exceptional REVIEW | Controller/component tests |
| Separate service save plus generic metadata save | M3 | One explicit apply operation | Atomic repository tests |
| Google edit detour from standard recovery | M4 | Provider-specific direct action | Card and controller tests |
| Old normal-review copy/stories/assertions | M1, M2 | Compact and exceptional state stories | Search plus unit/component suite |
| Separate account-change and partial-result acceptance actions | revised REQ-5, ADR-D4 | Single Reauthenticate action; exceptional results remain uncommitted | Container and component tests |
| Preset disclosure | revised REQ-3, M6 | Directly visible permission preset buttons | Default and mobile component tests |

Existing staged server endpoints and historical outcomes are retained, not removed.

## Security, Compatibility and Operations

No OAuth scope expansion, token storage in browser drafts, remote calls in database
transactions, alternate grant authority, or automatic tool replay. Server publication
continues to fence target/client/manager and handle exact historical outcomes.
Metadata updates reuse canonical identifier validation and namespace collision
checks. A stale revision/owner or failed validation rolls back the complete apply.
No operational rollout switch or legacy fallback. Existing iOS payloads remain valid.
Failures remain failures; completion is acknowledged before optional list refresh.

## Test Strategy

Retain the minimal cross-boundary Google connection E2E path, adapting it to normal
automatic completion. Most state combinations belong in pure decision, container,
backend transaction and Storybook tests, not new E2E permutations. Use existing
synthetic OAuth fixture support; no live Google credentials or paid model calls
are required. Cover unchanged identity, partial/unknown/empty grants, renewable
checks, changed account, return context, draft restoration, cancellation, exact
uncertainty lookup, stale callbacks and permissions. Backend tests exercise atomic
metadata/service/timeout apply, stale revisions, identifier conflicts and reconnect
metadata omission. Component stories cover creation/compact edit, disclosures,
clean/dirty apply, status errors, exceptional review, disabled permissions, Picker,
disconnect, keyboard and mobile. Run format/lint/typecheck/unit/component and
backend targeted tests; CI owns the complete required matrix on the final SHA.
Capture actual implemented components with app theme/fonts at desktop/mobile DPR 1.
Live OAuth and production behavior remain explicitly unverified, not silently passed.

## Feasibility and Authority Check

Current hooks, resume/callback lifecycle, typed catalog, owner adapters and Google
repository provide the required boundaries. Existing service save and publication
already execute inside owner-fenced transactions; extending their typed input is
local to the approved single-apply outcome. No new material choice remains outside
the approved proposal. Implementation must verify exact navigation/draft fencing
and atomic identifier validation before reporting full completion.

## Design Approval

- Mode: Collaborative
- Decision owner: requester
- Approved on: 2026-11-09
- Approved Design revision: 3
- Approved authority IDs: M1, M2, M3, M4, M5, M6
- Approved scope: the presented compact editor, standard Google recovery, normal
  automatic completion, one reauthentication action, visible presets and single settings apply.
  Requester instructed implementation and a PR; local mechanisms above derive
  from that scope and retained contracts, not a new independent product decision.
