---
title: "Signup Token Design"
created: 2026-06-17
updated: 2026-06-17
implemented: 2026-06-17
tags: [backend, api, frontend, security, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: signup-260617
migration_source: "docs/azents/design/signup-tokens.md"
historical_reconstruction: true
---

# Signup Token Design

## Overview

Separate Azents new account creation authority into `signup_token`. Currently, email OTP verification handles both login and signup; if email is new, `AuthService.verify_code` automatically creates `User` and primary `UserEmail`. This structure makes SMTP-less self-host installation difficult and creates public signup attack surface on hosted server.

This design separates signup and login. Login is existing account authentication, and signup is email-bound signup token redeem. Email-based signup is redefined as delivery method that sends signup token by email. In environments without SMTP, admin manually delivers same token.

## Requirements

### REQ-1. New account creation is controlled by signup token redeem

New `User` creation must be possible only through signup token redeem except bootstrap exception.

- Related decisions: [signup-260617/ADR-D1](../adr/signup-260617-signup-token-registration.md), [signup-260617/ADR-D2](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - Even if email OTP verify completes with new email without signup token, `User` is not created.
  - Valid signup token redeem creates `User`, primary `UserEmail`, `Session`.
  - Existing user email OTP login continues to work.

### REQ-2. Signup token is always email-bound

Every signup token must be fixed to one normalized email, and redeem input email must match token email.

- Related decisions: [signup-260617/ADR-D3](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - email is required in signup token create request.
  - redeem with email different from token email fails.
  - generic signup token creation API does not exist.

### REQ-3. Signup token redeem is treated as email verification completed

`UserEmail` created by token redeem must be verified.

- Related decisions: [signup-260617/ADR-D3](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - After successful redeem, primary `UserEmail.verified_at` is filled.
  - email delivery and manual delivery have same redeem semantics.
  - Use history of admin-issued token remains as auditable redemption row.

### REQ-4. Email-based signup is implemented as signup token email delivery

Email signup UX must create email-bound signup token and deliver it by email.

- Related decisions: [signup-260617/ADR-D2](../adr/signup-260617-signup-token-registration.md), [signup-260617/ADR-D3](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - When SMTP configured, email signup request creates signup token and sends signup link by email.
  - When SMTP not configured, email signup request fails as delivery unavailable or is hidden in UI.
  - Email signup also creates account through redeem endpoint.

### REQ-5. Workspace invitation remains email-bound membership intent

Workspace invitation does not directly have new account creation authority.

- Related decisions: [signup-260617/ADR-D4](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - Workspace invitation can be created for email with no user.
  - Pending invitation is exposed to user who signs up with same email.
  - Even if invitation email includes signup token link, account creation authority is in signup token.

### REQ-6. First owner bootstrap is separate from signup token

Allow first owner bootstrap only when self-host installation has zero users.

- Related decisions: [signup-260617/ADR-D5](../adr/signup-260617-signup-token-registration.md)
- Acceptance criteria:
  - When user count is 0, first owner can be created without SMTP.
  - When user count is 1 or more, bootstrap endpoint is rejected.
  - In hosted production, bootstrap can be disabled by config.

## Decision Table

| ADR decision | Requirements |
|---|---|
| [signup-260617/ADR-D1](../adr/signup-260617-signup-token-registration.md) | REQ-1 |
| [signup-260617/ADR-D2](../adr/signup-260617-signup-token-registration.md) | REQ-1, REQ-4 |
| [signup-260617/ADR-D3](../adr/signup-260617-signup-token-registration.md) | REQ-2, REQ-3, REQ-4 |
| [signup-260617/ADR-D4](../adr/signup-260617-signup-token-registration.md) | REQ-5 |
| [signup-260617/ADR-D5](../adr/signup-260617-signup-token-registration.md) | REQ-6 |

## Discussion Points and Decisions

### 1. Signup authority primitive

Decision: Use `signup_token`, not `signup_link`, as primary domain object.

Link is one token delivery method. Token-centered model naturally extends presentation such as manual URL, email delivery, CLI code, QR.

### 2. Existing email OTP new signup

Decision: Migrate existing email OTP based new signup onto email-bound signup token.

Email OTP remains for existing user login and elevation. New signup is performed only by token redeem.

### 3. Relationship between Signup token and email verification

Decision: signup token is always email-bound, and successful redeem treats corresponding email as verified.

Email delivery is naturally verified by inbox access, and admin manual delivery trusts admin choice.

### 4. Relationship between Workspace invitation and signup token

Decision: workspace invitation remains email-bound membership intent.

A userless email can be invited, and when user signs up with same email, pending invitation is exposed. Invitation email can include signup token link when policy allows, but invitation itself does not have account creation authority.

### 5. First owner bootstrap

Decision: first owner bootstrap remains separate flow from signup token.

It creates first owner without SMTP only when user count is 0, and automatically closes afterward.

## Architecture

Major responsibilities are split as follows.

| Component | Responsibility |
|---|---|
| `SignupTokenService` | token create, preview, redeem, revoke, redemption audit |
| `AuthService` | existing user login, refresh, logout, password login. remove new user auto-creation |
| `EmailService` | add signup token email delivery. does not block manual delivery when unconfigured |
| `WorkspaceInvitationService` | keep email-bound invitation. include signup token link in invitation email if needed |
| Registration policy checker | determine conditions for new user creation |
| Bootstrap service | create first owner when user count is 0 |

Signup token redeem flow:

1. User accesses signup page with URL or code containing signup token.
2. Public API performs token preview.
3. User submits password and required profile fields.
4. Redeem transaction validates token state and claims use count.
5. Create `User` and primary `UserEmail` with token email and fill `verified_at`.
6. Create password login.
7. Issue session and JWT access token.
8. Pending workspace invitations for same email are exposed through workspace list or invitation API.

## Data Model

### `signup_tokens`

| Field | Description |
|---|---|
| id | UUID7 hex primary key |
| token_hash | plaintext token hash. unique |
| email | normalized email. required |
| created_by_user_id | admin creator. nullable for bootstrap/system issuance |
| delivery_method | manual or email |
| expires_at | expiration time |
| max_uses | max use count. default 1 |
| used_count | use count |
| revoked_at | revocation time |
| created_at, updated_at | timestamp |

Constraints:

- `token_hash` unique
- `email` not null
- `max_uses` positive
- `used_count <= max_uses`
- indexes on `expires_at`, `email`, `created_by_user_id`, `revoked_at`

### `signup_token_redemptions`

| Field | Description |
|---|---|
| id | UUID7 hex primary key |
| signup_token_id | used token |
| user_id | created user |
| email | redeem email |
| ip_address | request IP |
| user_agent | request user agent |
| redeemed_at | use time |

Redemption row is always left even for single-use token. `used_count` increment is processed atomically within redeem transaction by row lock or conditional update.

### `user_emails.verified_at`

Current `UserRepository.create` creates primary `UserEmail` but does not fill `verified_at`. Signup token redeem must fill verified timestamp, so implement one of following.

- Add `email_verified_at` to `UserCreate`.
- Or add `UserEmailRepository.mark_verified(email_id)` and call immediately after user creation.

From feasibility standpoint, because `UserRepository.create` handles circular FK, passing verified value at user creation time is simplest.

## API

### Public API

| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/auth/v1/signup-tokens/preview` | query token state and email mask | unnecessary |
| POST | `/auth/v1/signup-tokens/redeem` | create account and issue session with token | unnecessary |
| POST | `/auth/v1/signup/email` | create email-bound signup token and send email | unnecessary, policy allow needed |
| POST | `/auth/v1/bootstrap/owner` | create first owner when user count is 0 | unnecessary, config/user count conditions |

Preview does not excessively reveal token existence. Even in valid state, email is masked or used only to confirm match with email in URL.

Redeem input:

| Field | Description |
|---|---|
| token | plaintext signup token |
| email | email that must match token email |
| password | initial password |
| user_agent, ip_address | collected from request |

Redeem output uses same token response shape as existing verify/password login.

### Admin API

| Method | Path | Description |
|---|---|---|
| POST | `/admin/auth/v1/signup-tokens` | create email-bound token. plaintext token/link returned only once in response |
| GET | `/admin/auth/v1/signup-tokens` | list token metadata. excludes plaintext token |
| DELETE | `/admin/auth/v1/signup-tokens/{id}` | revoke |

Admin API is already separated as separate admin app, so first implementation safely attaches here.

## Frontend

### Admin signup token creation screen

Admin enters email to create token. Shows manually copyable link regardless of SMTP status.

UI states:

| State | Behavior |
|---|---|
| SMTP not configured | hide or disable email send button. copy link primary |
| SMTP configured | both email send and copy link possible |
| immediately after token creation | show plaintext link once, provide copy button |
| list | show email, expires_at, used_count, revoked status. do not show plaintext token |

### Signup page

Add `/signup?token=...` page.

States:

| State | Display |
|---|---|
| valid | email confirmation, password setup form |
| expired | expiration notice |
| revoked | revocation notice |
| used | already used notice |
| invalid | invalid link notice |
| existing user | guide to proceed after login or account already exists notice |

### Login page

Login page is existing account authentication screen.

- Existing user logs in with email OTP or password.
- If new email and no signup token, show “signup token required”.
- Expose “receive signup link by email” CTA only when SMTP and registration policy allow.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `registration_mode` | `signup_token` | New signup allow method |
| `signup_on_email_verify_enabled` | `false` | existing signup-on-first-verify compatibility flag. default off |
| `bootstrap_first_owner_enabled` | `true` | allow bootstrap when user count is 0 |
| `signup_token_default_expire_hours` | `168` | default 7 days |
| `signup_token_default_max_uses` | `1` | default single-use |

Initial values of `registration_mode`:

| Value | Meaning |
|---|---|
| closed | block new signup |
| signup_token | signup only by signup token redeem |
| open | existing public signup compatibility. explicit setting required |

Hosted production uses `closed` or `signup_token`. Recommended self-host default is `signup_token` with bootstrap enabled.

## Feasibility Verification

### Fit with current code

| Item | Result | Basis |
|---|---|---|
| identify new user auto-creation location | possible | `AuthService.verify_code` calls `UserRepository.create` when absent after `user_email_repo.get_by_email` |
| preserve existing user login | possible | existing user path in `verify_code` continues to session creation |
| password-based signup possibility | possible | `PasswordLoginRepository.create` and password hashing util already exist |
| SMTP-less self-host support | possible | `EmailService.configured` false skips sending. But signup email delivery endpoint must change to explicit error |
| UserEmail verified handling | needs reinforcement | `UserEmail.verified_at` column exists but `UserRepository.create` does not fill it |
| Workspace invitation separation | possible | `workspace_invitations` is already email-bound and can invite userless email |
| Invitation query | possible | `list_pending_by_emails` queries pending invitation by current user's emails |
| Admin API surface | possible | admin app already separate from public app with auth/user_email/invitation admin routes |
| Migration addition | possible | azents Alembic revision structure and postgres enum convention already exist |

### Core points needing change

| File/area | Needed change |
|---|---|
| `core/config.py` | add registration/signup token/bootstrap settings |
| `rdb/models/*` | add `signup_tokens`, `signup_token_redemptions` models |
| `repos/signup_token/**` | add token CRUD, atomic redeem claim, list/revoke |
| `repos/user/**` or `repos/user_email/**` | add path to set primary email verified_at |
| `services/auth/**` | remove or policy-gate new user auto-creation |
| `services/signup_token/**` | add create/preview/redeem/email delivery orchestration |
| `core/email/service.py` | add signup token email template/send method |
| `services/workspace_invitation/**` | apply policy whether to include signup token link in invitation email |
| `api/public/auth/v1/**` | add signup token public endpoints |
| `api/admin/auth/v1/**` | add signup token admin endpoints |
| `typescript/apps/azents-web` | add signup/admin/login UX |

### Directly verified implementation risks

1. `EmailService.send_verification_code` puts code in log extra when unconfigured. Signup token plaintext must not remain in logs. Signup token email delivery must handle unconfigured case separately without putting plaintext token in log extra.
2. Current `UserEmail.verified_at` is effectively drifted state. Signup token redeem must add path that actually uses this column to guarantee verified state.
3. `AuthService.verify_code` strongly mixes login and signup. Minimal change is blocking only new user branch with policy check while preserving existing user branch.
4. Invitation email currently always sends `/login?next=/workspaces`. To send signup token link to new user, invitation service must construct different email context based on user existence, email configured, registration policy.
5. Atomic redeem has race if implemented as simple read then update. DB row lock or conditional update is required.

### Alternative re-review result

- Generic `auth_action_links` model is good for integrating password reset/email change, but excessive for current signup scope.
- Putting signup authority in workspace invitation blurs instance registration control.
- Unifying bootstrap into signup token complicates initial self-host UX.

Therefore, ADR decision does not conflict with current codebase, and needed changes converge to clear service/table addition and `AuthService.verify_code` new user branch restriction.

## Test Strategy

Product behavior verification is E2E primary. Unit/integration/static check is supporting verification.

### E2E primary verification matrix

| Scenario | Verification |
|---|---|
| Admin creates signup token and new user signs up | account creation at `/signup?token`, session issued, `/workspaces` accessible |
| Manual token creation with SMTP disabled | token link creation and copy UX succeeds without email sending |
| Email-bound token redeem | created `UserEmail.verified_at` is filled and login session issued |
| Token email mismatch | redeem fails, user not created, used_count not increased |
| Single-use token reuse | only first redeem succeeds, second redeem fails |
| Existing user email OTP login | existing account can still log in |
| New user email OTP verify | user creation blocked without signup token |
| Workspace invitation for absent user | after invitation creation, signup with same email exposes pending invitation |
| user count 0 bootstrap | first owner creation succeeds without SMTP |
| user count 1+ bootstrap | bootstrap rejected |

### E2E primary verification plan

- Location: `testenv/azents/e2e`
- Call public/admin API against real devserver.
- Prepare empty instance, existing user, workspace manager, invitation state with deterministic DB fixture.
- SMTP live credential is not required for default verification. Email delivery is verified separately with dev mail sink or E2E fixture capable of service mock.

### Seed/fixture requirements

- empty instance fixture
- instance admin fixture
- existing user fixture
- workspace + manager fixture
- pending invitation fixture
- SMTP disabled config fixture
- optional dev mail sink fixture

### Credential/prerequisite snapshot requirements

- Basic deterministic E2E must not require external credential.
- SES/SMTP live verification is separated as optional live_external.
- When Live credential absent, PR CI must sufficiently PASS through deterministic path, not skip.

### Evidence format

- E2E execution command and working directory
- API response snapshot summary
- generated user/workspace invitation read model assertion
- assertion that signup token plaintext is not exposed in list/admin response/log
- trace/log excerpt on failure

### CI execution policy

- Deterministic E2E included in PR CI.
- Live email delivery is nightly or manual-label optional workflow.
- Optional live test skips on credential missing; fails if delivery fails while credential configured.

## QA Checklist

### QA-1. Signup token manual signup

#### What to check

Verify admin can create email-bound signup token and user can create account with token.

#### Why it matters

This is core signup path for SMTP-less self-host.

#### How to check

In `testenv/azents/e2e`, create token through admin API, then call public redeem API and verify `/workspaces` access.

#### Expected result

User, primary UserEmail, PasswordLogin, Session are created and access/refresh token returned.

#### Execution result

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

#### Fixes applied

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

### QA-2. Block new user email OTP auto-signup

#### What to check

Verify that successful email OTP verify with new email without signup token does not create user.

#### Why it matters

Core regression prevention that closes hosted public signup attack surface.

#### How to check

Call send-code/verify path in E2E using email absent from DB.

#### Expected result

Verify returns registration required class error and user row is not created.

#### Execution result

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

#### Fixes applied

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

### QA-3. Preserve Existing user email OTP login

#### What to check

Verify existing user can still log in with email OTP.

#### Why it matters

Signup flow separation must not break existing login UX.

#### How to check

Run send-code/verify with existing user fixture.

#### Expected result

Session and token response are issued.

#### Execution result

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

#### Fixes applied

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

### QA-4. Workspace invitation exposed by email

#### What to check

Create workspace invitation for absent user email, signup with same email through signup token, and verify invitation is exposed.

#### Why it matters

Must preserve invitation UX while separating invitation from account creation.

#### How to check

Use Workspace manager fixture to create invitation, redeem signup token, query received invitations API.

#### Expected result

Pending invitation is displayed to signed-up user and accept creates membership.

#### Execution result

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

#### Fixes applied

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

### QA-5. Bootstrap first owner

#### What to check

Verify first owner bootstrap is possible when User count is 0 and repeated execution is rejected afterward.

#### Why it matters

Must satisfy self-host initial setup and hosted security boundary simultaneously.

#### How to check

Call bootstrap API in empty DB fixture, then call same API again.

#### Expected result

First call creates owner user and second call is rejected.

#### Execution result

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

#### Fixes applied

See `docs/azents/design/signup-tokens-verification-report-2026-06-17.md`.

## Implementation Plan

### Phase 1. Backend foundation

- Add registration/signup token/bootstrap settings to Config.
- Add `signup_tokens`, `signup_token_redemptions` migration/model/repo.
- Add path to set `UserEmail.verified_at`.
- Implement `SignupTokenService.create/preview/redeem/revoke`.
- Add public/admin API.

### Phase 2. Auth migration

- Block new user auto-creation in `AuthService.verify_code`.
- Implement email signup endpoint as signup token email delivery.
- Add signup token delivery to Email template/service.

### Phase 3. Frontend UX

- Add `/signup` page.
- Add Admin signup token create/list/revoke UI.
- Add registration required guidance and conditional email signup CTA to Login page.

### Phase 4. Workspace invitation integration

- Confirm pending invitation is preserved for absent user invitation.
- Include signup token link in invitation email if policy and SMTP state match.
- Verify pending invitation exposure/accept UX after signup.

### Phase 5. Bootstrap

- Add user count 0 setup status API.
- Add first owner bootstrap API/UI.
- Apply hosted production bootstrap disable setting.

## Alternatives Considered

### Generic `auth_action_links` table

Can integrate password reset, email change, and verify email, but current scope is signup separation, so it is excessive. Start with Signup token and unify later when need becomes clear.

### Generic signup token

Token not fixed to email weakens email verification meaning and increases abuse risk. Reject to maintain email-first identity.

### Workspace invitation directly having signup authority

Membership intent and instance account creation authority mix. Invitation remains email-bound membership, and signup is handled by token.

### Unify Bootstrap as signup token

Initial install then requires token issuance/delivery UX. User count 0 exception flow is simpler and better self-host experience.
