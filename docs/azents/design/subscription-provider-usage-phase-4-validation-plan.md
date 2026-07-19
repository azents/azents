---
title: "Subscription Provider Usage Phase 4 Validation Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [plan, validation, e2e, testenv, frontend, backend, llm, oauth, security]
---

# Subscription Provider Usage Phase 4 Validation Plan

## Phase Objective

Validate the completed ChatGPT OAuth, xAI OAuth, and integration-card stack through credential-free provider behavior, public API paths, and real-browser Workspace LLM Settings behavior. Add only the fixture and endpoint-injection support required for deterministic validation. Record exact evidence and implementation/spec drift before living spec promotion.

This phase is stacked on the frontend usage-card PR. The root agent owns the plan, implementation, direct review, validation, fixes, evidence report, commit, and PR creation without delegated implementation.

## Deterministic Provider Boundary

Extend the existing E2E provider proxy under `testenv/azents/e2e/src/support/` rather than adding a second overlapping container. The proxy will expose the production-shaped ChatGPT and xAI usage paths plus OAuth refresh endpoints used by the server container.

Scenario selection is credential-free and integration-scoped:

- tests create OAuth integrations through the public product API;
- fixed test-only account identifiers select a closed fixture scenario inside the proxy;
- journals store only the normalized scenario name, request path, response status, request sequence, and required-header presence booleans;
- journals never store header values, tokens, account identifiers, emails, request bodies, provider payloads, redirect query values, or financial values;
- clearing the journal also resets sequence-dependent scenarios.

Required ChatGPT fixture scenarios:

- normal Owner snapshot with two primary windows and financial details;
- exhausted snapshot at 100 percent;
- first usage 401 followed by deterministic token refresh and success;
- transport close, 429, 503, and malformed payload outcomes;
- success followed by 503 for stale client-snapshot validation.

Required xAI fixture scenarios:

- normal billing with settings plan metadata and optional auto top-up;
- trusted provider-managed redirect that short-circuits billing;
- invalid redirect that never reaches billing;
- billing 403;
- settings failure with billing success;
- transport close, 503, and malformed billing outcomes.

## Product Test Dependency

Keep production endpoint constants unchanged. Configure the E2E server container with explicit non-secret overrides:

- `AZ_CHATGPT_USAGE_BASE_URL`;
- `AZ_XAI_USAGE_BASE_URL`;
- existing `AZ_XAI_OAUTH_TOKEN_URL`;
- a new `AZ_CHATGPT_OAUTH_TOKEN_URL` resolver used by ChatGPT token exchange and runtime refresh.

The ChatGPT OAuth client must receive the resolved token URL through normal dependency injection or an explicit constructor dependency. Unit tests must prove the default remains the production token endpoint and the override affects only the configured process.

## API E2E Coverage

Add focused public E2E coverage that creates workspaces, users, invitations, and integrations only through product APIs.

Assertions:

- Owner ChatGPT normal returns two operational windows and financial details.
- Member ChatGPT normal returns identical operational windows with `financial_details` absent.
- ChatGPT exhausted returns 100 percent without synthesizing remaining-request counts.
- ChatGPT 401 performs exactly one refresh and one retry; the journal contains only safe classifications.
- ChatGPT 429, 503, transport close, and malformed responses return the expected typed unavailable reasons.
- xAI normal returns one normalized period and Owner-only prepaid, PAYG, and auto-top-up fields.
- xAI trusted redirect returns `external`, omits billing details, and records no billing request.
- xAI invalid redirect returns `invalid_provider_response`, exposes no URL, and records no billing request.
- xAI settings failure still returns available billing.
- xAI billing 403 returns entitlement unavailable while integration enabled state remains unchanged.
- Disabled eligible integrations return the disabled outcome and issue no provider request.
- Two eligible integrations can be read independently when one fixture scenario is broken.
- Serialized API responses, proxy journals, and sanitized server logs contain none of the deterministic token, refresh-token, account-id, or financial fixture source values beyond fields explicitly authorized in the API response.

## Browser E2E Coverage

Add `web_surface` coverage using the real worktree-built Main Web, Selenium browser, and API-created workspace state. Authenticate through the normal Main Web login flow.

Required browser assertions:

- ChatGPT and xAI cards render independent live usage regions while card enable/edit/delete controls remain present.
- Owner financial details are collapsed by default and become visible only after disclosure.
- A broken integration renders only its usage unavailable state while a healthy card remains visible and refreshable.
- A success-then-failure scenario preserves previous values and renders the stale warning after manual refresh.
- A disabled integration renders explicit disabled guidance and produces no journal entry.
- Trusted xAI external usage renders a safe new-tab link; invalid redirect renders no usage link.
- At a narrow viewport, the document and integration-card region have no horizontal overflow and refresh/management actions remain reachable.

Unexpected tRPC transport failure and component-render failure cannot be produced by provider fixture responses because the adapters intentionally normalize provider failures. Validate those frontend containment paths through the Phase 3 narrow error boundary implementation and static Storybook fixtures, and record this boundary explicitly in the evidence matrix rather than adding production test hooks.

## Validation Report

Create `docs/azents/design/subscription-provider-usage-validation-2026-07-19.md` containing:

- environment and Docker availability;
- exact commands and results;
- fixture readiness and safe-journal evidence;
- API, browser, backend, generated-client, frontend, Storybook, and static verification results;
- failures discovered and fixes applied;
- a strict row-by-row comparison against ADR-0168, the approved design, implementation plan, and current living specs;
- required deterministic results separately from optional live-provider verification.

Live credentials are not required and no live provider request is made in this phase.

## Quality Commands

Backend and focused tests:

```bash
cd python/apps/azents
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest src/azents/services/chatgpt_oauth src/azents/services/subscription_usage src/azents/api/public/llm_provider_integration/v1 -q
```

Testenv and E2E:

```bash
cd testenv/azents/e2e
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest -vv src/tests/azents/public/test_subscription_usage.py
uv run pytest -vv -m "web_surface" src/tests/azents/public/test_subscription_usage_web.py
```

Frontend regression:

```bash
cd typescript
pnpm run format
pnpm run lint
pnpm run typecheck
pnpm --filter=@azents/web run test
pnpm exec turbo run build --filter=@azents/web
pnpm exec turbo run build-storybook --filter=@azents/web
```

Final checks:

```bash
git diff --check
git status --short
```

## Explicit Non-Goals

- live-provider credentials or smoke requests;
- direct database setup or cleanup;
- production endpoint default changes;
- provider payload capture;
- durable usage persistence, polling, history, charts, alerts, or chat warnings;
- new public API fields or generated-client edits;
- test-only response branches in product routes, services, or frontend components;
- living spec promotion or cleanup-plan deletion before the next stack phases.

## Completion Requirements

Before opening the validation PR, confirm deterministic fixtures are closed and secret-safe, integrations are created only through product APIs, API and browser assertions cover the release-blocking behavior available through provider boundaries, generated clients remain unchanged, validation limitations are explicit, and the evidence report is complete enough for the following `/spec-review` phase.
