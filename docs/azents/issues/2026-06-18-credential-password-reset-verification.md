---
title: "Credential provider password reset verification"
created: 2026-06-18
tags: [backend, frontend, security, testing]
---

# Credential provider password reset verification

## Scope

PR stack:

- #4719 — design
- #4720 — credential provider backend
- #4721 — password reset backend/API
- #4722 — frontend/client integration
- #TBD — verification

## Strict spec implementation check

Source spec checked: `docs/azents/spec/domain/user-auth.md` as of 2026-06-18.

| Spec element | Current implementation after stack | Verdict | Evidence |
|---|---|---|---|
| Email OTP verify logs in existing user and does not create user unless `registration_mode=open` | Preserved | PASS | `AuthService.verify_code` unchanged for verify behavior |
| Signup token controlled registration | Preserved | PASS | signup token service/routes unchanged except adjacent OpenAPI regeneration |
| Signup token hash-only, single-use default, atomic claim, redemption audit | Preserved | PASS | signup token model/repo/service unchanged |
| Password login uses email lookup + bcrypt hash + no-leak invalid credentials | Preserved | PASS | `AuthService.login_with_password` unchanged except adjacent service dependency injection |
| Login methods no-leak behavior for missing email | Preserved for password; email flow projected as instance-level availability | PASS | `CredentialService.get_login_projection` returns `has_password=false` for unknown email and `email_available` from SMTP availability only |
| Security settings require elevated token | Preserved | PASS | route dependency for `/security/v1/auth-methods`, `/security/v1/password` unchanged |
| Elevation supports email OTP and password re-entry | Preserved | PASS | `send_elevation_code` remains callable; `elevate_with_email` and `elevate_with_password` preserved |
| Password set/update supports existing or missing password | Preserved | PASS | `SecurityService.set_password` unchanged |
| Password remove endpoint exists | Changed to enforce last valid credential invariant | PASS | `SecurityService.remove_password` calls `CredentialService.check_remove_allowed` before delete |
| Session refresh rotation/grace | Preserved | PASS | `SessionRepository` and `AuthService.refresh_token` unchanged |
| API reference `/auth/v1/login/methods` returns `{ has_password }` | Implementation now returns `{ has_password, email_available }` | SPEC UPDATE REQUIRED | Spec promotion must update API reference |
| API reference lacks password reset token endpoints | Implementation adds public/admin password reset APIs | SPEC UPDATE REQUIRED | Spec promotion must add endpoints and business rules |
| Domain model lacks PasswordResetToken/Redemption | Implementation adds models/tables | SPEC UPDATE REQUIRED | Spec promotion must update ERD/domain model |
| Frontend routes lack `/reset-password` and `/account/password-reset-tokens` | Implementation adds routes | SPEC UPDATE REQUIRED | Spec promotion must update frontend routes |

## Design requirement implementation check

| Requirement | Verdict | Evidence |
|---|---|---|
| REQ-1 CredentialProvider foundation | PASS | `services/credential/providers.py`, `CredentialService` |
| REQ-2 Internal summary + API projection | PASS | `CredentialSummary`, `CredentialProjection`, `LoginCredentialProjection` |
| REQ-3 SMTP-gated verified email credential | PASS | `EmailCredentialProvider._build` uses `EmailService.configured` |
| REQ-4 Credential deletion invariant | PASS | `CredentialService._apply_remove_invariants`, `SecurityService.remove_password` |
| REQ-5 Recovery-required state representation | PASS | Email credential can be configured+invalid with `smtp_not_configured`; diagnostic exposure via authenticated methods |
| REQ-6 Admin user_id-bound reset token | PASS | `PasswordResetTokenService.create`, `password_reset_tokens.user_id`; no email snapshot column |
| REQ-7 Reset redeem recovers password credential | PASS | `PasswordResetTokenService.redeem` creates/updates password login and writes redemption row |
| REQ-8 Reset does not auto-login and revokes sessions | PASS | redeem returns `{ success: true }`; `SessionRepository.revoke_all_by_user` called |

## Verification commands

Executed before verification PR:

- `cd python/apps/azents && uv run ruff check --fix ...`
- `cd python/apps/azents && uv run ruff format ...`
- `cd python/apps/azents && uv run pyright`
- `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
- `cd python/apps/azents && uv run pytest -q ...` — local testcontainers skipped because Docker unavailable
- `cd typescript && pnpm turbo run generate --filter=@azents/public-client`
- `cd typescript && pnpm turbo run generate --filter=@azents/admin-client`
- `cd typescript && pnpm run format --filter=@azents/web --filter=@azents/public-client --filter=@azents/admin-client`
- `cd typescript && pnpm run typecheck --filter=@azents/web --filter=@azents/public-client --filter=@azents/admin-client`
- `cd typescript && pnpm run lint --filter=@azents/web`

## CI/E2E status

- 2026-06-18 initial #4720 deterministic E2E failed because `send_elevation_code` was blocked when SMTP was disabled.
- Fix applied in #4720: method projection still marks email invalid under SMTP disabled, but deterministic email elevation code generation remains available for existing E2E/testenv path.
- 2026-06-18 second #4720 deterministic E2E failed because old E2E assertions expected SMTP-disabled email to be enabled and password deletion to succeed even when password was the last valid credential.
- Fix applied in #4720: updated deterministic E2E assertions to expect `smtp_not_configured` email credential state and `409` on last-valid-password deletion.
- Rebased and force-pushed #4721/#4722 after #4720 fixes.
- Final CI status: #4719, #4720, #4721, #4722, #4723, and #4724 are all CLEAN as of 2026-06-18.
