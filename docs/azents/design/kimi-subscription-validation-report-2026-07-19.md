---
title: "Kimi Subscription Provider Validation Report"
created: 2026-07-19
tags: [backend, frontend, api, testing, documentation, security]
---

# Kimi Subscription Provider Validation Report

## Scope

This report records deterministic local verification for the Kimi subscription provider through stacked PR phases 3–5. The implementation adds the experimental `kimi_oauth` provider, encrypted device authorization, integration-scoped model discovery, LiteLLM Moonshot routing, token refresh, normalized subscription usage, generated public clients, and workspace UI support.

No live Kimi credential or subscription was supplied. Deterministic tests use fake tokens, device identifiers, and mocked provider responses and never call Kimi.

## Test Strategy

Backend contract and service tests exercise the public API boundary, device-session ownership and redaction, provider response classification, token refresh, model projection, runtime mapping, and usage normalization. PostgreSQL tests cover encrypted persistence and refresh/reconnect serialization through `SELECT ... FOR UPDATE`. Frontend Node tests cover subscription-usage eligibility and projection, while colocated Storybook interactions cover idle, pending, connected, reconnect-required, expired, and read-only device-card states.

The local environment has no Docker socket. Tests requiring PostgreSQL, Redis, or other testcontainers were collected but skipped. Docker-enabled CI is therefore the required execution environment for database repository tests and the independent-session row-lock regression.

## Executed Verification

### Backend

Commands:

- `cd python/apps/azents && uv run ruff check --fix .`
- `cd python/apps/azents && uv run ruff format .`
- `cd python/apps/azents && uv run pyright`
- `cd python/apps/azents && uv run pytest`

Results:

- Ruff check and format: PASS; 1,004 files unchanged after formatting.
- Pyright: PASS, 0 errors.
- Pytest: PASS, 1,724 passed, 417 skipped, 5 warnings.
- The 417 skips are environment skips caused by unavailable Docker-backed fixtures. Fourteen Kimi runtime tests were collected, including stale success/failure, reconnect, two-success, two-failure, config-only recovery, and independent-session row-lock cases.

### Database migration

Commands:

- `cd python/apps/azents && uv run alembic -c db-schemas/rdb/alembic.ini heads`
- `cd python/apps/azents && uv run alembic -c db-schemas/rdb/alembic.ini history -r 7e9b625b4c81:heads`

Results:

- Alembic: PASS, one head at `c0a51320cfdb`.
- The generated Kimi migration follows `7e9b625b4c81` and updates `db-schemas/rdb/revision`.

### API schemas and generated clients

Commands executed during implementation and validation:

- `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
- `cd python/libs/azents-public-client && make generate`
- `cd typescript && pnpm run generate --filter=@azents/public-client`
- `cd python/libs/azents-public-client && uv sync`
- Python import assertions for the package, `KimiOAuthV1Api`, `KimiOAuthDeviceStartResponse`, and `LLMProviderIntegrationCreateRequest`

Results:

- Public OpenAPI generation: PASS.
- Python public-client generation and imports: PASS.
- TypeScript public-client generation: PASS during lint, typecheck, and build task dependency execution.
- Generated files were not manually edited. OpenAPI Generator emits trailing whitespace in some generated Python examples; the repository explicitly excludes generated clients from structural pre-commit rewriting.

### Frontend

Commands:

- `cd typescript && pnpm run format`
- `cd typescript && pnpm run lint`
- `cd typescript && pnpm run typecheck`
- `cd typescript && pnpm --filter=@azents/web test`
- `cd typescript && pnpm run build`
- `cd typescript && pnpm --filter=@azents/web build-storybook --quiet`

Results:

- Prettier: PASS.
- ESLint: PASS.
- TypeScript: PASS.
- azents-web Node tests: PASS, 45 passed.
- Production build: PASS, 7 of 7 workspace tasks successful.
- Storybook production build: PASS; the Kimi device-card and integration-modal stories are included.

## Deterministic Coverage

| User behavior | Result | Evidence |
|---|---|---|
| Discover provider | PASS | Provider capability route tests and generated provider types |
| Start connection | PASS | OAuth client/service/route tests and idle Storybook interaction |
| Continue pending connection | PASS | Pending and slow-down service tests; hook adopts server interval |
| Complete connection | PASS | Service and route tests create/reconnect the integration and queue catalog sync |
| Cancel or leave pending flow | PASS | Cancel service tests, pending Storybook interaction, local expiry, and unmount cleanup |
| Recover rejected credential | PASS | Refresh-required and temporary-unavailable runtime tests and reconnect UI state |
| Preserve concurrent reconnect | PASS with CI execution required | Secrets-generation check and PostgreSQL row-lock regression; local DB test skipped without Docker |
| Select account-visible model | PASS | Kimi model-list projection tests, catalog provider tests, and picker provider support |
| Execute model | PASS | Resolver and LiteLLM mapping assertions for `moonshot/{model}`, Kimi base URL, token, and compatibility headers |
| Inspect usage | PASS | Kimi usage parsing, one-refresh retry, service dispatch, settings eligibility, and composer tests |
| Isolate sessions | PASS with CI execution required | Workspace/user ownership service and repository tests; DB-backed cases skipped locally |
| Redact credentials | PASS | Public response schema tests, generic CRUD boundary tests, and log/error sanitization assertions |

## Implementation-versus-design Review

| Design requirement | Result | Evidence |
|---|---|---|
| Dedicated OAuth subscription provider, separate from Moonshot API keys | PASS | `kimi_oauth` provider identity and generic CRUD exclusion |
| Device flow only | PASS | Start, poll, and cancel API; no callback route |
| Encrypted server-only device and token credentials | PASS | Credential cipher persistence and public response schemas |
| Account-visible integration catalog | PASS | Authenticated `/models` adapter and direct integration projection |
| Shared LiteLLM runtime through Moonshot aliases | PASS | Runtime model and credential mapping tests |
| Proactive refresh and reconnect recovery | PASS | Five-minute threshold, forced 401 retry, typed status transitions, and row-lock persistence |
| Subscription usage without billing control | PASS | Live `/usages` adapter and provider-neutral UI projection |
| Experimental entitlement-aware UI | PASS | Four locales and Storybook assertions |
| No Kimi Search/Fetch tools or Moonshot API-key provider | PASS | No such provider or toolkit surface added |

## External and Live Verification

Live verification was not executed because no operator-supplied Kimi subscription credential was available. It remains optional and must be explicitly enabled with an account approved for one prompt, model discovery, and usage reads.

A live smoke must verify:

1. Device authorization succeeds against the current Kimi OAuth endpoints.
2. `/models` and `/usages` accept the compatibility identity and encrypted stable device ID.
3. LiteLLM accepts the `moonshot/{model}` alias with the Kimi Code API base URL.
4. One short prompt succeeds without logging tokens, device code, device ID, authorization headers, or raw provider bodies.
5. Account entitlement and quota are sufficient and safe for the smoke operation.

Live failure does not authorize weakening redaction, ownership, typed failure, or provider-separation boundaries.

## Remaining CI Gate

Docker-enabled CI must execute the 417 locally skipped tests, especially the Kimi independent-session `FOR UPDATE` test and encrypted repository/service tests. Any failure in those checks blocks merge and must be fixed in the relevant stack branch.

## Conclusion

All locally executable backend, generated-client, frontend, build, Storybook, schema, and documentation checks pass. The implementation matches the accepted design boundaries. Database-backed concurrency and persistence coverage is present but requires Docker-enabled CI execution, and live Kimi verification remains an explicit optional prerequisite-gated smoke test.
