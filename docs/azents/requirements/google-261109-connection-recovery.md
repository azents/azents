---
title: "Google Connection and Recovery Requirements"
created: 2026-11-09
implemented: 2026-11-09
document_role: primary
document_type: requirements
snapshot_id: google-261109
tags: [google, frontend, toolkit, security]
---

# Google Connection and Recovery Requirements

- Snapshot: `google-261109`
- Document reference: `google-261109/REQ`

## Problem and Primary Context

A connection manager recovering Google access must currently find a deeply nested
reauthorization action, inspect a repeated connection review, publish replacement
credentials, and encounter another settings save. Google is absent from the
standard direct Toolkit reauthorization affordance. Nested generic setup guidance
makes both creation and editing unnecessarily long.

Primary actor: an authorized manager of a shared, Agent-owned, or personal Google
connection. Primary scenario: recover an existing Google connection from the tool
that needs authorization and return to the original place with a truthful result.
Supporting scenarios: first connection, editing service/tool-group selections,
metadata edits, different-account consent, partial consent, cancellation and
uncertain publication.

## Goals and Non-Goals

Make recovery discoverable and complete normal consent without redundant saves.
Keep explicit tool selection, owner permissions, exact attempt fences, renewal
requirements, actual-grant evidence and no-replay guarantees. Do not redesign
other providers, widen grants, alter Google operator configuration, or automatically
re-execute tool effects. No infrastructure changes or deployment are included.

## Requirements

### REQ-1. Discoverable recovery

Google participates in the standard authorized Toolkit recovery action. An
unready Agent tool exposes direct reauthentication rather than an edit detour.
Details and the editor expose recovery beside the account without scrolling.
Existing ownership and manager permission boundaries remain unchanged.

### REQ-2. One normal completion

After explicit connection/recovery initiation and Google consent, a verified
same-account result with the requested usable capabilities completes without an
additional review, replacement-save, or generic settings-save button. Return to
the initiating context and update its visible status. Creation likewise completes
after usable consent without a mandatory separate metadata stage.

### REQ-3. Compact creation and editing

Show account/state and service/group summaries as the primary editor surface.
Keep permission presets directly visible within each Calendar, Drive and Gmail
service section. A preset changes only that service's selection. Individual
group and exact-operation customization use service-specific disclosures.
Advanced metadata, timeout and help are collapsed.
Remove the nested generic three-stage setup and repeated review summary for
Google. Keep the apply action reachable when disclosures scroll; preserve mobile
and keyboard operation. Start new connections with no services/groups selected.

### REQ-4. A single settings action

Apply non-consent settings once. If additional authorization is needed, the same
apply intent continues through consent and completes without another save.
Reauthentication alone must not publish unrelated metadata drafts. Preserve
unapplied drafts across authentication navigation; prompt before discarding them.
No-op apply is disabled. Retain Drive Picker and explicit local disconnect.

### REQ-5. One clear reauthentication action

Authentication controls expose one prominent Reauthenticate button rather than
separate account-change or partial-permission acceptance actions. Unexpected
accounts, missing capabilities and unusable grants explain the problem and allow
reauthentication or cancellation while retaining the existing connection. No
partial result or unexpected identity is published from these exceptional states.

### REQ-6. Honest failure and recovery

Cancellation/failure preserve the current local connection and unapplied draft.
Publication/exchange uncertainty uses exact outcome/review observation, not blind
replay or manufactured success. Duplicate inputs, expired/foreign attempts,
changed owner authority and stale completions cannot mutate another connection.
Restoring credentials does not replay mail, calendar or file effects.

## Fixed Constraints and Assumptions

All supported locales stay structurally aligned and naturally localized. Reuse
the existing Google/Toolkit authority lifecycle; local UI state is never grant
authority. Existing backend publication checks remain authoritative. Current iOS
contracts are preserved; this change targets Main Web management surfaces.

## Confirmation

The requester explicitly approved the presented complete proposal and requested
implementation and a PR on 2026-11-09. This document records that approved scope;
there is no new product decision or separate approval wait for the same intent.
The requester subsequently required a single proper Reauthenticate button,
removed partial-result acceptance and separate account-change choices, and
required presets to be directly visible on the default surface.
The requester further clarified that every service needs its own preset controls.
