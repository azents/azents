---
title: "Google Tool Group Consent Decisions"
created: 2026-10-22
document_role: primary
document_type: adr
snapshot_id: googletools-261022
tags: [google, toolkit, oauth, security]
---

# Google Tool Group Consent Decisions

Authority: [Requirements](../requirements/googletools-261022-tool-group-consent.md).
The requester instructed implementation and PR delivery on 2026-10-22 after the
workflow and selected-group execution-ceiling recommendation were presented, and
explicitly excluded existing notification controls. This record scopes that
instruction; it does not authorize operational OAuth or deployment changes.

## D1. Selected capabilities and actual grants jointly admit operations

- Authority: `googletools-261022/REQ-1`, `REQ-3`, `REQ-4`.
- Decision: use one saved selected-group set and the existing compiled operation
  policy. Model exposure and every current-authority invocation check intersect
  selected group operations, enabled services and actual Google grants. Presets
  only edit selection; a preset identifier is not an additional runtime authority.
- Rejected: using group selection only to construct OAuth scopes, which would
  expose unselected operations when broad scopes are returned.
- Internal argument-dependent prerequisites remain policy checked and do not
  become separately exposed model tools.

## D2. Curated tool groups request supported sufficient scopes

- Authority: `googletools-261022/REQ-1`, `REQ-2`, `REQ-3`.
- Decision: maintain a bounded backend group catalog over the existing operation
  catalog, including explicit sufficient request scopes. Validate coverage and
  sufficiency against existing method policies. The Web consumes token-free
  catalog metadata rather than accepting arbitrary scope strings as group intent.
- Presets provide read-only, everyday assistance, full capability and clear
  selections, with all resulting choices visible and editable. New connections
  start without a hidden full-access preset. Group labels describe capabilities
  and risky effects such as sending, file sharing and ownership transfer.
- Rejected: requesting every supported service scope, or treating preset labels as
  permission evidence. Google's consent surface is not guaranteed to be granular.

## D3. Preserve existing saved authorization through data conversion

- Authority: existing connection preservation and ownership constraints.
- Decision: backfill existing Google configurations to explicit selected groups
  covering their previously permitted operation set. Preserve identity, token and
  actual-grant records unchanged. Convert stored reviewed intent and final settings
  consistently so an upgrade does not manufacture broader reviewed authorization.
- New persisted configuration is explicit; do not introduce a permanent legacy
  missing-field runtime fallback or silently reconnect existing accounts.
- Conversion must fail closed with nonsecret diagnostics on ambiguous persisted
  input and commit atomically under the existing migration transaction.

## D4. Calendar guest controls remain a focused independent change

- Authority: `googletools-261022/REQ-5`.
- Decision: expose Google's three guest privilege booleans on event create/patch
  and provider result projection. Nullable create fields preserve provider defaults;
  omitted patch fields preserve current privileges. Existing notification settings
  and organizer/resource restrictions are unchanged.
- Delivery: independent small PR; it does not depend on group-configuration changes.
