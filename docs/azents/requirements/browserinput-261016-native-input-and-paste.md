---
title: "Browser Native Input and Paste Requirements"
created: 2026-10-16
implemented: 2026-10-16
document_role: primary
document_type: requirements
snapshot_id: browserinput-261016
tags: [browser, frontend, runtime]
---

# Browser Native Input and Paste Requirements

Snapshot: `browserinput-261016`; reference: `browserinput-261016/REQ`.

## Problem and Primary Scenario

A Session user needs to enter a locally copied password into a streamed Browser page. An image-only page does not offer normal local clipboard integration, and unconditional mobile focus can open or dismiss the keyboard at the wrong time.

## Goals and Supporting Effects

Reliable explicit plaintext insertion, stable mobile input focus, and ordinary new-tab selection without changing Browser access or isolation. Native page rendering remains authoritative.

## Non-Goals

Remote-to-local copy, text selection UX, rich clipboard data, ambient clipboard synchronization, clipboard history, a full local DOM layer, and unrelated Browser redesign.

## Requirements

### REQ-1. Explicit paste

Selecting an input and pressing the address-bar paste button inserts locally copied plaintext, including passwords, without an application confirmation dialog. Native keyboard/callout paste also works. The value is not trimmed, transformed, logged, persisted or routed through Agent conversation. A denied/unavailable clipboard, empty/oversized text or changed destination produces content-free feedback and no automatic retry. Browser/OS permission UI remains browser-owned.

### REQ-2. Mobile native focus

Only known current editable regions may request the mobile software keyboard. Repeated input taps and ordinary frame/visual-viewport updates preserve the local receiver instead of cycling blur/focus. Non-input taps do not open the keyboard. Unknown, stale, detached, disabled and read-only regions are not speculative input targets.

### REQ-3. Link-opened tabs

An ordinary unmodified user click opening a new tab selects that tab. Explicit modifier/middle-click background intent, another attachment's actions, Agent actions, reconnects and old notifications do not steal selection.

### REQ-4. Native rendering

Remove credential/password/OTP field masking in live frames and intentional captures. Preserve the website's own password bullets and all unrelated authority, transport and content-safe diagnostic boundaries.

## Fixed Constraints

Preserve opt-in default OFF, exact Session/task/page/incarnation and attachment/source fencing, observation-only restrictions, transient input conflict guards, no replay, bounded transport and existing TLS/network behavior. Use focused contract/component coverage plus the existing representative E2E rather than adding an OS/gesture permutation matrix. No merge, deployment or Runtime restart is authorized.

## Open Assumptions

Physical iPhone testing of the primitive focus strategy is evidence of feasibility, not proof of assembled-product integration. Custom editors that require a native remote paste event are outside ordinary plaintext insertion semantics.

## Confirmation

On 2026-10-16 KST the requester confirmed the three Browser repairs, reviewed a real-component paste prototype, removed its application confirmation popup, and explicitly approved implementation of that flow with copy deferred.
