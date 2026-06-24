---
title: "ADR-0065: New signup is controlled by email-bound signup token redeem"
created: 2026-06-17
tags: [architecture, backend, api, security]
---

# ADR-0065: New signup is controlled by email-bound signup token redeem

## Context

Current Azents authentication model uses email OTP verification as single entry point for both login and signup. `/auth/v1/email/send-code` sends OTP, and when `/auth/v1/email/verify` succeeds, existing user logs in while new email automatically creates `User` and primary `UserEmail`.

This makes email login easy to provide as first-class feature, but creates two problems for open-source transition and self-host support.

- We do not want email delivery infrastructure such as SMTP/SES to become mandatory prerequisite for self-host installation.
- If hosted server has public signup open, it becomes attack surface for account creation spam, email sending cost, and compute/LLM resource abuse.

Therefore new account creation authority must be separated from email delivery itself and controlled by signup authority explicitly issued by operator.

## Decision

### ADR-0065-D1. Main domain object of signup authority is signup token

Use `signup_token` as first-class domain object, not signup link. Link is only a presentation method that passes token through URL.

Signup token is source of truth for account creation authority; raw token is not stored and only hash is stored. Manual link, email delivery, future CLI code/QR and similar delivery methods all use same token object.

### ADR-0065-D2. Existing email OTP based new signup migrates to email-bound signup token redeem

Email OTP remains for existing user login and security elevation. New user creation happens only through signup token redeem.

Email-based signup UX is redefined as flow that creates email-bound signup token, delivers it by email, then creates account by token redeem. Therefore signup-on-first-verify behavior of `AuthService.verify_code` must be removed from default path.

### ADR-0065-D3. Signup token is always email-bound and successful redeem treats that email as verified

Signup token is always fixed to exactly one email. User email created or linked during redeem must match token email.

When token redeem succeeds, corresponding `UserEmail` is treated as verified. Token delivered by email naturally verifies through inbox access. Token manually delivered by Admin trusts Admin's choice.

Generic signup token is not created.

### ADR-0065-D4. Workspace invitation remains email-bound membership intent

Workspace invitation is not new account creation authority. It remains membership intent inviting specific email to specific workspace, as today.

Invitation can be stored by email even when invited email does not yet have user. If user later signs up with same email, pending invitation is exposed; accepting it creates workspace membership.

If SMTP is configured and instance registration policy allows, invitation email may include signup token link. Even then signup token is account creation authority, while invitation is membership authority.

### ADR-0065-D5. First owner bootstrap is separate flow from signup token

For first self-host installation experience, allow first owner bootstrap only when user count is 0. Bootstrap creates first owner with email/password without SMTP and automatically closes after success.

Bootstrap is installation/initialization flow, so it is separated from signup token representing new account creation authority during normal operation. Hosted production must be able to disable bootstrap by config.

## Consequences

### Positive

- Admin can manually deliver email-bound signup token and create new account without SMTP.
- Hosted environment can close public signup attack surface.
- New account creation path converges on signup token redeem.
- Responsibilities of Workspace invitation and instance signup authority are separated.
- Existing email signup UX can be preserved through token email delivery.

### Negative / Trade-offs

- Existing signup-on-first-verify UX changes.
- New user creation behavior of `AuthService.verify_code` and related tests must be changed.
- Repository/service path is needed to actually populate UserEmail verification state.
- If Admin issues token to wrong email, that email is treated as verified; audit and UI confirmation are important.

## Alternatives

### Use signup link as main domain object

Link is URL presentation and only one token delivery method. Token-centered model is more natural if future CLI code, QR, email-only delivery are supported. Rejected.

### Allow generic signup token

Token not fixed to email allows anyone to create account with arbitrary email, weakening meaning of email trust. Goal here is to reduce SMTP dependency while preserving email-based account model. Rejected.

### Workspace invitation directly has new signup authority

Workspace manager could bypass instance account creation authority. Invitation should remain membership intent; if needed, include separate signup token in invitation email. Rejected.

### Model bootstrap as signup token too

This unifies account creation path, but first installation would need token creation/delivery UX and complicate self-host initial experience. Simpler to keep bootstrap as installation flow open only when user count is 0. Rejected.
