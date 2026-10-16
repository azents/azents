---
title: "Browser Manual Keyboard and Rounded Input Verification"
created: 2026-10-16
tags: [browser, frontend, runtime, testing, accessibility]
document_role: supporting
document_type: supporting-verification-report
---

# Browser Manual Keyboard and Rounded Input Verification

Scope: [manualkeys-261016](../requirements/manualkeys-261016-browser-keyboard-access.md), explicit manual keyboard activation and generic rounded native input recognition. This does not implement or establish direct multilingual IME repair.

## Root-cause evidence

A native input using the public login stylesheet's 8px rounded corners had a 300-by-48-pixel bounding rectangle. The original Runner sampled points one pixel inside each bounding corner plus center. All four corner hit tests returned background and center returned the native input, so the original probe emitted no receiver. Changing only border-radius to zero made all five tests hit the input and emitted one receiver. This was reproduced with the production `BrowserEditableRegions` and real Chromium on synthetic markup; no authentication, challenge answers, real input values or submissions were used.

The corrected production probe emits one receiver for both shapes. Its rounded shape is an inscribed native rectangle, then clipped and tested at corners, edge midpoints and center. No site-name exceptions, arbitrary center-only eligibility, changed native IDs or relaxed field replacement fences are introduced. Automated tests use self-contained CSS rather than a live-site/network dependency.

A read-only Session DOM observation showed that the reported kind of target was a main-document native text input rather than an iframe custom editor. The Session observation surface did not expose private live editable telemetry or computed styles; the synthetic reproduction is not claimed as post-fix live-site acceptance.

## Implemented behavior and boundaries

- A focused-view Show keyboard icon is independent of recognized native receivers. It synchronously activates the generic local textarea with textual input mode in the trusted click/touch gesture.
- The generic receiver has its own stable reference, independent of the interaction controller's currently focused native overlay. The keyboard action sends no remote click, refind, value read or full-field replacement.
- Ordinary direct input continues to the existing remote focus with existing source/attachment/navigation/permission checks. Unrecognized destinations gain no private Edit/Paste eligibility.
- Blur, scope changes, hidden document, disconnect, access loss and unmount clear/reset the generic local receiver. Ordinary frame-sequence changes do not reset it.
- Existing automatic native input, one-shot editing, native hints, address selection, direct Paste and no-retry behavior remain intact. No API/wire/schema/dependency/persistence changes are introduced.

## Local verification

| Boundary | Result |
| --- | --- |
| Runner full pytest suite | 569 passed |
| New rounded geometry suite, included above | 12 passed |
| Native field editor and new geometry focused suites | 50 passed |
| Runner Ruff, formatting and configured type checker | passed |
| Web Node suite | 563 passed |
| Web TypeScript, ESLint and Storybook build | passed |
| E2E Browser test Ruff, formatting and configured type checker | passed |
| Documentation catalog and whitespace checks | passed |

Geometry tests cover 8px corners, pill radii, percentages, elliptical/asymmetric/overlapping radii, textarea, an interior hit grid, stable editable identity and exact private replacement, center/edge/full overlays, clipping and readonly/disabled eligibility.

Ten real component stories passed at each viewport size (20 interaction/accessibility passes, no page errors), followed by a successful trusted touch activation probe. The final rebuilt first-open Tab regression passed in both sizes. Real component tests cover independent activation with zero recognized native fields, actual native focus/inputmode, normal text dispatch without a remote pointer/paste operation, blur reset, streaming continuity, target/navigation/attachment reset, readonly/disconnect/dialog/stale-source guards and switching from a selected native receiver to the separate generic receiver. Prior native receiver, Paste, address selection and field editor plays remain regression obligations. Mobile and desktop rendering use actual product components/providers/fonts at 390x844 and 1200x900, scale 1 and light mode. Touch activation uses the actual non-passive toolbar touch controller. These are component renders, not an assembled-product or physical keyboard result.

## Independent review

A read-only independent reviewer reproduced a first-open Send Tab regression caused by separating the stable generic receiver reference from the currently focused interaction reference. Both Send Tab menu handlers now restore focus through the stable generic receiver, retaining the existing reference fallback and default inputmode=none. A component regression checks Send Tab and Send Shift+Tab before any receiver has been selected. Targeted source re-review confirmed the correction and reported no additional blocking finding in manual activation, lifecycle/authority, recognized-only actions, rounded geometry or E2E changes. The reviewer independently passed all 12 rounded-geometry tests. The implementation owner rebuilt Storybook and passed the corrected first-open Tab regression in both viewport sizes as part of the final 20 component interaction/accessibility passes.

## Assembled-product evidence and remaining acceptance

The existing authenticated Browser Web E2E is extended with a rounded password field and an intentionally unrecognized native field. After a participant tap establishes the remote field focus, Show keyboard must activate the generic local receiver and ordinary typing must produce the expected remote page result through Web/API/Control/Runner. The expected password read/Cancel/Apply, original email attributes, navigation and reconnect checks remain. CI must use submitted-content-matched Web and Runner images.

Exact submitted-SHA CI and final review evidence are recorded in the PR after completion. No local assembled-product pass is claimed. Physical iPhone Safari software-keyboard appearance, actual site behavior, native consent/autofill and direct multilingual IME acceptance remain unverified by these checks. No merge, deployment or Runtime restart is performed by this verification.
