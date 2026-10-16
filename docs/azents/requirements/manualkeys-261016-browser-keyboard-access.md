---
title: "Browser Manual Keyboard Access Requirements"
created: 2026-10-16
tags: [browser, frontend, runtime, accessibility]
document_role: primary
document_type: requirements
snapshot_id: manualkeys-261016
---

# Browser Manual Keyboard Access Requirements

- Snapshot: `manualkeys-261016`
- Document reference: `manualkeys-261016/REQ`

## Problem

A participant cannot summon a mobile software keyboard when a remote page's input is not recognized by the Browser's native editable detection. A generic explicit keyboard action is needed independently of automatic detection. Investigation also reproduced rejection of ordinary rounded native inputs by the current rectangular corner hit tests.

## Primary Context

### Primary Actor

A participant with current Browser input permission using a mobile browser.

### Primary Scenario

The participant taps the intended destination on the remote page. If automatic native-input activation does not expose the keyboard, the participant explicitly opens it through a Browser action and types into the remote page's existing focus without automatically replacing an entire field or changing its focus.

## Supporting Scenarios or Effects

- Normally recognized native inputs retain automatic keyboard activation and one-shot Edit.
- A rounded native input should not lose automatic recognition solely because its rounded corners do not occupy the bounding rectangle's extreme corners (proposed additive correction).

## Goals

- Explicit keyboard access independent of recognized native editable regions.
- Preserve existing Browser interaction, permission, privacy and stale-target safeguards.

## Non-Goals

- Solving or submitting any website's security challenge.
- Finding or choosing a different remote field automatically.
- Whole-field Edit for unrecognized/custom editors.
- Claiming that manual keyboard access fixes direct multilingual IME semantics.
- Persistent keyboard preferences, clipboard synchronization, deployment or merge.

## Requirements

### REQ-1. Explicit keyboard activation

**Acceptance criteria**

- In the focused Browser view, an input-authorized participant can explicitly open the native local software keyboard even when no remote native editable is recognized.
- Activation is available through a discoverable keyboard button and does not require a recognized-field Paste/Edit toolbar to already be visible.
- Existing automatic keyboard activation remains the default.

### REQ-2. Existing remote focus and direct-input behavior

**Acceptance criteria**

- The action itself does not click, refind, or move focus to a remote field.
- Subsequent participant text/key input goes to the existing remote focus through the ordinary direct-input behavior.
- No automatic whole-field read/replacement or inferred field identity is introduced.
- Recognized-field-only Paste/Edit retain their existing identity and eligibility rules.

### REQ-3. Permission and lifecycle boundaries

**Acceptance criteria**

- Read-only, disconnected, stale-target and active-dialog states cannot gain input authority through the keyboard action.
- Target/document/attachment changes and loss of authority discard pending local input and do not carry the previous manual activation into a new scope.
- No typed values, credentials or clipboard contents are added to diagnostics or conversation history.
- Existing navigation, zoom, pointer, address editing and one-shot editor behavior remain intact.

### REQ-4. Rounded-input recognition

**Acceptance criteria**

- An otherwise eligible visible native input is not rejected solely because rounded corners are outside its rectangular bounds' corner hit samples.
- Actual occlusion, disabled/read-only state and uncertain geometry remain excluded; the correction is generic rather than site-specific.
- Preserve exact recognized-field identity, stale-source and replacement safety.

## Fixed Constraints

- Existing Browser authority and no-replay constraints remain effective.
- No merge, deployment or Runtime restart is authorized by this snapshot.

## Open Assumptions

- Mobile keyboard availability ultimately remains controlled by the local browser and OS. Desktop automation cannot prove physical-iPhone behavior.
- A current-page DOM observation confirms a real native text input; the matching public stylesheet reproduces its rounded-input failure. Live internal editable telemetry/computed style is not exposed by the Session Browser observation tools, so the isolated reproduction is not a post-fix live-site acceptance result.

## Confirmation

The requester asked for an explicit keyboard button when automatic input detection fails and separately requested investigation of the currently open page on 2026-10-16 KST. After the existing generic receiver, native-input DOM observation and rounded-corner reproduction were explained, the requester explicitly confirmed the complete REQ-1 through REQ-4 scope: manual keyboard access to existing remote focus plus the generic rounded-input correction, retaining existing permission, source and field-editing boundaries. This is implementation authority, not merge or deployment authority.
