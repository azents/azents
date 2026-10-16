---
title: "Browser Manual Keyboard Access Design"
created: 2026-10-16
tags: [browser, frontend, runtime, accessibility]
document_role: primary
document_type: design
snapshot_id: manualkeys-261016
---

# Browser Manual Keyboard Access Design

Authority: [Requirements](../requirements/manualkeys-261016-browser-keyboard-access.md) and [decisions](../adr/manualkeys-261016-browser-keyboard-access.md).

## Current behavior and gaps

Focused viewing has a generic hidden textarea with inputmode=none for physical keyboard and unrecognized-target pointer focus. Recognized native fields additionally publish transparent local receivers. The lower Paste/Edit pair depends on a selected acknowledged native receiver. There is no independent mobile keyboard activation.

Runner checks the native bounding rectangle's four corners inset one pixel and center. Rounded native controls exclude their extreme corner pixels from native hit testing, so an otherwise interactive text input is omitted. A synthetic native input with a public 8px-radius stylesheet produces four false corner hits and a true center hit; removing only the radius changes recognized regions from zero to one. No authenticated-site input or challenge submission is needed to reproduce this defect.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Discoverable focused-view keyboard button independent of native receiver membership | REQ-1, ADR-D1 | required |
| M2 | Synchronous local native receiver activation and existing direct-input stream to existing remote focus | REQ-2, ADR-D1, current Session Browser flow | existing |
| M3 | Transient activation retired on blur, scope/authority loss; existing source, privacy and recognized-field action eligibility | REQ-3, REQ-2, ADR-D1, current Session Browser flow | derived |
| M4 | Native rounded-outline inner rectangle with clipping and multipoint occlusion checks, unchanged editable identity | REQ-4, REQ-3, ADR-D2 | derived |

M1-M4 implement the requester's confirmed direction. No unresolved material decision remains. Helper names, equivalent geometry arithmetic and test fixture structure are local implementation details.

## Ownership and lifecycle

A dedicated web controller owns a stable reference to the generic receiver, independent of the interaction controller's currently focused receiver reference. Its explicit activation callback is called in the trusted button click/touch gesture: verify current eligibility, cancel held local input, set textual input mode and synchronously focus the generic receiver with preventScroll. No asynchronous request precedes focus, and no remote click/refind is sent. Physical keyboard handlers remain unchanged. The upper address chrome includes a localized accessible keyboard icon button in focused view only, disabled when interaction is unavailable or a field editor is active.

Local blur resets the receiver to inputmode=none. Layout-effect scope cleanup, disabled authority, hidden document and unmount clear local contents, reset mode and blur the generic receiver. Use the current target/resource, attachment and navigation identity, not frame sequence, so ordinary streaming does not close the keyboard. Do not retain manual activation across navigation/target changes. The normal controller owns held-key/composition cancellation and source fencing. Recognized-field Paste/Edit keep their current explicit editable membership requirements; generic input gains neither.

## Rounded geometry

For native input/textarea only, resolve the four computed horizontal/vertical corner radii, including percentages, and normalize overlapping radii by native box dimensions. Derive inner insets using the ellipse's 45-degree point, scaled to the displayed axis dimensions. The resulting rectangle fits inside every rounded corner. Intersect it with viewport/ancestor clipping, enforce existing minimum dimensions, and check corners, edge midpoints and center against native hit targets. Unknown radius representation fails closed. The local receiver uses the published inner bounds, not the full noninteractive bounding corners. Existing frame/shadow traversal, unsupported transform rules, disabled/readonly checks, limits and stable identity remain unchanged. No site-specific CSS or hostname is part of product code.

## Interfaces, security and operations

No API, wire message, database, versioning, persistent setting or generated client changes. Text uses existing source-fenced direct input, not private field replacement. Values remain outside diagnostics, files and Agent history. Existing read-only, disconnected, stale-image and active-dialog states disable effects. Opening the keyboard itself is a local effect and does not guarantee that a remote field is focused or accepts subsequent input. Unknown effects are not retried.

Ship as one focused PR; no merge, deployment or Runtime restart is authorized. Rollback is the normal code rollback with no data migration. The physical keyboard surface is browser/OS controlled and requires device acceptance distinct from automated component checks. Existing direct multilingual IME limitations remain separate.

## Removal and Replacement

| Existing unit | Authority | Replacement | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Generic receiver always suppresses mobile activation | REQ-1, ADR-D1 | Explicit gesture-only temporary textual activation; default none retained | web focused view/controller | component focus/mode/lifecycle tests |
| Bounding-box corners incorrectly exclude rounded native controls | REQ-4, ADR-D2 | Safe native inner rectangle plus clipping/multipoint hits | Runner region probe | rounded, pill, elliptical, clipped and occluded regressions |

No obsolete protocol, storage, configuration or generated surface is introduced or removed. Earlier field-editor snapshots remain unchanged.

## Test Strategy

E2E-first representative flow: normal authenticated Browser journey clicks a synthetic custom/unrecognized editable, opens the keyboard button, types text and observes a page result through Web/API/Control/Runner without recognized field metadata. Retain native field Edit/Cancel/Apply and original-attribute checks. Fixture images must match submitted content; use current testenv Browser prerequisites without live-site credentials. CI must run the required Web and API lanes, not only Storybook.

Runner real Chromium tests cover 8px rounded input, pill/percentage/elliptical/asymmetric radii, textarea, corners inside published inner bounds, clipping, actual overlay occlusion, disabled/readonly, and retained identity. Do not use third-party CSS/network in committed tests. Web component stories use the real controller to cover no recognized fields, native mode/focus in the gesture, ordinary text dispatch without remote pointer selection, blur/reset, navigation/attachment and authority loss, active editor/read-only/disconnect guards, touch handling and mobile/desktop chrome overflow. Node and existing controller tests retain direct composition/paste and source fencing coverage.

Run Runner Ruff/format/typechecker/full pytest; web formatting/ESLint/typecheck/Node tests/Storybook build and targeted real plays at mobile390x844 and desktop1200x900; E2E Ruff/typecheck, docs catalog and diff checks. Evidence belongs in a supporting verification report and exact-SHA PR/CI record. Physical Safari keyboard and actual site acceptance are reported not run when device prerequisites are absent, never counted as passed by Chromium emulation. No automated challenge solving or live credential entry.

## Authority and feasibility audit

M1 follows explicit manual-button confirmation; M2 retains existing direct focus/stream behavior; M3 follows unchanged input authority/no-replay plus scope cancellation requirements; M4 retains native receiver identity and occlusion rules while correcting its rounded outline. Each REQ has a mechanism, and each mechanism has approved or unchanged authority. No new product behavior, persistent state, input authority or direct IME transport is added.

Repository feasibility: existing generic receiver and ordinary text/composition path support M1-M3 without server changes. The public-CSS synthetic reproduction establishes M4's defect and an isolated real-browser verification lane. Automated implementation verification remains pending. Physical mobile keyboard acceptance is conditional on device/browser policy; this does not require a different implementation authority.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Approved on: 2026-10-16.
- Approved Design revision: `1`.
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`.
- Approved scope: requester explicitly confirmed the disclosed focused-view manual keyboard/current-remote-focus behavior and generic rounded-input correction with retained permission/source/field-editor boundaries, then authorized implementation. This records the confirmed mechanisms, not a claim that the requester separately reviewed this document's exact wording.
- No merge, deployment, Runtime restart, expanded unrecognized-field Edit/Paste or direct IME repair is authorized.
