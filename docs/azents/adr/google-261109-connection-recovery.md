---
title: "Google Connection Recovery Decisions"
created: 2026-11-09
document_role: primary
document_type: adr
snapshot_id: google-261109
tags: [google, frontend, security]
---

# Google Connection Recovery Decisions

Requirements: [google-261109/REQ](../requirements/google-261109-connection-recovery.md).
Requester approved the compact connection/recovery proposal and its normal
automatic-completion/exceptional-confirmation split before implementation.

## D1. Reuse staged publication, automate only the normal user decision

Authority: google-261109/REQ-2, REQ-5, REQ-6 and existing Google exact-attempt
publication. Keep server review, renewable-grant checks and atomic confirmation.
The web controller automatically confirms a normal verified result. Unknown grants,
missing capabilities and identity changes remain explicit exceptional states.
Do not make callback arrival itself success. Reject direct credential replacement
or automatically accepting a changed identity: both remove current safety checks.

## D2. Preserve the difference between recovery and applying a settings draft

Authority: google-261109/REQ-4 and existing metadata/grant separation. An explicit
apply intent may include metadata in the same revision-fenced local settings save
or reconnect publication. Recovery omits metadata. This avoids a second write and
partial publication while preserving unrelated drafts. Reuse the existing server
transaction and owner checks; no new persistence store or background workflow.
Persist only bounded token-free editor intent in tab-scoped browser draft state;
it is restored only for the exact owner/target/attempt and never grants authority.
Reject sequential independent metadata/service writes as the normal apply path:
a partial failure would reintroduce duplicate saves and ambiguous completion.

## D3. Standard recovery is a provider action, not a generic OAuth endpoint

Authority: google-261109/REQ-1, REQ-6. Add Google to the existing standard recovery
affordance, dispatch to its existing provider flow, and preserve shared/Agent/user
manager checks. Do not send Google through the generic MCP OAuth endpoint or grant
shared management to an Agent-only administrator. Return context is validated
navigation only, not authorization. No new client modes, schema versions,
credential fallback, migration, or infrastructure are introduced.

## D4. A single reauthentication action and visible permission presets

Authority: requester correction on 2026-11-09, REQ-3 and revised REQ-5.
Supersedes the exceptional-confirmation choice in D1 for Main Web: a partial,
unusable or unexpected-account result retains the existing connection and offers
Reauthenticate or cancellation. Normal complete same-account consent still
auto-confirms. Remove separate account-change initiation and partial-result
publication from Web; existing server publication contracts remain available to
other clients. Show permission presets without a disclosure. Hiding a shortcut
behind detailed tool configuration increased rather than reduced decision cost.

## D5. Scope visible presets to each service

Authority: requester clarification on 2026-11-09 and REQ-3. Put the preset buttons
inside Calendar, Drive and Gmail separately, applying only to that service.
Retain other services' explicit selections when choosing or clearing one preset.
This replaces the visually ambiguous shared preset row following Gmail.
