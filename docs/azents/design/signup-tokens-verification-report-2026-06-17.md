---
title: "Signup Tokens Verification Report"
created: 2026-06-17
updated: 2026-06-18
tags: [backend, frontend, testing]
---

# Signup Tokens Verification Report

## Scope

This report records verification results performed in local runtime as of 2026-06-17 for Phase 1–4 implementation of signup token stacked PR.

## Executed Verification

### Python

- `cd python/apps/azents && uv run ruff check .`
- `cd python/apps/azents && uv run ruff format --check .`
- `cd python/apps/azents && uv run pyright`
- `cd python/apps/azents && uv run pytest src/azents/repos/signup_token/repository_test.py src/azents/services/signup_token/service_test.py src/azents/services/auth/service_test.py src/azents/repos/user/repository_test.py src/azents/services/workspace/service_test.py -q`

Results:

- ruff check: PASS
- ruff format check: PASS
- pyright: PASS
- pytest: all 27 targeted tests SKIPPED under Docker fixture conditions of current runtime

### TypeScript

- `cd typescript && pnpm run lint --filter=@azents/web`
- `cd typescript && pnpm run format:check --filter=@azents/web`
- `cd typescript && pnpm run typecheck --filter=@azents/web`

Results:

- lint: PASS
- format check: PASS
- typecheck: PASS

## QA Checklist Results

| QA | Result | Evidence | Remaining verification |
|---|---|---|---|
| QA-1. Manual signup with signup token | Partial PASS | Backend service/repo/API implementation, pyright/ruff passed. Service test skipped due to Docker fixture condition | Need verify redeem creates User/UserEmail/PasswordLogin/Session in actual DB fixture or CI |
| QA-2. Block automatic signup for new user email OTP | Partial PASS | `AuthService.verify_code` new user branch changed to return `RegistrationRequired`. Static verification passed | Need verify no user is created after new email verify in actual DB fixture/CI |
| QA-3. Preserve existing user email OTP login | Partial PASS | Existing user branch preserved and auth service test target included | Need verify existing user verify succeeds in actual DB fixture/CI |
| QA-4. Workspace invitation exposed by email | Needs verification | Path implemented to include signup token link in invitation email | Need E2E: create invitation → signup redeem → received invitations list/accept |
| QA-5. Bootstrap first owner | Partial PASS | bootstrap status/API/service/UI implemented, workspace service test target included | Need verify first call succeeds and second call rejected in actual DB fixture/CI |

## Fixes Applied During Verification

- Regenerated TypeScript generated client from OpenAPI changes.
- Cleaned up import/order/format according to frontend lint/typecheck results.
- Cleaned up test helper typing according to backend pyright results.

## Follow-up Corrections After Full Review on 2026-06-18

Compared design/ADR/current PR stack again and found/fixed these missing or partial implementations.

| Item | Correction result |
|---|---|
| Failed redeem could consume `used_count` | Changed to perform `claim_for_redemption` only after token availability/email/existing-user validation. Added service tests proving email mismatch, existing email, and weak password failures do not consume usage count. |
| Missing Admin signup token web UI | Added `/account/signup-tokens` page and `signupTokenAdmin` tRPC router. Implemented manual token issuance, metadata list, revoke, one-time raw link display/copy UX. |
| Login signup CTA always visible | Added `GET /auth/v1/signup/status` and changed CTA to show only when `registration_mode=signup_token` and email delivery is configured. |
| Missing admin token creator attribution | azents-web tRPC admin client now forwards current access token to admin API, and admin create route records optional current user as `created_by_user_id`. |
| Preview exposed full email | Changed preview response email value to masked hint, and `/signup` screen now requires user to enter email directly for redeem. |
| Insufficient verification of invitation for non-existing user followed by signup token signup | Added E2E scenario: invite non-existing user email → signup token signup with same email → received invitations lookup → accept → verify workspace membership. |
| Insufficient internal row verification for manual signup | Added service test verifying creation of `UserEmail.verified_at`, `PasswordLogin`, `Session`, and `signup_token_redemptions` rows. |
| Insufficient expired/revoked token verification | Added service tests for expired token and revoked token redeem failures. |
| Insufficient bootstrap disabled verification | Added service test rejecting bootstrap when `first_owner_bootstrap_enabled=false`. |
| Insufficient verification preventing raw token re-exposure | Added service test proving signup token list output does not include `plaintext_token` or `token_hash`. |

Additionally, dumped OpenAPI spec again and regenerated `@azents/public-client`, `@azents/admin-client`. Living spec `docs/azents/spec/domain/user-auth.md` was updated as of 2026-06-18.

## Conclusion

Static verification and frontend type verification passed. Docker-backed DB tests were skipped in current runtime, so QA items requiring actual DB state need additional verification in CI or environment with Docker fixture available.
