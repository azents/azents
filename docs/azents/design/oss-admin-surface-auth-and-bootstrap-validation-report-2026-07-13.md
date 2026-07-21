---
title: "OSS Admin Surface Authentication and Bootstrap Validation Report"
created: 2026-07-13
updated: 2026-07-13
tags: [admin, auth, bootstrap, e2e, testenv, validation]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/oss-admin-surface-auth-and-bootstrap-validation-report-2026-07-13.md"
---

# OSS Admin Surface Authentication and Bootstrap Validation Report

## Scope

This report records validation for the OSS Admin authentication and bootstrap stack. The deterministic E2E coverage uses the real Public API and Admin API processes with shared PostgreSQL, Redis, and object-storage dependencies. Product state is created only through bootstrap, Public API, Admin API, and operator CLI paths.

No database writes are performed by the tests.

## Environment

- Date: 2026-07-13
- Python: 3.14.6
- E2E project: `testenv/azents/e2e`
- Server artifact: current-worktree `azents.Dockerfile` image in Docker-enabled execution
- External credentials: not required
- Setup token and JWT values: generated in memory and never written to retained output

The local agent runtime did not expose a Docker socket, so container-backed execution could not start locally. Collection, Ruff, and Pyright validation completed locally. Docker-backed API and Chromium execution completed in GitHub Actions against commit `31b1530a960416eaf94afd147befc4d2874061f1`.

## Automated Coverage

`test_00_system_admin.py` and the shared E2E fixtures cover:

- configured-token bootstrap availability;
- invalid setup-token rejection without token disclosure;
- two concurrent bootstrap attempts with exactly one success;
- bootstrap becoming unavailable after success;
- first administrator session issuance;
- bootstrap creating no Workspace;
- configured setup token absent from Public and Admin server logs;
- ordinary-user denial at System and Debug Admin API boundaries;
- live role grant and revoke taking effect for an existing access token;
- Public API self-role projection before and after revoke;
- exact-email operator CLI promotion and invalid-email failure;
- final-system-admin role revoke rejection;
- final-system-admin User deletion rejection;
- safe deletion and role cascade when another administrator remains;
- Main Web password login and role-gated Admin link visibility in a real Chromium session;
- Admin Web password login and logout with isolated secure HTTP-only cookies;
- self-role revocation through the Users UI followed by immediate sign-out and API denial;
- dedicated-host and gateway path-prefix routing through a TLS reverse proxy.

The fixture update also shares one JWT signing key across Public API, Admin API, worker, and runtime-control processes. Existing Admin API E2E clients now authenticate as the bootstrapped administrator. Raw Admin API support requests forward that bearer token instead of relying on the removed no-auth mode. Browser E2E builds both web images from the tested worktree and runs Chromium on the same isolated container network.

## Local Results

| Command | Result |
|---|---|
| `uv run ruff format ...` | Passed; changed files formatted |
| `uv run ruff check ...` | Passed |
| `uv run pyright` | Passed with 0 errors |
| `uv run pytest --collect-only -q -m 'not live_external' ./src` | Passed; 168 selected and 2 deselected tests collected |
| `uv run pytest -vv -s src/tests/azents/admin/test_00_system_admin.py` | Infrastructure unavailable before test setup: Docker socket absent |

The Docker failure occurred while `testcontainers` initialized its network and did not execute product code. It is an environment limitation, not a skipped or passing product result.

## CI Results

- Commit: `31b1530a960416eaf94afd147befc4d2874061f1`
- Run: [GitHub Actions 29258423170](https://github.com/azents/azents/actions/runs/29258423170)
- Command: `uv run pytest -vv -m "not live_external and not runtime_provider" ./src`
- Result: 152 passed, 11 skipped, 7 deselected in 463.40 seconds

The Docker-enabled run passed the new system-administrator API and browser tests together with the existing deterministic Admin and Public API suite. The skipped tests were existing substrate-conditional cases; the requested Admin coverage executed rather than being converted to a skip. Retained job output contained no setup token, refresh token, password, or bearer-token value, and the E2E assertions also verified that the configured setup token was absent from Public and Admin server logs.

## Browser Matrix

`test_01_admin_web.py` now exercises Main Web and Admin Web through a real headless Chromium session. The browser profile uses TLS for production cookie behavior, verifies the Main Web role-gated link, checks Admin Web login/logout and cookie paths, performs self-revocation through the Users UI, and runs both dedicated-host and path-prefix gateway topologies.

The browser journey passed in the Docker-enabled CI run recorded above, including both dedicated-host and path-prefix gateway topologies.
