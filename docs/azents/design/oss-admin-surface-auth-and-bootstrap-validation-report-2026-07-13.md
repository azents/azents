---
title: "OSS Admin Surface Authentication and Bootstrap Validation Report"
created: 2026-07-13
updated: 2026-07-13
tags: [admin, auth, bootstrap, e2e, testenv, validation]
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

The local agent runtime did not expose a Docker socket, so container-backed execution could not start locally. Collection, Ruff, and Pyright validation completed locally. The deterministic container matrix remains a required CI gate; its run URL and final outcome must be added before the design is marked implemented.

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
- safe deletion and role cascade when another administrator remains.

The fixture update also shares one JWT signing key across Public API, Admin API, worker, and runtime-control processes. Existing Admin API E2E clients now authenticate as the bootstrapped administrator. Raw Admin API support requests forward that bearer token instead of relying on the removed no-auth mode.

## Local Results

| Command | Result |
|---|---|
| `uv run ruff format ...` | Passed; changed files formatted |
| `uv run ruff check ...` | Passed |
| `uv run pyright` | Passed with 0 errors |
| `uv run pytest --collect-only -q -m 'not live_external' ./src` | Passed; 167 selected and 2 deselected tests collected |
| `uv run pytest -vv -s src/tests/azents/admin/test_00_system_admin.py` | Infrastructure unavailable before test setup: Docker socket absent |

The Docker failure occurred while `testcontainers` initialized its network and did not execute product code. It is an environment limitation, not a skipped or passing product result.

## CI Completion Requirements

Before spec promotion and setting the design `implemented` date:

1. Run the deterministic E2E suite in a Docker-enabled CI worker.
2. Confirm both new system-admin tests and all existing Admin/Public tests pass.
3. Confirm failure output and retained logs contain no setup token, refresh token, password, or bearer-token value.
4. Record the exact commit SHA, CI run URL, and final test counts in this report.
5. Treat any product or fixture failure as blocking; do not convert it to a skip.

## Remaining Browser Matrix

Main Web link visibility, Admin Web password login/logout, self-revocation navigation, and dedicated-host/path-prefix browser routing remain covered by the PR 6 TypeScript unit/build and Helm render contracts but still require real dual-web browser execution. That browser evidence is blocking for final spec promotion and must be recorded with the CI completion update.
