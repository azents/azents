---
title: "Current Browser Input Editing Design"
created: 2026-10-16
tags: [browser, frontend, runtime, security]
document_role: primary
document_type: design
snapshot_id: fieldedit-261016
---

# Current Browser Input Editing Design

Authority: [Requirements](../requirements/fieldedit-261016-current-input-editing.md) and [decisions](../adr/fieldedit-261016-current-input-editing.md).

## Current behavior and scope

Current Browser frames expose content-free native editable identities/geometry. The participant stream supports source-fenced pointer, wheel, keyboard, composition, paste, dialog and navigation actions. Actual clipboard Paste already exists. The accepted component prototype still uses synthetic remote values; the production container returns no field-editor controls. No whole-field read/replace result exists yet.

Earlier tab, popup, unmasked-image, native-receiver, zoom and touch repairs are ancestors of this worktree's base. They are regression obligations, not changes to replay from the old worktree. Remote selected-text Copy is explicitly deferred.

## Design Authority

- Design revision: `2`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Compact floating Paste/Edit, single-field full-screen modal and no duplicate upper actions/status banners | REQ-1, REQ-6, ADR-D1 | required |
| M2 | Explicit value read and one confirmed original-field replacement | REQ-2, REQ-3, ADR-D1 | required |
| M3 | Existing Browser direct logical stream and current input authority, no Agent/history path | REQ-5, ADR-D2, current Session Browser flow | existing |
| M4 | One transient attachment/document/element-bound snapshot and atomic unchanged-value check, no retry | REQ-3, REQ-5, ADR-D3, existing no-replay contract | derived |
| M5 | Original supported native input type/editing attributes, password semantics and bounded transient draft | REQ-2, REQ-5, ADR-D5 | required |
| M6 | VisualViewport-following controls, selected-field reveal and keyboard-preserving participant scrolling | REQ-6, existing Browser view/source contract | derived |
| M7 | Explicit real Clipboard API/native paste; native OS consent retained | REQ-4, ADR-D1 | required |
| M8 | Address first-focus selection and editor enter/exit transitions with reduced motion | REQ-7, REQ-10 | required |
| M9 | Preserve earlier tab/input/touch/authority behavior | REQ-9, current Session Browser flow | existing |

REQ-8's direct-mode text replacement lane is not authorized to invent a language-specific or blind-diff mechanism by this table. It remains a distinct feasibility/implementation obligation under ADR-D4; this document must be extended through the same authority process before introducing a material direct-mode text transport.

## Architecture and ownership

The web container owns selected receiver state, pending read/apply state, native draft, current target scope and visual lifecycle. UI components remain prop-driven. `BrowserConnection` owns one pending editor exchange scoped to its concrete socket attachment; raw values are resolved only to the editor controller, not added to general status or durable projection state.

Runtime-control owns strict typed request/reply codecs. Runner's attachment validates fresh participant input authority, acknowledged editable membership, exact target and navigation before any read or mutation. BrowserEditableRegions resolves the same frame/shadow/document-local native element. An opaque JS handle retains the original value and native element in that document; it is never serialized into logs or Agent events.

Read/replace uses the current private Browser stream rather than generated public API routes. API/Runner source ownership and direct relay bounds remain unchanged. No OpenAPI client regeneration or database migration is needed.

## Exchange and lifecycle

Add typed field-open, field-replace and field-cancel actions on the existing sequenced source-fenced input path, plus a typed field-value reply correlated with the originating sequence. Open requires a current acknowledged field and no held input/composition. It returns the attachment-local operation handle, exact editable ID, native kind and unchanged value; an empty value is valid. Only native textual input/textarea is accepted initially; custom/contenteditable targets fail closed rather than being flattened.

A snapshot belongs to one attachment, navigation and exact element. Opening another retires the former. Ordinary direct input, target/document change, disconnect, access loss, cancellation or apply retire relevant snapshots. Apply validates identity, focus, writability, original value and captured native editing configuration in one document turn before the native value setter and input notification. A detached native same-type/configuration control must represent the draft exactly before any original-field event or mutation; repeat validation after beforeinput. A cancelled event, configuration change or unrepresentable draft rejects without overwrite. The snapshot is consumed before the effect; there is no retry.

The private read also returns a bounded closed native-attribute record: supported input type, input mode, autocomplete, effective capitalization/correction, spelling, enter-key hint, min/max length, pattern, required/multiple, name and placeholder. Native IDL getters preserve associated-form inheritance and native defaults without inventing generic-ancestor inheritance. The web maps only these explicit hints to the local input/textarea; it retains independent local identity, explicit focus and transport limits, and copies no page script, arbitrary attribute, form/action, original DOM ID or submission routing. Actual autofill availability remains browser/OS/local-origin controlled, not access to credentials saved for a remote origin. Local explicit Paste uses native insertion and derives state from the actual control, preserving email selection where standard range APIs are unavailable; unsupported native insertion fails without blind append or a hidden differently sanitized draft. Native OS Paste remains available.

The UI distinguishes closed, reading, editing, applying and closing states. Read-only, pending or stale targets provide no effect-bearing action. Closing via Cancel discards the operation without altering the page. Apply closes only when the explicit exchange is confirmed; unknown outcomes stay unknown. No clipboard/value queues are introduced.

Draft display may remain transient only through the requested exit animation; no persistent retention is introduced. Security invalidation clears immediately rather than animating unauthorized content. Clipboard reads begin in the actual click/touch gesture, and delayed results cannot follow a new receiver or scope. No routine clipboard/status banners are added.

## Presentation

Use the approved compact floating pair, current theme tokens, actual native local editor and original full-screen modal. Keep the modal's opaque body-colored background through the layout viewport behind Safari accessories; remove shadow seams. Never style or simulate the native Safari accessory controls. Upper address-bar duplicates disappear once the connected lower actions exist.

VisualViewport resize/scroll bounds the focused viewport and controls. The participant's selected receiver is initially revealed above the measured controls with label context, without shrinking text. User scrolling is not counteracted by repeated auto-reveal. Preserve source coordinate mapping and native receiver identity across frame/viewport updates; do not send a remote scroll merely to reproduce the synthetic fixture behavior.

Use short enter/exit opacity transitions rather than moving the field out from under a trusted focus gesture. Retain content until the exit transition completes, clear on completion, and respect reduced motion. Address selection remains the separately tested first-focus native behavior.

## Security, bounds and failures

- Existing Browser input permission, TLS, owner/resource fencing, no action replay and current-dialog rules remain unchanged.
- Field values and clipboard contents are absent from ordinary frames, logs, exception bodies, telemetry, files and Agent history. Test payloads are fixed synthetic fixtures.
- Preserve existing 32,768-character and whole-message byte bounds without truncation. Oversize reads are rejected before emitting a reply.
- Stale/unsupported/cancelled edit outcomes are typed content-free rejections; no refind, fallback overwrite or automatic retry.
- Native site input handlers may validate/transform a dispatched value as with normal input. Transport dispatch does not prove later site workflow completion.
- No persistent setting, content versioning, synchronization daemon, background clipboard access, or generic remote-to-local Copy capability.

## Removal and Replacement

| Existing unit | Authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Synthetic-only production fieldEditor=null | REQ-2 | real scoped editor controller | product container | connected integration tests |
| Prototype-only local wheel/reveal emulation | REQ-6, current source contract | actual Browser wheel path and local viewing geometry | production wiring | no fake remote value/scroll state |
| Duplicate upper actions in editor experience | REQ-6 | lower floating actions | connected panel | component button counts |
| Zero-duration modal transitions | REQ-10 | enter/exit lifecycle and reduced motion | editor UI | transition/focus/cleanup plays |
| Temporary scope note | project workflow | permanent snapshot/spec and evidence report | final cleanup | temporary file absent before PR |

Existing standalone Paste remains until a connected lower replacement exists. Pure fixtures can retain explicit synthetic behavior for tests but must never be wired into production.

## Test Strategy

E2E primary boundary: real participant attachment opens a fixture native field with an existing value, reads it into the native editor, cancels unchanged, applies replacement to that exact field, rejects independent mutation/navigation/focus/element replacement, and respects read-only permissions. Use the existing Browser core E2E substrate; keep detailed UI permutations in component stories and low-level Runner tests.

Runner tests cover input/textarea/password, empty/unicode/emoji/line-break values, frame/shadow identity, unsupported fields, read-only/disabled/disappeared fields, changed values/focus/document, cancelled page input handlers, one-shot consumption, disconnect and size bounds. Contract tests reject unknown/malformed/missing fields and invalid phase combinations before effects. Typed web tests cover reply correlation, current scope, cancellation, no replay and pending-state cleanup.

Component plays cover initial no-action state, compact lower controls, genuine touch path, clipboard empty/denied/no-op layout, viewport/keyboard-sized geometry, source-field visibility, manual scroll, modal focus/animation/cancel/apply/re-entry, reduced motion and first-focus address selection. Actual iPhone Safari OS keyboard/candidate/clipboard-consent evidence is a separate acceptance boundary and must not be replaced by Chromium emulation claims.

Local checks: runtime-control and Runner Ruff/typechecker/Pytest, web lint/typecheck/tests/build/Storybook, scoped spec review and independent read-only code review. Create a focused PR or reviewable stack only after local verification; monitor all required CI through completion. No merge or deployment without explicit authority. No live credentials are required for the deterministic fixture suite. Optional physical/live tests are reported as not run when prerequisites are absent, not silently counted as passed.

## Feasibility

M1-M9 have local implementation and verification evidence in the [field-editor verification report](browser-field-editor-verification-report-2026-10-16.md): strict contract, real Runner attachment, API authority/correlation, web lifecycle and component interaction checks pass. The representative assembled-product E2E is extended and requires revision-matched CI verification. Physical Safari keyboard/clipboard acceptance and REQ-8 remain conditional on device evidence and a safe generic direct-edit mechanism over pre-existing text/selection. The complete snapshot is not marked implemented while those obligations remain outstanding.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Authorized revision: `2`; exact authority ID set: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M9`. The same-date original-type/attribute instruction extends M5 under REQ-2/ADR-D5 without expanding execution or deployment authority.
- Execution authorization: requester finalized the demonstrated behavior and explicitly requested implementation with earlier outstanding outcomes on 2026-10-16 KST; later the same date added animation.
- Authorized implementation direction: M1-M9, as required/existing/derived mechanisms of that approved behavior and the unchanged Browser security boundary. This records the existing implementation instruction rather than claiming the requester separately reviewed this document's exact wording.
- Any new material direct-mode text transport, expanded custom-editor scope, privacy relaxation, deployment or migration remains outside that authorization and must return to the decision owner.
