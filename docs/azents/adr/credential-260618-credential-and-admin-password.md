---
title: "Introduce credential provider model and admin password reset token"
created: 2026-06-18
tags: [architecture, backend, api, security, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: credential-260618
historical_reconstruction: true
migration_source: "docs/azents/adr/0066-credential-provider-and-admin-password-reset.md"
---

# credential-260618/ADR: Introduce credential provider model and admin password reset token

## Context

[signup-260617/ADR](./signup-260617-signup-token-registration.md) separated new signup authority from email delivery so SMTP/SES is not mandatory prerequisite for open-source/self-host transition. New signup is controlled by signup token, and admin can manually deliver signup link even without SMTP.

However, login and security settings still have SMTP dependency. Current system displays verified email as if it is always usable authentication method, and uses email OTP for login and elevation. In self-host instance without SMTP, email OTP cannot be sent, so verified email alone cannot be actual login credential.

Password management also currently provides only features where logged-in user sets/changes/deletes password while elevated. If user forgot password and SMTP is not configured, there is no self-service recovery path. When SMTP is configured, user can log in by email and change password, so separate forgot-password email flow is not core requirement.

Credentials such as TOTP and passkey may be added later, so implementation strongly tied to password/email should be avoided. Authentication method query, elevation method query, credential deletion invariant, and password reset recovery path are organized around credential provider.

## Decision

### credential-260618/ADR-D1. Login methods are modeled as CredentialProvider

Password and verified email are both credentials that can be used for login. Introduce `CredentialProvider` boundary from initial implementation.

First providers are `PasswordCredentialProvider` and `EmailCredentialProvider`. `CredentialService` composes providers to calculate credential summary, login/elevation availability, and deletion invariant.

Goal of this decision is not minimum implementation but foundation for future credentials such as TOTP/passkey. Upper services do not directly combine password/email detail tables; they go through CredentialService.

### credential-260618/ADR-D2. Internal CredentialSummary is rich, while API has purpose-specific projections

CredentialProvider internally produces rich summary such as `configured`, `valid`, `can_login`, `can_elevate`, `can_remove`, `unavailable_reason`.

Do not expose this summary as-is in every API. Public login API projects minimal information to avoid user enumeration. Authenticated security/elevation API is about user's own account, so it may provide detailed information such as configured/valid/can_remove/unavailable_reason.

### credential-260618/ADR-D3. Verified email is valid credential only when SMTP is configured

Email with `UserEmail.verified_at` set is configured credential, but it is valid credential usable for login/elevation only when outbound email is configured and OTP can actually be sent.

On instance without SMTP, verified email can remain user identity attribute, but is not valid login credential. In that case password or future non-email credential is required.

### credential-260618/ADR-D4. Credential deletion must preserve at least one valid credential invariant

User should have at least one valid credential in normal state. Credential deletion is allowed only if at least one valid credential remains after deletion.

Password deletion must also pass CredentialService invariant judgment. SMTP disabled + password-only user cannot delete password. SMTP enabled user with valid verified email credential can delete password. Future TOTP/passkey valid credentials join same invariant calculation.

### credential-260618/ADR-D5. Allow recovery-required state from SMTP disabled and recover by admin reset

SMTP disabled state is allowed. In this state, verified email is configured credential but not valid credential.

Existing email-only user may become recovery-required state with zero valid credentials under SMTP disabled state. UI or diagnostic guides that password setup or admin reset is needed. Recovery path is password reset token issued by admin.

### credential-260618/ADR-D6. SMTP-less password recovery is provided by user_id-bound admin reset token

If user forgot password and SMTP is not configured, recovery through email login is impossible. In this case admin creates password reset token for existing user and manually delivers link containing raw token.

Password reset token is bound to existing `user_id`. Email snapshot is not stored. If Admin list or public preview needs email hint, query current user email and display masked hint.

Password reset token is single-use, valid by default for 24 hours, and stored hash-only. Raw token or reset URL is displayed only once immediately after creation and is never re-exposed in list/admin response/log.

### credential-260618/ADR-D7. Password reset token only recovers password credential and does not automatically log in

Password reset token redeem creates or updates password credential. Reset token itself is not extended as login credential; after success user logs in again with new password.

Reset success is audited in separate redemption row. On reset success, all existing refresh sessions are revoked by default. This is because password reset represents account recovery and compromise response.

## Consequences

### Positive

- Admin can recover user who forgot password in SMTP-less self-host environment.
- Actual usability of Email credential matches SMTP setting.
- Prevents regression where password deletion leaves user unable to log in.
- Reduces spread of password/email-specific branches when future credentials such as TOTP/passkey are added.
- Reuses hash-only, one-time plaintext, manual delivery pattern validated by signup token for password reset.

### Negative / Trade-offs

- Implementing CredentialProvider boundary from start is larger scope than simple helper approach.
- API design becomes more complex because public login projection and authenticated security projection must be separated.
- Under SMTP disabled, email-only user can become recovery-required and need admin intervention.
- Admin-issued reset link relies on manual delivery security, requiring short TTL and audit.
- Self-service forgot-password email flow is not included in this decision scope.

## Alternatives

### Handle only with existing AuthService/SecurityService helper

Fast to implement, but credential judgment scatters across login method, elevation method, password deletion, reset recovery. With TOTP/passkey later, password/email-specific conditions would likely spread in many places. Rejected.

### Keep only internal helpers in CredentialService and extract provider boundary later

Initial implementation size is smaller, but insufficient because goal of this work is to build future credential foundation. Add provider boundary from beginning considering TOTP/passkey. Rejected.

### Expose internal CredentialSummary as-is in every API

Model is simple, but public login API could reveal excessive user-specific credential state. Use purpose-specific projection to reduce user enumeration risk. Rejected.

### Hard fail when SMTP disabled

This strongly prevents invalid credential state, but conflicts with self-host goal to operate without SMTP. SMTP config belongs to env/config/infra and app layer cannot always control when it changes. Instead allow recovery-required state and admin reset recovery. Rejected.

### Make password reset token email-bound

Similar to signup token, but password reset is existing user credential recovery. Bind by user_id to avoid entangling reset target with email change/reuse policy. Rejected.

### Store email snapshot in password reset token

It can preserve audit of delivery target at issue time, but has little benefit for 24-hour single-use token. If snapshot diverges from current email, UI explanation burden increases. Querying current email by user_id for hint is sufficient. Rejected.

### Automatically log in after reset token redeem

Convenient for user, but reset token effectively becomes login token and stolen token impact increases. Password reset focuses only on credential recovery; require new password login after success. Rejected.

## Migration provenance

- Historical source filename: `0066-credential-provider-and-admin-password-reset.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
