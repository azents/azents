---
title: "Subscription Provider Usage Phase 1 Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [plan, backend, api, llm, oauth, billing, security, testing]
---

# Subscription Provider Usage Phase 1 Plan

## Phase Objective

Implement the normalized subscription-usage backend contract and ChatGPT OAuth adapter described by
ADR-0168 and `subscription-provider-usage.md`. This phase includes public OpenAPI/client generation but
no frontend rendering and no xAI provider calls.

The phase must leave the existing integration list, model catalog, Agent execution, token accounting,
and connection management behavior unchanged. ChatGPT usage failures degrade only the child usage
endpoint response and never disable the integration unless the existing OAuth refresh lifecycle itself
proves the credential invalid.

## Implementation Ownership

- Root agent owns this plan, final integration, review-feedback fixes, and PR creation.
- One implementation subagent implements the plan.
- A different verification subagent reviews and validates the finished diff.
- The implementation subagent must not expand scope into xAI, frontend UI, E2E substrate, living specs,
  or design changes.

## Required Repository Rules

Before editing, read:

- repository, Python app, and documentation `AGENTS.md` files;
- `.claude/rules/conventions.md` and `.claude/rules/python-conventions.md`;
- applicable convention bodies for layered architecture, dependency injection, exhaustive unions,
  required new fields, narrow exception handling, structured logging, timezone-aware datetimes, and
  generated clients;
- `.claude/skills/openapi-client-gen/SKILL.md` before regenerating clients.

Do not edit generated clients manually. Do not add a migration. Do not update living specs in this
phase.

## Contract Decisions

### Endpoint

Add:

```text
GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/subscription-usage
```

Route behavior:

- require `Permissions.LLM_INTEGRATIONS_READ` or return 403;
- pass `include_financial_details=member.has_permission(LLM_INTEGRATIONS_WRITE)` to the service;
- map missing and cross-workspace integration failures to 404;
- map unsupported provider failure to 409;
- return a discriminated public response for controlled `available`, `external`, and `unavailable`
  outcomes;
- do not catch unexpected service exceptions or manufacture explicit 5xx responses.

The route must call only the subscription usage service. It must not call repositories or provider
clients directly.

### Public response models

Define response models under the existing integration API v1 data module. Use `type` as the Pydantic
and OpenAPI discriminator.

`SubscriptionUsageLimitResponse`:

- `id: str`;
- `label: str`;
- `used_percent: float`;
- `window_minutes: int | None`;
- `resets_at: datetime.datetime | None`;
- `primary: bool`.

`ChatGPTSubscriptionFinancialDetailsResponse` with `type="chatgpt"`:

- `has_credits: bool | None`;
- `unlimited: bool | None`;
- `balance: str | None`;
- `spend_limit: str | None`;
- `spend_used: str | None`;
- `spend_remaining_percent: float | None`;
- `spend_resets_at: datetime.datetime | None`;
- `reached_type: str | None`.

Define the xAI financial response shape from the accepted design now, even though Phase 2 is the first
producer. This keeps the public contract stable for the stacked implementation:

- `type="xai"`;
- nullable prepaid balance, PAYG cap/used, auto-top-up enabled, amount, and monthly maximum fields in
  integer cents.

`SubscriptionUsageAvailableResponse`:

- `type="available"`;
- `integration_id`;
- provider restricted to `chatgpt_oauth | xai_oauth`;
- timezone-aware `fetched_at`;
- nullable `plan_label`;
- non-empty normalized `limits`;
- nullable discriminated `financial_details`.

`SubscriptionUsageExternalResponse`:

- `type="external"`;
- integration/provider/fetched metadata;
- validated URL and fixed Azents message.

`SubscriptionUsageUnavailableResponse`:

- `type="unavailable"`;
- integration/provider/fetched metadata;
- reason enum from the design;
- fixed Azents message;
- `retryable`.

Never include provider error strings, response bodies, request identifiers, credentials, account id,
email, or arbitrary metadata in public models.

### Internal domain models

Create `azents/services/subscription_usage/` with defining modules imported directly rather than
re-exported through `__init__.py`.

Use frozen dataclasses or Pydantic models for:

- normalized limit window;
- ChatGPT and xAI financial details;
- available/external/unavailable outcomes;
- controlled service failures: not found, not in workspace, unsupported provider;
- ChatGPT adapter-only unauthorized marker used for the one-refresh retry.

Use a closed union and exhaustive `match`/`assert_never` dispatch. `External` exists in the common
contract but ChatGPT does not produce it in this phase.

Financial projection occurs in the subscription usage service before conversion to public response.
When `include_financial_details` is false, replace financial details with `None`; do not fetch a second
provider response and do not rely on frontend hiding.

## Service Layer

Add `SubscriptionUsageService` as a FastAPI-injectable service. It owns:

1. loading one integration with decrypted secrets through the established encrypted repository
   boundary;
2. workspace ownership verification;
3. provider and enabled-state eligibility;
4. OAuth freshness and controlled refresh-result mapping;
5. closed provider dispatch;
6. financial projection;
7. safe structured outcome logging.

Dependencies must be constructor-injected:

- `LLMProviderIntegrationRepository` built with `CredentialCipher`;
- `SessionManager[AsyncSession]`;
- an injected `httpx.AsyncClient` for usage HTTP calls;
- provider endpoint configuration/resolver with production defaults.

The service must not touch SQLAlchemy directly. The route must not construct its dependencies manually.

### Integration loading and eligibility

- `repository.get_by_id_with_secrets` returns not found when absent.
- Compare `workspace_id` before any provider call.
- API-key and other providers return the service unsupported-provider failure for route 409.
- `chatgpt_oauth` disabled integrations return controlled unavailable reason `disabled` without token
  freshness or HTTP calls.
- Phase 1 may return 409 for `xai_oauth` until its Phase 2 adapter is present; the common response schema
  already admits xAI outcomes.
- Invalid ChatGPT secret/config types return `invalid_provider_response` without exposing validation
  detail.
- Existing config status `refresh_required` or `disabled` maps to `reconnect_required` or `disabled`.
  `temporarily_unavailable` remains eligible for the shared freshness lifecycle.

### ChatGPT endpoint configuration

Add a dedicated ChatGPT usage base default:

```text
https://chatgpt.com/backend-api
```

The adapter calls `GET {base}/wham/usage` rather than appending to the `/codex` runtime base. Support an
explicit non-secret test/development base URL override needed by deterministic E2E, while retaining the
production default when absent. Do not reuse the Responses runtime URL.

## ChatGPT OAuth Refresh Refactor

Refactor `services/chatgpt_oauth/runtime.py` without changing existing runtime behavior.

Add public `refresh_runtime_tokens(...)` that forces exactly one refresh and owns the current refresh
request, persistence, permanent/transient failure status update, and concurrent-refresh recovery.

Change `ensure_runtime_tokens(...)` to:

- preserve the same provider/type/status validation;
- return unchanged integration outside the five-minute threshold;
- delegate the near-expiry case to `refresh_runtime_tokens`.

Do not duplicate `_persist_refresh_success` or `_persist_refresh_failure`. Existing engine/catalog
callers must continue using `ensure_runtime_tokens` unchanged.

The subscription usage service flow is:

1. call `ensure_runtime_tokens`;
2. if freshness fails, map permanent rejection to `reconnect_required` and transient provider failure to
   `temporarily_unavailable`;
3. call ChatGPT usage adapter with the fresh access token;
4. if and only if adapter returns its internal unauthorized marker, call `refresh_runtime_tokens` once;
5. retry usage exactly once with the returned integration;
6. if the retry is unauthorized, return `reconnect_required` without a third request;
7. other controlled provider outcomes are returned directly.

A usage 403 does not update connection status. Only token refresh persistence can do so.

## ChatGPT Adapter

Implement an adapter/client that owns the unstable wire contract and receives only:

- injected `httpx.AsyncClient`;
- usage base URL;
- validated `ChatGPTOAuthSecrets` and `ChatGPTOAuthConfig`.

### Request

```text
GET /wham/usage
Authorization: Bearer <access token>
ChatGPT-Account-Id: <account id>
originator: azents
User-Agent: azents/<version>
```

Reuse `build_chatgpt_oauth_headers` for client identity. Missing account id returns
`account_metadata_missing` before HTTP.

Do not log header values. Tests may assert header presence and expected test values through
`MockTransport`, but production logs and returned errors must never contain them.

### Controlled HTTP outcomes

- 401: internal unauthorized marker for service-level forced-refresh retry;
- 403: unavailable `permission_denied`, non-retryable;
- 429: unavailable `rate_limited`, retryable;
- 5xx and `httpx.TimeoutException`/transport failures: unavailable `temporarily_unavailable`, retryable;
- other non-success status: unavailable `unsupported_account`, non-retryable unless source evidence
  justifies a more specific design reason;
- invalid JSON or structurally malformed 2xx: unavailable `invalid_provider_response`, non-retryable.

Catch only expected `httpx` and parsing/validation exceptions. Unexpected programming exceptions must
propagate.

### Wire schema and normalization

Parse the source-backed payload keys:

- top-level `plan_type`;
- `rate_limit.primary_window` and optional `secondary_window`;
- `additional_rate_limits[*].limit_name`, `metered_feature`, and nested `rate_limit` windows;
- optional `credits.has_credits`, `credits.unlimited`, and provider-formatted `credits.balance`;
- optional `spend_control.reached` and `spend_control.individual_limit` fields `limit`, `used`,
  `remaining_percent`, and `reset_at`;
- optional `rate_limit_reached_type.type`;
- reset-credit summary fields only for parse compatibility, without public exposure or consumption API.

Window mapping:

- main primary id `primary`, label derived from duration such as `5-hour limit`, `primary=true`;
- main secondary id `secondary`, duration label such as `Weekly limit`, `primary=true`;
- additional window ids are stable sanitized provider identifiers and `primary=false`;
- convert `limit_window_seconds` to whole `window_minutes` when valid;
- convert Unix `reset_at` seconds to timezone-aware UTC datetime;
- ignore `reset_after_seconds` as redundant when `reset_at` exists;
- accept numeric integer/float percentages, clamp presentation values to `[0, 100]`, and reject booleans,
  non-finite values, missing required window percentage, and invalid structures;
- an available response requires at least one valid main or additional window;
- preserve provider-formatted string balances/limits without labeling them as currency.

Fixed user-facing messages and labels must be English in backend response defaults. Frontend localization
comes later.

## Logging and Observability

Log one safe completion event per usage read with a static message and `extra={}` fields only:

- provider enum;
- integration id;
- operation `subscription_usage_read`;
- outcome category;
- safe HTTP status when present;
- adapter contract fingerprint/version;
- duration in milliseconds.

Malformed provider responses should be error-level observations through normal logger integration.
Controlled availability failures may use warning/info according to current project logging patterns.
Do not log and re-raise the same exception. Never log provider body, exception text containing URLs or
headers, token values, account/email, financial values, or redirect values.

## Public Conversion and OpenAPI

Add explicit `convert_from` methods from internal outcomes to public response models. Conversion must be
exhaustive and must preserve timezone-aware datetimes.

After route/schema tests pass, run the OpenAPI generation workflow exactly:

```bash
cd python/apps/azents
uv run python src/cli/dump_openapi.py

cd ../../libs/azents-public-client
make generate

cd ../../../typescript
pnpm run generate --filter=@azents/public-client
```

Inspect generated diffs for the new endpoint and discriminated response types. Do not edit generated
output.

## Required Tests

### ChatGPT runtime tests

- fresh token is returned without refresh;
- token within five minutes delegates to forced refresh;
- direct forced refresh refreshes even a currently fresh token;
- success persists rotated credentials and connected status;
- rejected refresh marks refresh required;
- transient refresh marks temporarily unavailable;
- concurrent refresh recovery returns the latest credential;
- existing non-ChatGPT and invalid integration behavior remains unchanged.

### ChatGPT adapter tests

Use `httpx.MockTransport` with exact request assertions.

- primary plus secondary normalization;
- additional rate limit normalization;
- plan and financial mapping;
- missing optional financial fields;
- percentage clamping and duration/reset conversion;
- missing account metadata makes zero HTTP calls;
- 401 marker;
- 403, 429, 5xx, timeout, and transport classification;
- malformed JSON, non-object body, missing rate limit, empty windows, invalid types, boolean/non-finite
  percentage, and invalid timestamp;
- no raw response, token, account, email, or financial value in caplog output.

### Service tests

- missing and cross-workspace integration;
- unsupported API-key provider;
- disabled ChatGPT makes zero refresh/usage calls;
- read-only projection strips financial details;
- write projection preserves financial details;
- freshness permanent/transient failure mapping;
- normal successful read;
- one 401 triggers one forced refresh and one retry;
- repeated 401 stops after retry;
- usage 403 does not call repository update or mutate integration status;
- unexpected adapter exception propagates rather than becoming a success response.

### Route and schema tests

- missing read permission -> 403;
- read-only member receives operational data with `financial_details=null`;
- writer receives financial detail;
- service not found/cross-workspace -> 404;
- unsupported provider -> 409;
- all response variants serialize with discriminator and timezone-aware `fetched_at`;
- integration list route remains provider-call free.

## Validation Commands for This Phase

Run targeted checks first, then project checks:

```bash
cd python/apps/azents
uv run ruff check src/azents/services/subscription_usage \
  src/azents/services/chatgpt_oauth/runtime.py \
  src/azents/api/public/llm_provider_integration/v1
uv run ruff format --check src/azents/services/subscription_usage \
  src/azents/services/chatgpt_oauth/runtime.py \
  src/azents/api/public/llm_provider_integration/v1
uv run pytest -q \
  src/azents/services/subscription_usage \
  src/azents/services/chatgpt_oauth/runtime_test.py \
  src/azents/api/public/llm_provider_integration/v1
uv run pyright

cd ../../libs/azents-public-client
make test

cd ../../../typescript
pnpm run typecheck --filter=@azents/public-client
```

If the generated Python client has no `make test` target, record that fact and run its documented
available generation/type/import check instead. Do not invent a passing command.

Also run `git diff --check` and inspect `git status --short` before handoff.

## Explicit Non-Goals

- xAI HTTP implementation or xAI refresh-window correction;
- frontend tRPC/query/components/translations/stories;
- deterministic E2E fixture or browser tests;
- living spec promotion or design `implemented` date;
- database schema, persisted usage snapshots, cache service, polling, alerts, chat warnings;
- API-key provider billing;
- reset-credit consumption or management;
- broad OAuth refactors unrelated to extracting ChatGPT forced refresh.

## Implementation Handoff Requirements

The implementation subagent must return:

- summary of behavior implemented;
- exact files changed;
- commands run and complete results;
- generated artifacts produced through the official workflow;
- any plan deviation or unresolved provider schema ambiguity;
- confirmation that xAI/frontend/spec/E2E scope was not added;
- confirmation that the working tree contains no unrelated files.

The root agent will then assign an independent verification subagent. No PR is created before that
verification and root recheck complete.
