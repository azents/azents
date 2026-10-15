---
title: "Browser Native Input and Paste Decisions"
created: 2026-10-16
document_role: primary
document_type: adr
snapshot_id: browserinput-261016
tags: [browser, frontend, runtime, architecture]
---

# Browser Native Input and Paste Decisions

Authority: [browserinput-261016/REQ](../requirements/browserinput-261016-native-input-and-paste.md).

The approved research/prototype and current Browser authority determine the outcomes below. No new persistent state, service, public endpoint, runtime mode or compatibility fallback is introduced.

## D1. Explicit plaintext insertion on the existing direct stream

For REQ-1 and the unchanged Browser source contract, native local `paste` reads only event-authorized `text/plain`; the toolbar initiates `navigator.clipboard.readText()` directly in the click. Both submit a bounded typed paste input through the existing authenticated Browser stream. Include a document-local editable identifier to reject a changed destination, and use native `keyboard.insert_text` only after current focus validation. No copy operation or remote clipboard permission is needed.

Forwarding only Ctrl/Cmd+V would address the wrong machine's clipboard. Agent tools would retain input in conversation. Ambient synchronization conflicts with explicit intent. A second clipboard service or persistence has no requirement authority. These are not viable alternatives within the confirmed constraints.

## D2. Content-free native editable geometry

For REQ-2, use the physically validated directly touched local receiver pattern over content-free native geometry, including bounded open-shadow/frame traversal. Stable document-local IDs retain receiver identity across frames. Uncertain occluded/transformed/dynamic geometry is omitted, while image streaming continues. A full DOM/text overlay and unconditional focus are outside the approved scope.

## Fixed removals and retained boundaries

REQ-3 requires popup preference only for its initiating plain-click attachment; background intent and explicit user tab choice remain authoritative. REQ-4 requires deleting mask selectors/options and obsolete masking tests, with no replacement masking. Existing Browser admission, opt-in, source/sequence validation and transient interaction guards remain authoritative throughout. These are fixed outcomes, not new discretionary decisions.

## Risks

Safari may show its own clipboard consent UI; applications cannot remove it. Native insertion emits input rather than a remote clipboard paste event. Geometry is intentionally incomplete for custom/canvas editors and uncertain transforms. Device-level keyboard/callout behavior still requires physical product verification.
