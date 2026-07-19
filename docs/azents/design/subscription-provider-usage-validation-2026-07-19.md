---
title: "Subscription Provider Usage Validation Report"
created: 2026-07-19
tags: [backend, frontend, api, llm, oauth, billing, security, testing, testenv]
---

# Subscription Provider Usage Validation Report

## Scope

This report validates the implementation described by
[`subscription-provider-usage.md`](./subscription-provider-usage.md), ADR-0168, and the phased
delivery requirements recorded during implementation.

The validation covers:

- integration-scoped live subscription usage for `chatgpt_oauth` and `xai_oauth`;
- normalized operational limits and write-permission-gated financial details;
- provider adapter request paths, required headers, failure classification, and safe logging;
- ChatGPT single-refresh retry and xAI settings, redirect, billing, and auto top-up behavior;
- disabled, unavailable, stale-refresh, external-link, and multi-card isolation behavior;
- card-local frontend state projection, accessibility, localization, responsive presentation, and error containment;
- deterministic provider fixture readiness and sanitized request evidence;
- implementation drift against ADR-0168, the approved design, implementation plan, and current living specs.

No live provider credential or live provider request is part of this validation.

## Environment

- Date: 2026-07-19
- Worktree branch: `feature/subscription-usage-06-validation`
- Base commit: `c860a378` (`feature/subscription-usage-05-frontend`)
- Operating system: Linux 6.8.0 x86_64
- Python: 3.14.6
- Node.js: 24.18.0
- pnpm: 11.1.0
- Docker CLI: unavailable
- Docker Unix socket: unavailable (`/var/run/docker.sock` is absent)
- Live provider credentials: not requested and not used

## Validation Results

### Backend contract and runtime

The focused backend quality and test chain passed:

```console
cd python/apps/azents
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest \
  src/azents/core/chatgpt_oauth_test.py \
  src/azents/services/chatgpt_oauth \
  src/azents/services/subscription_usage \
  src/azents/api/public/llm_provider_integration/v1 -q
```

Results:

- Ruff lint: passed.
- Ruff format: passed; 977 files unchanged in the final run.
- Pyright: zero errors and zero warnings.
- Focused Pytest: 119 passed, 7 environment-dependent skips, 3 warnings.

The backend checks include adapter contract tests, normalized response tests, permission projection,
disabled and unsupported outcomes, OAuth refresh lifecycle behavior, and the ChatGPT token endpoint
resolver introduced for deterministic E2E injection.

The resolver tests prove that production continues to use `https://auth.openai.com/oauth/token` when
no override is configured and that `AZ_CHATGPT_OAUTH_TOKEN_URL` affects only the configured process.
Every `ChatGPTOAuthClient` construction site passes the required token URL explicitly.

### Deterministic provider proxy

The direct credential-free proxy contract suite passed:

```console
cd testenv/azents/e2e
uv run pytest -vv src/tests/test_subscription_usage_proxy.py
```

Result: 13 passed, 2 dependency deprecation warnings.

The suite verified:

- ChatGPT production-shaped `/backend-api/wham/usage` responses;
- xAI `/v1/settings`, `/v1/billing?format=credits`, and `/v1/auto-topup-rule` responses;
- required provider header presence without recording header values;
- ChatGPT normal, exhausted, 401-refresh-success, 429, 503, malformed, transport-close, and success-then-failure scenarios;
- xAI normal, trusted redirect, rejected redirect, settings failure, billing 403, billing 503, malformed, and transport-close scenarios;
- deterministic request sequence reset;
- transport-close behavior producing a real client connection error;
- a journal schema limited to `scenario`, `path`, `sequence`, `status`, and required-header booleans.

The test helper resets only the direct ephemeral server's subscription journal and sequence state at
startup, making each direct contract test independent of pytest ordering. The product E2E proxy still
retains its shared journal until the product test clears it through the fixture's HTTP endpoint.

### Testenv static verification

```console
cd testenv/azents/e2e
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Results:

- Ruff lint: passed.
- Ruff format: 49 files already formatted.
- Pyright: zero errors and zero warnings.

### Public API deterministic E2E

The public API E2E was invoked exactly as planned:

```console
cd testenv/azents/e2e
uv run pytest -vv src/tests/azents/public/test_subscription_usage.py
```

Pytest collected 15 cases. All 15 were blocked during the session-scoped Testcontainers network setup
before any product assertion ran. The Docker client could not connect because the Docker Unix socket is
absent, ending with:

```text
docker.errors.DockerException: Error while fetching server API version:
('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))
```

This is a local environment prerequisite failure, not a product assertion failure.

Required pull-request CI run `29691843411` subsequently executed the full deterministic lane with Docker.
The lane completed with 205 passed, 11 skipped, 10 deselected, and 2 dependency deprecation warnings in
371.75 seconds. All 17 cases from `test_subscription_usage.py`, including the product API, refresh,
isolation, serialization, journal, and structured server-log assertions, passed.

The API cases cover:

- Owner and Member operational/financial projection;
- exhausted ChatGPT limits without remaining-request synthesis;
- exactly one ChatGPT refresh and one usage retry after 401;
- typed ChatGPT transport, rate-limit, service, and malformed outcomes;
- xAI billing, plan, prepaid, PAYG, and auto-top-up normalization;
- trusted redirect short-circuit and rejected redirect fail-closed behavior;
- settings best-effort enrichment and required billing failure behavior;
- disabled request suppression, two-integration isolation, and integration enabled-state preservation;
- sanitized serialized responses, proxy journals, and server logs.

All integrations, workspaces, users, invitations, and memberships are created through product APIs. The
suite contains no direct database write.

### Browser and web-surface deterministic E2E

The real-browser lane was invoked separately:

```console
cd testenv/azents/e2e
uv run pytest -vv -m "web_surface" \
  src/tests/azents/public/test_subscription_usage_web.py
```

Pytest collected the single browser scenario. It was blocked at the same session-scoped Testcontainers
network setup because Docker is unavailable, before the browser, gateway, or worktree-built Main Web
could start. No browser assertion ran locally.

Required pull-request CI run `29691843411` executed the Web Surface lane with Docker and the real browser.
The lane completed with 3 passed, 223 deselected, and 3 dependency warnings in 368.64 seconds. The target
`test_subscription_usage_cards_are_live_local_safe_and_responsive` scenario passed.

The browser scenario covers:

- independently loaded ChatGPT and xAI card usage regions;
- management controls remaining available during usage failure;
- Owner financial details collapsed by default and disclosed on demand;
- healthy-card visibility while another card is unavailable;
- last-successful snapshot retention and stale warning after manual refresh failure;
- disabled guidance with no provider journal entry;
- trusted xAI external URL attributes and rejected redirect suppression;
- a 390-pixel viewport with no document or card horizontal overflow and reachable actions.

Provider fixture outcomes cannot induce an unexpected tRPC serialization failure or React render
exception because expected provider failures are normalized before those boundaries. Those two
containment paths are therefore covered by the Phase 3 projection tests, static Storybook fixtures, and
the card-local error-boundary implementation rather than a test-only production hook.

### Frontend regression and presentation

The complete TypeScript verification chain passed with exit code zero:

```console
cd typescript
pnpm run format
pnpm run lint
pnpm run typecheck
pnpm --filter=@azents/web run test
pnpm exec turbo run build --filter=@azents/web
pnpm exec turbo run build-storybook --filter=@azents/web
```

Results:

- workspace format, lint, and type checking: passed;
- azents-web tests: 40 passed;
- production web build: passed;
- Storybook build: passed;
- only the existing non-failing large-chunk Storybook warning was emitted.

The frontend coverage includes the closed usage state projection, eligible-provider filtering, disabled
request suppression, loading, available, external, unavailable, stale-error retention, financial
disclosure, threshold presentation, narrow layout, and localized copy across English, French, Japanese,
and Korean.

### Generated clients and final static checks

```console
git diff --check
git diff --exit-code -- \
  python/libs/azents-public-client \
  python/libs/azents-admin-client \
  typescript/packages/azents-public-client/src/generated \
  typescript/packages/azents-admin-client/src/generated
```

Results:

- `git diff --check`: passed.
- Generated Python and TypeScript clients: no Phase 4 diff.
- Phase 4 adds no public API schema and does not manually edit generated artifacts.

## Safe Fixture and Journal Evidence

The deterministic fixture uses fixed provider account identifiers only as provider-boundary scenario
selectors. The selectors and test credentials are never copied into journal entries. Journal entries
contain only:

- a normalized closed scenario label such as `chatgpt_normal` or `xai_transport`;
- the URL path without query values;
- a path-scoped sequence number;
- an integer status or the safe `transport_close` classification;
- booleans recording whether required headers were present.

Direct proxy assertions reject token values, refresh-token values, provider account identifiers, emails,
provider financial source values, provider plan values, trusted and rejected redirect values, and header
values.
The journal never records provider request bodies or response payloads.

Product API tests additionally reject deterministic credentials and provider account metadata from normalized API
responses and subscription-usage service logs. Required Docker-backed CI executed and passed those
assertions.

## Behavior Validation Matrix

| Behavior | Static/unit evidence | Product API E2E | Browser E2E | Result |
| --- | --- | --- | --- | --- |
| ChatGPT normal and exhausted limits | Backend and proxy passed | Passed in deterministic CI | Normal and stale cards passed | Passed |
| ChatGPT 401 refresh and one retry | Backend and proxy passed | Passed in deterministic CI | Not separately rendered | Passed |
| ChatGPT 429/503/malformed/transport | Backend and proxy passed | Passed in deterministic CI | Malformed card passed | Passed |
| xAI billing and auto top-up | Backend and proxy passed | Passed in deterministic CI | Financial disclosure passed | Passed |
| xAI trusted/rejected redirect | Backend and proxy passed | Passed in deterministic CI | Link safety passed | Passed |
| Reader/writer financial split | Route/service tests passed | Passed in deterministic CI | Owner disclosure passed | Passed |
| Disabled provider suppression | Service/query tests passed | Passed in deterministic CI | Passed | Passed |
| Two-card failure isolation | Query/projection tests passed | Passed in deterministic CI | Passed | Passed |
| Failed-refresh stale snapshot | Frontend tests and Storybook passed | Fixture passed | Passed in Web Surface CI | Passed |
| Narrow responsive layout | Storybook build passed | Not applicable | Passed at 390 pixels | Passed |
| Secret-safe journal and service logs | Proxy assertions passed | Passed in deterministic CI | Journal assertions passed | Passed |

## ADR-0168 and Approved Design Comparison

| Decision | Implemented behavior | Validation | Drift |
| --- | --- | --- | --- |
| D1 — Integration-scoped live snapshot | One child endpoint reads one integration and returns `fetched_at` without attributing usage to Azents | Backend tests and deterministic API E2E passed | None |
| D2 — OAuth subscription providers only | Only `chatgpt_oauth` and `xai_oauth` are eligible; API-key providers do not request usage | Backend/frontend tests passed | None |
| D3 — Adapter-owned provider contracts | Paths, headers, parsing, compatibility identity, and failures remain in provider adapters | Adapter and proxy suites passed | None |
| D4 — Read-through and non-durable | No usage table, history, scheduler, polling, or server cache; frontend keeps only card-local query and last-successful snapshot state | Code review and frontend tests passed | None |
| D5 — Operational/financial permission split | Readers receive quota state; writers additionally receive financial details | Service/route tests and product E2E passed | None |
| D6 — Card-local canonical UI | Usage renders inside each eligible LLM Settings card with manual refresh and freshness | Frontend tests/build/Storybook and browser E2E passed | None |
| D7 — Typed expected outcomes and isolation | Expected provider outcomes normalize to `available`, `external`, or `unavailable`; unexpected UI defects are card-contained | Backend/frontend and isolation E2E passed | None |
| D8 — Provider-specific control planes | ChatGPT uses backend `/wham/usage`; xAI uses CLI proxy settings before billing; redirects require trusted HTTPS domains | Adapter and proxy suites passed | None |
| D9 — No remaining-request inference | UI and API expose provider-reported used percentages and resets only | Backend/frontend tests passed | None |

The implementation follows the approved non-goals: no API-key billing, AgentRun token accounting,
persistence, history, charts, alerts, global header indicator, chat warning, automatic failover, or provider
billing mutation was added.

## Implementation Plan Invariant Comparison

| Invariant | Evidence | Result |
| --- | --- | --- |
| One integration read owns one endpoint request and one card-local query | Route and frontend container structure reviewed; tests passed | Match |
| Usage never gates integration list or management controls | Independent query/container structure and browser assertion passed | Match |
| One integration failure does not invalidate another | Frontend projection and API/browser isolation tests passed | Match |
| Provider failures never expose raw payloads or exception serialization | Adapter tests and safe journal assertions passed | Match |
| Initial failure is local; failed refresh preserves stale success | Frontend tests, Storybook, and browser scenario passed | Match |
| Usage failures do not change entitlement or enabled state | Service/adapter tests and xAI 403 product assertion passed | Match |
| Existing OAuth refresh lifecycle remains authoritative | ChatGPT/xAI runtime tests passed; deterministic token endpoints preserve production defaults | Match |
| No credentials, provider account identifiers, provider bodies, redirects, or unauthorized financial values enter logs | Unit/proxy and product structured-log assertions passed | Match |

## Current Living Spec Comparison Before Promotion

| Spec | Current coverage | Implemented behavior missing from current spec | Promotion action |
| --- | --- | --- | --- |
| `docs/azents/spec/flow/chatgpt-oauth.md` | Device flow, integration credentials, catalog, runtime refresh, execution | Live `/wham/usage` read, normalized windows, financial projection, usage 401 forced refresh/retry, endpoint override behavior, and card-local UI states | Update spec, code paths, verification date, and version |
| `docs/azents/spec/flow/xai-oauth.md` | Device flow, credentials, five-minute refresh, inference execution | CLI-proxy settings/billing/auto-top-up usage flow, trusted redirect control, permission projection, typed failures, and card-local UI states | Update spec, code paths, verification date, and version |

The living-spec drift is expected at this stack boundary because the implementation plan reserves current
behavior promotion for PR 7/8. No contradictory current spec statement was found. The next PR must run
`/spec-review`, update both OAuth flow specs, and mark the approved design implemented only after this
validation PR is recorded.

## Validation Findings Fixed

1. Deterministic ChatGPT usage E2E required token refresh to remain inside the provider proxy. A
   non-secret `AZ_CHATGPT_OAUTH_TOKEN_URL` resolver and explicit `ChatGPTOAuthClient` dependency were
   added. The production default is unchanged and unit-tested.
2. The direct ephemeral proxy contract helper depended on default test ordering because the proxy journal
   is intentionally class-level. The helper now resets subscription journal and sequence state before
   each ephemeral server starts, without changing product E2E journal behavior.
3. Transport-close behavior was verified directly rather than assumed. Both ChatGPT and xAI scenarios
   produce real connection failures and normalize through adapter transport handling.
4. The initial deterministic CI run found that the generated Python client's `to_json()` helper does
   not serialize `datetime` fields in subscription-usage models. The E2E helper now unwraps the generated
   model with `to_dict()` and applies Pydantic JSON-mode conversion without modifying generated code.
5. The initial browser CI run found that Mantine attaches the toggle label to a visually hidden native
   input. The browser assertion now verifies that the input exists and is enabled instead of requiring
   the native input itself to be visually displayed.
6. The next browser CI run found that a provider 503 becomes a typed `unavailable` response rather than
   a React Query transport error. That successful HTTP response replaced the prior query data, so the
   stale-warning projection could not retain the last successful snapshot. The card container now keeps
   the latest `available` or `external` snapshot in workspace-and-integration-keyed TanStack Query memory,
   with a mounted-card ref retaining the same value for the active card lifecycle. The state projector
   uses that snapshot when a later typed `unavailable` response arrives. A regression test covers the
   exact success-then-unavailable transition.
7. The following deterministic CI run exposed three validation assertion defects rather than provider
   adapter failures. The ChatGPT financial reset expectation now matches the fixture's UTC epoch, the
   refresh journal expects the second request to the same usage path to have sequence `2`, and the
   server-log safety assertion filters structured subscription-usage records before rejecting source
   identifiers so unrelated email-service logs do not produce false positives. Static checks, two pure
   helper tests, and all 13 direct proxy tests passed locally. Docker-backed product-path confirmation
   was then completed by the final CI run recorded below.
8. The next deterministic run passed those three boundaries and exposed an overbroad exhausted-usage
   assertion. The no-inference invariant applies to normalized usage-limit fields, while the provider's
   financial `spend_remaining_percent` value is intentionally preserved for writers. The assertion now
   rejects remaining-value fields only inside normalized usage limits.

## Required CI Evidence

The repository's Docker-backed credential-free lanes passed on validation head `08433ab6` in CI run
`29691843411`:

```console
uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src
uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src
```

Results:

- deterministic E2E job `88205869226`: 205 passed, 11 skipped, 10 deselected, and 2 dependency
  deprecation warnings in 371.75 seconds;
- Web Surface E2E job `88205869230`: 3 passed, 223 deselected, and 3 dependency warnings in 368.64
  seconds;
- all 17 subscription-usage API/helper cases passed in the deterministic lane;
- the real-browser subscription usage scenario passed, including provider journals, card isolation,
  stale-state retention, safe external links, management-control availability, and 390-pixel overflow
  assertions;
- the aggregate `ci-python-e2e` gate and all other required Python, TypeScript, Docker, Helm, and
  pre-commit checks passed.

## Optional Live Verification

Optional live-provider verification was not requested and was not run. It is not required for this
feature because the accepted private-provider contracts are represented by source-grounded deterministic
fixtures and isolated adapters. Live credentials, provider payload capture, and provider account metadata
must not be added to the validation report or fixture journal.
