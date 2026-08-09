---
title: "Discord Callback SDK Gap Requirements"
created: 2026-08-09
updated: 2026-08-09
implemented: 2026-08-09
tags: [external-channel, discord, sdk, callback, reliability]
document_role: primary
document_type: requirements
snapshot_id: callback-260809
---

# Discord Callback SDK Gap Requirements

- Snapshot: `callback-260809`
- Document reference: `callback-260809/REQ`

## Problem

The adopted `discord.py` public Application edit API accepts an Interaction Endpoint
argument but its HTTP implementation removes that field before issuing the provider
request. Discord connection activation therefore cannot configure the required
callback through the adopted SDK version.

## Primary Actor and Scenario

A Workspace administrator connects a customer-owned Discord App. Azents automatically
configures the per-connection Interaction Endpoint and the connection becomes active
without a manual Discord configuration step.

## Goals

- Preserve automatic Discord callback configuration and current activation outcomes.
- Treat an adopted SDK API that cannot perform the required provider effect as an SDK
  capability gap.
- Keep the exception narrow, reviewable, deterministic, and removable.

## Non-Goals

- Adding a second Discord SDK or an Azents-owned general Discord REST client.
- Retaining both SDK and direct callback mutation paths.
- Changing callback URL construction, credential ownership, or activation semantics.

## Requirements

### REQ-1. Callback configuration remains automatic

Discord Single and Multi App setup and validation must configure the exact current
Interaction Endpoint before reporting the connection active.

### REQ-2. The unusable SDK operation is not treated as supported

An adopted SDK method is not a usable capability when its released implementation
cannot transmit the required provider field. Callback configuration must use one
operation-specific direct transport until the adopted SDK public API can perform the
effect correctly.

### REQ-3. The gap remains closed and removable

The transport must expose only callback configuration, issue one fixed provider route,
preserve established safe error classification, and be removed rather than retained as
a fallback once an adopted `discord.py` release performs the operation correctly.

### REQ-4. Verification remains deterministic

Unit and deterministic E2E tests must prove the callback request, sanitized fixture
evidence, successful activation, and the absence of private SDK APIs or generic
provider request surfaces.

## Fixed Constraints

- Continue using the adopted `discord.py` SDK for Application metadata, Bot identity,
  command reconciliation, history, delivery, and Gateway operations it can perform.
- Do not use private `discord.py` APIs or mutate credentials globally.
- Preserve the established commit-before-provider-I/O and activation failure mapping.

## Confirmation

Confirmed by the requester on 2026-08-09: an SDK API with this implementation defect is
not SDK-supported for the required operation.
