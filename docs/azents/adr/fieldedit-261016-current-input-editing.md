---
title: "Current Browser Input Editing Decisions"
created: 2026-10-16
tags: [browser, frontend, runtime, security]
document_role: primary
document_type: adr
snapshot_id: fieldedit-261016
---

# Current Browser Input Editing Decisions

Requirements authority: [fieldedit-261016/REQ](../requirements/fieldedit-261016-current-input-editing.md).

## D1. Explicit one-shot full-field editing

The requester selected one-shot editing of the currently selected field, then finalized the compact floating Paste/Edit controls and full-screen modal and requested implementation. Preserve direct input as the default. Read the actual value on Edit, keep local edits local, and replace the whole original field only on Apply. Cancel leaves it unchanged. Preserve native password masking without introducing an Azents value-masking transform.

Rejected: automatic opening on every focus, a persistent modal mode, the assistant's bottom-input-panel interpretation, duplicate upper actions, routine status banners, and continuing to ship synthetic values as the connected experience. Native Safari clipboard consent is not application UI and cannot be removed by this decision.

Authority: REQ-1 through REQ-6; requester finalization and implementation instruction on 2026-10-16 KST.

## D2. Preserve existing private Browser transport and authority

The connected editor extends the existing typed direct Browser logical stream. It does not use Agent tools, conversation events, durable API records or a new endpoint. Field values appear only in an explicit editor read response to the authorized attachment; they are absent from ordinary frames/status and generic logs. Reads require the same mutation authority as other participant input. Existing opt-in, target, attachment, navigation, generation and source fences remain effective.

This retains the established Browser ownership boundary rather than creating a new authority. A separate Agent or durable HTTP value service conflicts with the existing privacy and no-history outcome and is excluded. No database migration, setting, persistent mode, wire-version negotiation or fallback is introduced.

Authority: REQ-2, REQ-4, REQ-5; existing [Session Browser flow](../spec/flow/session-browser.md).

## D3. Compare original identity and value before one replacement

A read establishes one transient exact-element snapshot owned by its attachment and document. Apply consumes that snapshot once and verifies that the same native field remains current, writable, focused and unchanged. Perform the comparison and value mutation in one native document execution turn, with normal input notification for page frameworks. Reject changed/removed/replaced targets or cancelled page events. Do not retry replacement or treat an uncertain dispatch as confirmed success.

An opaque transient edit handle avoids echoing the original password/value in a second request. It is an operation identity, not persisted content versioning. Replace/cancel/navigation/disconnect/access loss retire the edit state. Open snapshots are bounded to one per attachment; client drafts remain bounded by existing text/message limits.

Rejected: blind full-value overwrite, refinding a field by label/coordinates after context change, sending password contents in Agent events, and automatic replacement retries.

Authority: REQ-3, REQ-5 and the existing source-fenced no-input-replay contract. This concretizes the already requested original-target/unchanged-value outcome.

## D4. Keep direct-mode IME repair independent

Explicit whole-field editing is not evidence that direct-mode IME is fixed. Native input owns language composition; no Hangul/kana/pinyin reconstruction is authorized. Direct editing must preserve existing remote value/selection context before a local replacement can be mapped safely. Detailed direct-mode replacement semantics require repository feasibility evidence and must not be inferred from empty synthetic fields alone. REQ-8 remains separately tracked until that evidence and implementation pass.

Authority: REQ-8, REQ-9 and the requester's explicit objection to fragile local-buffer diffing over pre-existing remote text.

## D5. Preserve original native editing hints

The requester explicitly requires original input types and attributes in the modal, including email keyboard and autocomplete. Transfer bounded native editing metadata only through the already explicit private field read. The modal uses the supported original input type, input mode, autocomplete, capitalization/correction, spelling, enter-key, length, pattern, required/multiple, name and placeholder hints. These are local native-control semantics, not page execution or submission authority.

Reject the former hardcoded generic text/autocomplete-off behavior. Do not spread arbitrary page attributes, event handlers, form association/actions, styles or original DOM IDs into the local application. Browser/OS suggestions and saved credentials remain governed by the local application origin and native policy; no remote-origin credential extraction or simulated suggestion popup is introduced.

Authority: the requester's additive original-type/attribute instruction on 2026-10-16 KST, captured by REQ-2, and the unchanged privacy/authority constraints in REQ-5 and ADR-D2.
