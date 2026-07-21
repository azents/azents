---
title: "Introduce credential provider model and admin password reset token Historical Requirements Reconstruction"
created: 2026-06-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: credential-260618
historical_reconstruction: true
migration_source: "docs/azents/adr/0066-credential-provider-and-admin-password-reset.md"
---

# Introduce credential provider model and admin password reset token Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `credential-260618`
- Source: `docs/azents/adr/credential-260618-credential-and-admin-password.md`
- Historical source date basis: `2026-06-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[signup-260617/ADR](../adr/signup-260617-signup-token-registration.md) separated new signup authority from email delivery so SMTP/SES is not mandatory prerequisite for open-source/self-host transition. New signup is controlled by signup token, and admin can manually deliver signup link even without SMTP.

However, login and security settings still have SMTP dependency. Current system displays verified email as if it is always usable authentication method, and uses email OTP for login and elevation. In self-host instance without SMTP, email OTP cannot be sent, so verified email alone cannot be actual login credential.

Password management also currently provides only features where logged-in user sets/changes/deletes password while elevated. If user forgot password and SMTP is not configured, there is no self-service recovery path. When SMTP is configured, user can log in by email and change password, so separate forgot-password email flow is not core requirement.

Credentials such as TOTP and passkey may be added later, so implementation strongly tied to password/email should be avoided. Authentication method query, elevation method query, credential deletion invariant, and password reset recovery path are organized around credential provider.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
