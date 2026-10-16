---
title: "Browser Manual Keyboard Access Decisions"
created: 2026-10-16
tags: [browser, frontend, runtime, accessibility]
document_role: primary
document_type: adr
snapshot_id: manualkeys-261016
---

# Browser Manual Keyboard Access Decisions

Authority: [manualkeys-261016/REQ](../requirements/manualkeys-261016-browser-keyboard-access.md).

## D1. Explicit local keyboard activation retains existing remote focus

The requester confirmed an upper focused-view keyboard button that opens a local native keyboard and directs ordinary participant input to the remote page's existing focus. Reuse the current generic receiver and direct-input stream. The gesture synchronously enables a textual input mode and focuses the local receiver; it sends no remote pointer, focus-selection, value-read or whole-field replacement operation. Retire manual activation on local blur and scope/authority loss. No persistent preference, separate input protocol, automatic retry or new input authority is introduced.

Rejected: automatically refinding a field, synthesizing recognized editable identity, making unrecognized fields eligible for private Edit/Paste, or treating manual keyboard access as an IME composition repair. These conflict with the confirmed scope rather than forming unresolved options.

Authority: REQ-1, REQ-2, REQ-3; requester confirmation on 2026-10-16 KST; unchanged Session Browser direct-input and permission contract.

## D2. Publish a safe inner rectangle for rounded native controls

The requester confirmed the generic rounded-input correction while retaining actual occlusion and uncertain-geometry exclusions. Derive an inscribed rectangular hit area from native rounded corners, then apply the existing clipping and hit checks to that actual receiver rectangle. Retain document-local identity. Check its corners, edge midpoints and center rather than accepting a center hit alone. The local transparent rectangular receiver must fit inside the native field's rounded outline instead of covering unclickable corner pixels.

Rejected: site-name exceptions, globally dropping corner checks, granting whole-field editing based solely on current focus, or publishing the full bounding rectangle while ignoring its noninteractive rounded pixels. The chosen bounded calculation is local geometry implementation under REQ-4, not an expansion of Browser interaction authority.

Authority: REQ-4 and REQ-3; requester confirmation on 2026-10-16 KST; unchanged source-fenced receiver geometry contract.
