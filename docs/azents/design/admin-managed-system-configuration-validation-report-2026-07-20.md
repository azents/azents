---
title: "Admin-Managed System Configuration Validation Report"
created: 2026-07-20
tags: [backend, frontend, admin, configuration, security, infra, testenv]
---

# Admin-Managed System Configuration Validation Report

## Scope

This report validates the implementation from [Admin-Managed System Configuration](admin-managed-system-configuration.md) before living-spec promotion.

The validation phase covers:

- the live `system_admin` authorization boundary and redacted inventory/detail projections;
- Platform GitHub App candidate validation, activation, retry, cancellation, health, audit, and optimistic concurrency;
- deterministic GitHub App and OAuth credential classifications without external network access;
- secret exclusion from API responses, logs, provider diagnostics, audit projections, and report evidence;
- Admin Web navigation and redacted secret replacement controls;
- Public Toolkit reconnect projection and runtime generation/App-binding enforcement at their owning service boundaries;
- environment overlay, migration, Worker/runtime, Redis-independence, and Helm consumer contracts at the narrowest deterministic layer that owns each invariant; and
- optional live GitHub prerequisite and skip/fail policy.

## Environment

- Date: 2026-07-20
- Python: 3.14.6
- Node.js/pnpm: repository toolchain
- Local container prerequisite: unavailable
  - the Docker socket is absent;
  - Testcontainers fails before fixture startup while fetching the Docker server API version.
- Required credential-free deterministic and Web Surface E2E remain mandatory CI gates.
- No protected live GitHub App credentials were available locally. The optional live smoke is therefore skipped locally; configured live verification must fail on invalid credentials, a missing declared installation, or provider failure.

## Validation Results

| Area | Command or evidence | Result |
| --- | --- | --- |
| Backend focused formatting/lint | Ruff on System Settings config, lifecycle, validation client, and Admin route files | Passed |
| Backend focused typing | Pyright on the changed System Settings backend files | Passed with 0 errors |
| Backend focused tests | System Settings lifecycle, GitHub validation client, and Admin route tests | 9 passed, 9 skipped |
| Admin/Main Web focused tests | PR 7 package tests | Admin Web 7 passed; Main Web 46 passed |
| Helm render matrix | PR 7 chart tests with Helm 3.17.3 | 27 passed |
| E2E formatting/lint | Ruff on the fake provider, fixtures, API E2E, and browser E2E | Passed |
| E2E typing | Pyright on the fake provider, fixtures, API E2E, and browser E2E | Passed with 0 errors |
| Fake GitHub boundary unit test | `uv run pytest -q src/tests/test_github_validation_proxy.py` | 1 passed |
| E2E collection | Focused collection for Admin System Settings API and Admin Web | 4 tests collected |
| E2E execution | Focused deployed Admin System Settings API test | Blocked before fixture startup because Docker is unavailable; CI required |

## Added Deterministic Validation Support

The validation branch adds a state-controlled HTTP boundary used by the deployed Admin API fixture. It supports:

- successful authenticated App lookup and OAuth `bad_verification_code` proof;
- App credential rejection;
- OAuth client credential rejection;
- App identity mismatch;
- provider outage; and
- provider rate limiting.

The boundary never logs request headers or bodies, never reflects submitted credentials, and exposes only request counts and the selected non-sensitive scenario to the test process.

The Admin API fixture receives the boundary through a testenv-only process setting. Production behavior retains the canonical GitHub endpoints when this setting is absent.

## Added E2E Coverage

The validation branch adds these product checks through generated clients and real browser/API surfaces:

1. A fresh instance lists exactly one `platform_github_app` Section as not configured at Admin version zero.
2. Redacted detail contains all four fields while secret values remain absent.
3. An ordinary authenticated User receives `403` for inventory, detail, and audit without Section metadata disclosure.
4. An incomplete current setting records a sanitized invalid health result.
5. A complete Admin-managed candidate validates through the deterministic HTTP provider boundary and activates atomically.
6. Activated responses expose App ID, Client ID, secret presence, and sanitized App slug without secret plaintext or effective generation.
7. A stale Admin version returns stable `409`.
8. Provider outage preserves the current version and stores a retryable unavailable candidate.
9. OAuth credential rejection updates the same candidate to a sanitized invalid result without provider response-body leakage.
10. An invalid candidate cannot be confirmed and can be cancelled without altering current state.
11. A valid explicit health check records healthy status and bounded App slug metadata.
12. Audit projections include lifecycle event types and secret action names only; sentinels, provider diagnostics, and effective generation remain absent.
13. Admin API container logs exclude submitted client-secret sentinels and provider-private diagnostics.
14. Admin Web exposes System Settings navigation, Platform GitHub App fields, health, and audit surfaces while secret replacement inputs remain empty.
15. An in-flight candidate that is replaced by another mutation fails with stable `409 system_setting_candidate_replaced` instead of validating or reporting `404` against the replacement.

## Validation Matrix Disposition

| Scenario | Deterministic evidence | Disposition |
| --- | --- | --- |
| Fresh bootstrap and inventory | Existing bootstrap/final-admin E2E plus new inventory/detail E2E | Required CI E2E |
| Admin-managed configuration | New fake-provider Admin API E2E | Required CI E2E |
| Full environment ownership | Field-level resolution/read-only service tests and Helm injection matrix | Owning-layer deterministic coverage |
| Mixed ownership | System Settings resolver tests and dedicated optional Helm keys | Owning-layer deterministic coverage |
| Present-empty overlay | Service test proves presence-based empty override and read-only behavior | Owning-layer deterministic coverage |
| Environment removal with fallback | Shared-DB resolver instances prove Admin fallback visibility when the overlay is absent | Owning-layer deterministic coverage |
| Environment removal without fallback | Resolver incomplete/unconfigured projection tests | Owning-layer deterministic coverage |
| App ID change | Binding impact/claim service tests and Main Web reconnect component tests | Runtime/API owning-layer coverage; no direct DB E2E seed added |
| Same-App credential rotation | Runtime binding tests and candidate secret replacement lifecycle | Owning-layer coverage |
| Upgrade with or without environment App ID | Application-migration binding tests, advisory lock, and marker tests | Migration-layer coverage |
| Migration corruption | Cipher/binding migration rollback tests | Migration-layer coverage |
| OAuth settings change mid-flow | Public OAuth generation test with exchange-call spy | Public API owning-layer coverage |
| Concurrent Admin mutations | Candidate identity fencing test plus stale-version E2E assertion | Required backend and E2E CI |
| Unauthorized access | Existing live-role E2E plus new System Settings API E2E | Required CI E2E |
| Secret redaction | New response/audit/log sentinel scan plus existing crypto/service tests | Required CI E2E |
| Redis unavailable | PostgreSQL-only repositories and no cache/notification correctness dependency | Architecture and service coverage; no local fault-injection execution |
| Helm disabled/full/mixed | Chart render tests cover optional keys and consumer set; Scheduler excluded | Passed in PR 7; required chart CI |
| Public Toolkit reconnect projection | Runtime projection/API tests and Main Web component tests | Owning-layer deterministic coverage; no direct DB test setup permitted |
| Worker token path | Runtime provider and token-boundary tests | Owning-layer deterministic coverage; optional deployed Worker scenario remains prerequisite-bound |

No direct database writes were added to E2E or testenv support. Migration and reconnect states that cannot be constructed through current user-facing API/OAuth paths remain verified at their owning service/runtime layers rather than through prohibited database seeding.

## Findings and Fixes

- Added a deterministic external HTTP boundary so Admin candidate validation is exercised through the deployed service rather than only through `httpx.MockTransport` unit tests.
- Added candidate identity fencing across external validation. A candidate replaced while validation is in flight now returns a stable conflict and cannot validate or activate the replacement candidate accidentally.
- Added Admin API response, audit, provider-diagnostic, and container-log sentinel assertions.
- Added real-browser coverage for System Settings navigation and empty secret replacement controls.

## Optional Live GitHub Policy

Optional live verification requires a dedicated non-production GitHub App, protected private key and client secret, an approved displayable App ID/slug, and at least one declared test installation.

- Missing protected credentials or prerequisite snapshot: SKIP.
- Credentials present but rejected: FAIL.
- Declared installation missing: FAIL.
- Configured provider environment unavailable or rate limited: FAIL.
- Any plaintext credential in output, logs, artifacts, screenshots, or report evidence: FAIL.

Temporary OAuth and installation tokens must remain protected and must be revoked or cleaned up by the live workflow. This report contains no credential values, fingerprints, or effective-generation values.

## Remaining CI Evidence

Before validation is complete, the full PR stack must pass:

- backend Ruff, Pyright, and Pytest for the final validation diff;
- credential-free deterministic E2E, including the new Admin System Settings lifecycle;
- Web Surface E2E, including Admin System Settings navigation and redacted secret controls;
- Admin/Main Web and generated-client checks;
- Helm render checks; and
- documentation frontmatter/index validation.

Living-spec promotion and the design `implemented` date must occur only after this required CI evidence is green.
