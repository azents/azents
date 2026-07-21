---
title: "New signup is controlled by email-bound signup token redeem Historical Requirements Reconstruction"
created: 2026-06-17
implemented: 2026-06-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: signup-260617
historical_reconstruction: true
migration_source: "docs/azents/adr/0065-signup-token-registration.md"
---

# New signup is controlled by email-bound signup token redeem Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `signup-260617`
- Source: `docs/azents/adr/signup-260617-signup-token-registration.md`
- Historical source date basis: `2026-06-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Current Azents authentication model uses email OTP verification as single entry point for both login and signup. `/auth/v1/email/send-code` sends OTP, and when `/auth/v1/email/verify` succeeds, existing user logs in while new email automatically creates `User` and primary `UserEmail`.

This makes email login easy to provide as first-class feature, but creates two problems for open-source transition and self-host support.

- We do not want email delivery infrastructure such as SMTP/SES to become mandatory prerequisite for self-host installation.
- If hosted server has public signup open, it becomes attack surface for account creation spam, email sending cost, and compute/LLM resource abuse.

Therefore new account creation authority must be separated from email delivery itself and controlled by signup authority explicitly issued by operator.

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
