---
title: "Browser Field Editor Verification Report"
created: 2026-10-16
tags: [browser, frontend, runtime, security, testing]
document_role: supporting
document_type: supporting-verification-report
---

# Browser Field Editor Verification Report

Scope: the one-shot field editor, compact lower actions, address selection and touch-view regression subset of [fieldedit-261016](../requirements/fieldedit-261016-current-input-editing.md). The separate direct multilingual IME repair remains outstanding; the complete snapshot is not marked implemented.

## Implemented boundary

- Native textual input/password/textarea reads occur only after explicit Edit on a selected acknowledged receiver.
- The private Browser stream carries one correlated field value and one single-use replacement/cancellation identity. API, connection and Runner validate their respective authority and correlation boundaries.
- Empty replacement is valid. Original-element/document/focus/writability/value changes fail closed. Unsupported custom/contenteditable editors are not flattened into native fields.
- Private values remain outside ordinary status, frame, projection, logs and Agent history. Security invalidation clears local visual content immediately and retires the attachment/snapshot.
- Apply stays read-only until acknowledgement. A lost response is not retried. Oversized encoded replacement is rejected before send without creating a false unknown outcome.
- Direct Paste remains unchanged; its selected receiver survives lower-toolbar activation. Clipboard reads happen during explicit gestures, with no writes or background access.
- The selected receiver is revealed in local viewing space above the measured lower controls. Subsequent participant scrolling does not trigger repeated auto-reveal.
- The modal has one opaque body-colored background, no shadow seam, enter/exit motion and reduced-motion support. Initial address focus selects all; later caret edits remain native.

## Local verification

| Boundary | Result |
| --- | --- |
| Runtime-control complete pytest suite | 461 passed |
| Runner complete pytest suite | 527 passed |
| Runner field viewer transport tests, included above | 14 passed |
| API Browser socket tests | 35 passed; two existing testcontainers deprecation warnings |
| Web Node suite | 556 passed |
| Web TypeScript, ESLint and Storybook build | passed |
| Changed Python Ruff/format and configured type checkers | passed |
| E2E Python Ruff and type checker | passed |
| Documentation catalog and whitespace checks | passed |

Runner coverage includes real native input/password/textarea, empty text, unchanged-value checks, cancelled beforeinput, one-shot replacement, read-only access and child-frame document replacement without a top-level navigation change. API socket coverage rejects unsolicited, duplicate, wrong-field, wrong-sequence, read-only and revoked private responses.

Real Storybook component probes at 390×844 and 1200×900 passed nine interaction/accessibility stories at each size, with no page errors. These include the production editor lifecycle and the real direct Paste selection controller, not just the older synthetic editor callbacks. A touch probe with a simulated 500-pixel VisualViewport verified the password editor, opaque background through the 844-pixel layout viewport, no overflow/shadow seam, one lower Paste/Edit pair, and restored direct controls after Cancel. Measured enter/exit transition durations were 160/120 milliseconds; reduced motion used zero duration.

All text and passwords used by automated fixtures are synthetic. Viewport simulation is not evidence that a physical software keyboard, IME candidate strip or native clipboard-consent surface behaved correctly.

## Independent review

The implementation owner requested a read-only independent review. Accepted findings were corrected and targeted re-reviewed:

- selected-field reveal was connected to production rather than remaining fixture-only;
- editable membership loss now retires private editing, including child documents;
- lower-toolbar activation preserves the production Paste controller's selection;
- Apply remains open/read-only until acknowledgement;
- status invalidation closes the attachment to dispose Runner-owned private state;
- byte-size preflight rejects unsent oversized replacement safely.

The targeted re-review reported no remaining blocking finding in the corrected scope and independently passed 13 focused Node tests.

## Assembled product and remaining acceptance

The existing authenticated Browser Web E2E now covers actual password read, local Cancel without source change, re-entry with the original value, and Apply through the real Web/API/Control/Runner boundary. It requires the content-matched Web and Runner fixture images. This report does not claim a local assembled-product pass; required CI results must be checked independently for the submitted revision.

Physical iPhone Safari keyboard focus after asynchronous value read, native clipboard permission, Korean/Japanese/Chinese candidate/replacement behavior and actual keyboard-height changes remain unverified. Direct input remains the default, and this modal is not a direct-mode IME fix. No merge, deployment or Runtime restart was performed as part of this verification.
