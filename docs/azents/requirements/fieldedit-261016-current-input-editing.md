---
title: "Current Browser Input Editing Requirements"
created: 2026-10-16
tags: [browser, frontend, runtime, security]
document_role: primary
document_type: requirements
snapshot_id: fieldedit-261016
---

# Current Browser Input Editing Requirements

- Snapshot: `fieldedit-261016`
- Document reference: `fieldedit-261016/REQ`

## Problem

Direct remote input does not reliably provide native mobile text editing, especially for composition-based languages and editing existing values. Users need an explicit alternative for one selected field without changing the default interaction mode.

## Primary Context

### Primary Actor

A Session participant authorized to interact with its Browser.

### Primary Scenario

The participant directly types in a current Browser input by default. A compact toolbar above the keyboard offers Paste and Open editor actions. Open editor loads the current field's full value in the previous full-screen native input modal; the participant edits locally and either cancels without changing the source or confirms replacement of that exact input.

## Supporting Scenarios or Effects

- Edit an existing multiline value with native text selection and composition.
- Edit a password using native password masking without altering the underlying characters.
- Paste actual device clipboard text through an explicit gesture or native paste menu.

## Goals

- Preserve direct input as the default.
- Make one-field editing usable on mobile and desktop.
- Access the actual selected value and actual device clipboard rather than simulated values in the connected experience.

## Non-Goals

- A persistent modal input mode or automatic opening on focus.
- A generic clipboard synchronization service, rich clipboard transfer, or the explicitly deferred remote-text-block Copy feature.
- Solving direct-mode IME behavior through this editor.
- Changing unrelated Browser layout, navigation, or authority policy.

## Requirements

### REQ-1. Explicit one-shot editing

**Acceptance criteria**

- An explicit control edits only the currently selected input.
- Selecting an input alone does not open the editor.
- Confirming or cancelling does not change later fields into a modal mode.

### REQ-2. Read the actual selected value

**Acceptance criteria**

- Opening the editor loads the selected field's existing complete value rather than an empty or example value.
- Text, multiline, and password editing retain their native editing semantics.
- The modal matches the original supported input type and native editing attributes. An email input uses the email keyboard and the original autocomplete hints; password, URL, telephone, search and multiline inputs retain their corresponding native behavior.
- Preserve applicable input-mode, capitalization/correction, spelling, enter-key, length, pattern and multiple-value hints without copying page scripts or submission behavior. Native browser/OS suggestions remain under browser/OS control rather than being simulated.
- Unsupported or unavailable targets are reported without silently editing a different target.

### REQ-3. Cancel or replace

**Acceptance criteria**

- Local edits do not change the source before confirmation.
- Cancel discards the draft and leaves the original field unchanged.
- Confirm replaces only the original field's full value with the unchanged draft characters, including an intentionally empty value.
- A changed, unavailable, or unauthorized source is not overwritten. Failure is visible and is not automatically retried.

### REQ-4. Real device clipboard

**Acceptance criteria**

- Explicit paste and native paste use actual device plain text with native browser/OS consent.
- Native browser/OS paste consent and the input's native Paste action remain available. Do not fabricate a successful insertion when clipboard access is denied or unavailable.
- No clipboard write, continuous read, or background clipboard synchronization is introduced.

### REQ-5. Transient private values

**Acceptance criteria**

- Values and drafts are not logged, persisted, sent to Agent history, or attached to generic diagnostics.
- Password characters remain intact and masked in the editor.
- Cancel, completion, target/document change, disconnection, or access loss discards the draft.
- Read-only participants cannot request values through this editing interaction or replace fields.

### REQ-6. Reviewable responsive experience

**Acceptance criteria**

- Present the real component's clickable prototype before finalizing the production experience.
- Verify disabled, open, cancel, confirm, password, multiline, focus, and one-shot states at mobile and desktop sizes.
- During direct input, keep the source page visible and put only Paste and Open editor actions immediately above the keyboard. This toolbar contains no additional input field.
- Keep full-value editing in the full-screen modal, not in a bottom input panel. Its opaque background continues below the visible content through the keyboard/accessory-covered layout area, instead of showing a gray dimming backdrop there.
- In the field-editing experience, expose Paste and Edit only in the bottom action controls, removing duplicate address-bar actions.
- Reposition the toolbar when the visible area changes without requiring a fixed keyboard height. Toolbar taps preserve input focus.
- Use the approved compact floating Paste/Edit buttons despite Safari's native accessory gap; do not claim control of native browser chrome. The earlier toolbar comparison is review evidence, not an additional production mode.
- Keep the selected input, including a lower password field, visible above the software keyboard and action controls, with enough nearby context to identify it. Both visual alternatives must satisfy this before comparison.
- Allow touch page scrolling while the keyboard is open without losing input focus. Automatic input visibility adjustment must not undo the participant's subsequent manual scroll.
- Paste and Open editor must activate through actual touch gestures, not only mouse clicks.
- Keep floating buttons compact and shorten the action label to Edit. Remove added status banners for clipboard checks, empty values, completion and cancellation; do not duplicate status text above the page and controls.
- Clearly distinguish actual clipboard access, simulated page state, connected remote reads, and verified production behavior.

### REQ-7. Immediate address editing

**Acceptance criteria**

- Initial address focus or re-entry selects the full address for immediate deletion/copying.
- Subsequent native caret/range edits remain intact while focus is retained.
- Preserve URL keyboard, validation and navigation behavior.

### REQ-8. Language-independent direct text input repair

**Acceptance criteria**

- Investigate and repair the reported Korean compatibility-jamo input without adding a Korean-specific text composer.
- Preserve native local composition/replacement semantics for Korean, Japanese, Chinese, Latin, emoji and deletion, without blindly overwriting an existing remote value or caret context.
- Distinguish synthetic event regressions from verified physical-iPhone acceptance. Do not claim an unobserved device result.
- Keep direct input as the default and keep its text transport separate from explicit whole-field modal replacement.

### REQ-9. Preserve earlier Browser fixes

**Acceptance criteria**

- Regress earlier native input focus, source-fenced link/item taps, local pinch zoom, preview-to-focus activation, recent/first live tab selection, tab creation/closure and initiating-tab popup selection behavior.
- Preserve unmasked Browser imagery and input without adding Azents masking/rewrite logic; native password input semantics remain unchanged.
- Retain touch feedback with its exact-location center dot, edge-to-edge focused viewing and expanding address entry.

### REQ-10. Editor transitions

**Acceptance criteria**

- Animate the editor opening and closing without breaking trusted input focus, draft cancellation, or the continuous modal background.
- Respect reduced-motion settings.

## Fixed Constraints

- Existing Browser opt-in, transport security, target/attachment/document authority, and no-input-replay constraints remain effective.
- No merge, deployment, or Runtime restart is authorized by this snapshot.

## Open Assumptions

- Initial connected editing covers native textual input and textarea; uncertain custom editors must not be silently treated as equivalent native fields.
- Physical-iPhone acceptance requires requester/device participation; local browser automation alone is not that evidence.

## Confirmation

The requester specified the one-shot workflow and real value/clipboard access, then explicitly confirmed the final compact-floating-controls/full-screen-modal prototype and requested implementation of it and the earlier outstanding requirements on 2026-10-16 KST. The same date's follow-ups add editor opening/closing animation and explicitly require the modal's input type and native attributes to match the original, including email keyboard and autocomplete behavior. The explicit implementation request is execution authority for these confirmed outcomes; it does not authorize merge, deployment, unrelated product changes or weakening existing Browser privacy/authority boundaries.
