---
title: "Subscription Provider Usage Phase 2 Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [plan, backend, llm, oauth, billing, security, testing]
---

# Subscription Provider Usage Phase 2 Plan

## Phase Objective

Add xAI OAuth subscription usage behind the Phase 1 normalized endpoint without changing the public OpenAPI response shape or adding frontend behavior. The phase implements the source-backed xAI CLI proxy settings, billing, optional auto-top-up, trusted external redirect, shared OAuth freshness, and one-refresh retry behavior.

Usage failures remain read-only and card-local. They must never update xAI inference entitlement, integration enabled state, or connection status. Only the existing shared OAuth token refresh lifecycle may persist connection state when token refresh itself proves a credential rejected, entitlement denied, or temporarily unavailable.

## Implementation Ownership

- The root agent owns the plan, implementation, validation, review-feedback fixes, and PR creation.
- The phase must not add frontend code, E2E fixtures, living spec edits, migrations, durable usage storage, API-key billing, or public schema changes.
- Validation must include a fresh direct review of the complete phase diff after all implementation checks pass.

## Source Evidence and Compatibility Fingerprint

Pinned implementation evidence:

- repository: `/workspace/agent/research/grok-build`;
- commit: `7cfcb20d2b50b0d18801a6c0af2e401c0e060894`;
- Grok compatibility version: `0.2.105` from `xai-grok-version/Cargo.toml`;
- CLI proxy base: `https://cli-chat-proxy.grok.com/v1`;
- endpoints: `GET /settings`, `GET /billing?format=credits`, `GET /auto-topup-rule`.

The wire contract is private and implementation-backed. Isolate it in the xAI subscription usage adapter, record a stable adapter contract version, and never expose raw provider JSON, error strings, URLs rejected by validation, request identifiers, headers, credentials, account id, email, or arbitrary metadata.

## Required Repository Rules

Before editing, read repository/Python/docs `AGENTS.md`, applicable Python conventions, the Phase 1 domain/service implementation, xAI OAuth runtime and tests, and the xAI OAuth living spec for the currently intended five-minute refresh window.

Do not edit generated clients because this phase must not change the public schema. Do not add a migration. Do not update living specs in this phase; the planned spec-promotion PR remains authoritative for spec changes.

## Provider Endpoint Configuration and Identity

Add a dedicated non-secret xAI usage proxy default and resolver:

```text
https://cli-chat-proxy.grok.com/v1
```

Support an explicit test/development base URL override while preserving the production default when absent. Do not reuse the inference API base `https://api.x.ai/v1`.

Every provider request uses:

- `Authorization: Bearer <access token>`;
- `X-XAI-Token-Auth: xai-grok-cli`;
- `x-userid: <account id>`;
- `x-grok-client-version: 0.2.105`;
- `x-grok-client-identifier: grok-shell` as the pinned compatible upstream identity;
- `x-grok-client-mode: interactive` as the pinned compatible upstream mode.

Do not send `x-email`. Treat absent, empty, or whitespace-only account id as `account_metadata_missing` and make zero provider HTTP calls.

## Adapter Outcomes and Service Dispatch

Extend the internal subscription usage adapter union with xAI-specific normalized outcomes needed before integration projection:

- available xAI snapshot with one normalized operational limit and optional financial details;
- trusted external redirect marker containing only the validated URL and fixed Azents message;
- internal unauthorized marker for one service-level forced-refresh retry;
- controlled unavailable outcome carrying only reason, retryability, and safe HTTP status telemetry.

Extend `SubscriptionUsageService.read` from ChatGPT-only eligibility into exhaustive closed dispatch for `chatgpt_oauth` and `xai_oauth`. Preserve 409 for every other provider. Keep financial projection in the service: read-only callers receive `financial_details=None` even though the provider billing response is fetched once.

xAI config eligibility:

- disabled integration or config status `disabled` -> typed `disabled` without freshness/provider calls;
- `refresh_required` -> `reconnect_required` without provider calls;
- existing `entitlement_denied` -> `entitlement_unavailable` without provider calls;
- `temporarily_unavailable` remains eligible for the shared freshness lifecycle;
- invalid xAI secret/config types -> `invalid_provider_response` without detail leakage.

## xAI OAuth Refresh Window Correction

Change `services/xai_oauth/runtime.py` refresh window from one hour to five minutes so runtime behavior matches the living spec. Do not modify the shared persistence, concurrent-refresh recovery, or failure-state mapping.

Add deterministic boundary tests with an injected/frozen current time or expiration offsets:

- more than five minutes remaining -> unchanged integration and zero refresh calls;
- within five minutes -> shared refresh path;
- direct `refresh_runtime_tokens` refreshes a still-fresh token;
- existing non-xAI and invalid-type behavior remains unchanged.

Usage flow:

1. call xAI `ensure_runtime_tokens`;
2. map token refresh `ProviderRejected` to `reconnect_required`, `ProviderEntitlementDenied` to `entitlement_unavailable`, and `ProviderUnavailable` to retryable `temporarily_unavailable`;
3. run the full settings/redirect/billing/optional-enrichment sequence with the fresh token;
4. if any required settings or billing request returns the internal unauthorized marker, call xAI `refresh_runtime_tokens` exactly once;
5. rerun the full sequence exactly once with the returned integration;
6. repeated unauthorized -> `reconnect_required` without another refresh or request sequence.

A usage 403 must not call repository update methods or reuse the runtime entitlement-persistence path.

## Settings Read and Redirect Kill Switch

Call `GET /settings` first. Parse only:

- `subscription_tier`;
- `subscription_tier_display`;
- `on_demand_enabled`;
- `usage_billing_redirect_url`.

Settings is best effort unless it contains a non-empty redirect value:

- timeout, transport error, 4xx, 5xx, malformed JSON, or malformed non-redirect fields: record safe observation and continue to billing;
- absent or blank redirect: continue to billing;
- valid trusted redirect: return internal external outcome and skip billing and auto-top-up;
- invalid redirect: return non-retryable `invalid_provider_response`, do not fall through to billing, do not serialize/log the rejected URL.

Trusted redirect validation:

- absolute HTTPS only;
- no username or password/userinfo;
- hostname must be exact `x.ai`, a subdomain of `x.ai`, exact `grok.com`, or a subdomain of `grok.com`;
- reject lookalikes such as `evilx.ai`, `x.ai.evil.example`, `grok.com.evil.example`, trailing-dot ambiguity unless normalized explicitly, IP literals, non-HTTPS schemes, scheme-relative URLs, relative paths, and values with invalid host parsing;
- preserve the validated URL for the public `HttpUrl` conversion, but never include it in logs.

Use fixed English external message from Azents, not provider text.

## Billing Read and Normalization

Call `GET /billing?format=credits` when settings did not produce an external outcome.

Parse top-level fields:

- `config`;
- `onDemandEnabled`;
- `subscriptionTier`.

New config fields:

- `creditUsagePercent`;
- `currentPeriod.type`, `.start`, `.end`;
- `onDemandCap.val`;
- `onDemandUsed.val`;
- `prepaidBalance.val`;
- `isUnifiedBillingUser` only for compatibility validation, without public exposure.

Legacy fallback fields:

- `monthlyLimit.val`;
- `used.val`;
- `billingPeriodStart`;
- `billingPeriodEnd`.

Operational limit normalization:

- prefer finite numeric `creditUsagePercent` and clamp presentation to `[0, 100]`;
- if absent, derive `used / monthlyLimit * 100` only when `monthlyLimit.val > 0`;
- reject bools, strings, non-finite values, invalid structures, and legacy division inputs that cannot yield a valid percentage;
- prefer `currentPeriod.end` for `resets_at`, falling back to `billingPeriodEnd`;
- parse RFC3339 timestamps into timezone-aware UTC datetimes;
- `USAGE_PERIOD_TYPE_WEEKLY` -> `Weekly limit`, monthly variant -> `Monthly limit`, otherwise a valid unknown period type -> `Subscription limit`;
- use stable limit id `subscription`, `primary=True`, and derive `window_minutes` from valid period start/end when both are available and ordered;
- an available billing response requires `config` and one valid operational usage percentage.

Plan label precedence:

1. non-empty settings `subscription_tier_display`;
2. non-empty billing `subscriptionTier`;
3. non-empty settings `subscription_tier`;
4. otherwise `None`.

Financial normalization:

- Cent wrappers require mapping shape and signed integer `val`; proto3 zero omission permits `{}` and normalizes to zero where the upstream type documents that behavior;
- reject bool, float, string, and overflow-incompatible values;
- map prepaid balance, on-demand cap, and on-demand used into the existing xAI financial detail fields in integer cents;
- `onDemandEnabled` is not substituted for auto-top-up enabled; it controls PAYG availability only and does not add a new public field in this phase;
- history/product usage/unified billing flags are not exposed or stored.

Required billing HTTP classification:

- 401 -> internal unauthorized marker;
- 403 -> non-retryable `entitlement_unavailable` (usage-only, no state mutation);
- 429 -> retryable `rate_limited`;
- 5xx, timeout, transport -> retryable `temporarily_unavailable`;
- other non-success -> non-retryable `unsupported_account` unless source evidence supports a more specific existing reason;
- malformed/non-object/missing required billing data -> non-retryable `invalid_provider_response`.

## Optional Auto Top-Up Enrichment

Call `GET /auto-topup-rule` only when normalized `prepaidBalance.val` satisfies `abs(value) > 0`.

Parse:

```json
{
  "rule": {
    "enabled": true,
    "topupAmount": {"val": 500},
    "maxAmountPerMonth": {"val": 2000},
    "minBeforeHittingSl": {"val": 100}
  }
}
```

Rules:

- `rule: null` -> disabled/no configured rule;
- missing `enabled` -> false, matching proto3 omission;
- top-up amount and monthly maximum use strict Cent parsing;
- `minBeforeHittingSl` is compatibility-parsed but not exposed by the existing public contract;
- any auto-top-up timeout, transport error, non-success status, invalid JSON, or malformed shape is optional-enrichment failure: keep the billing outcome available and omit all auto-top-up fields rather than failing usage;
- auto-top-up 401 does not trigger the service-level refresh retry because required billing already succeeded; record safe optional-enrichment failure and omit it;
- never log values or provider error strings.

## Logging and Isolation

Keep one safe service completion event with provider, integration id, operation, outcome, safe required-request HTTP status, xAI adapter contract version, and duration. Optional settings/auto-top-up failures may emit fixed-message observations with endpoint category and safe status only.

No xAI usage path may:

- update integration config/status directly;
- call entitlement persistence helpers;
- disable the integration;
- change model catalog or runtime inference state;
- write billing/usage data to storage;
- log account id, email, token, raw body, redirect, financial values, or exception/provider strings.

Unexpected programming errors propagate instead of becoming typed 200 responses.

## Required Tests

### xAI adapter tests

Use `httpx.MockTransport` and assert exact paths/query and header presence/test values.

- settings -> billing normal flow;
- exact header identity and absence of `x-email`;
- None/blank/whitespace account id -> zero calls;
- settings tier precedence;
- settings 4xx/5xx/timeout/transport/malformed -> billing still succeeds;
- blank redirect -> billing;
- trusted exact/subdomain x.ai and grok.com redirect -> external and zero billing calls;
- invalid scheme/userinfo/lookalike/relative/IP/trailing-dot redirect -> invalid response and zero billing calls;
- new weekly/monthly/unknown period normalization;
- legacy percentage/reset fallback;
- percentage clamping, invalid bool/string/nonfinite, zero/negative legacy limit;
- strict Cent parsing and proto3 omitted-zero behavior;
- auto-top-up called only for absolute non-zero prepaid balance;
- enabled, omitted-enabled, null-rule auto-top-up mapping;
- auto-top-up transport/status/malformed/401 leaves available result with omitted enrichment;
- 401/403/429/5xx/other status classification;
- malformed billing JSON/object/config/timestamps;
- caplog contains no secrets, account/email, provider body/error, rejected URL, or financial values.

### Service tests

- xAI successful available and read/write financial projection;
- disabled/refresh-required/entitlement-denied config short-circuit;
- freshness rejected/entitlement/transient mapping;
- first required-request 401 -> exactly one forced refresh and one full retry;
- repeated 401 -> reconnect required, no third sequence;
- settings failure plus billing success remains available;
- trusted redirect returns external;
- invalid redirect stays invalid and skips billing;
- billing 403 calls no repository update and leaves integration config/entitlement unchanged;
- optional auto-top-up failure remains available;
- unexpected adapter exception propagates;
- ChatGPT Phase 1 behavior remains unchanged under closed provider dispatch.

### Runtime tests

- five-minute threshold boundary, including more-than-five and within-five cases;
- forced refresh of fresh token;
- persistence/race/failure behavior unchanged;
- non-xAI/invalid integration behavior unchanged.

### Route tests

- xAI available/external/unavailable conversion uses the unchanged Phase 1 schema;
- read-only financial stripping and writer detail preservation;
- integration list remains provider-call free;
- no OpenAPI/generated-client diff is produced.

## Validation Commands

```bash
cd python/apps/azents
uv run ruff check src/azents/services/subscription_usage \
  src/azents/services/xai_oauth/runtime.py \
  src/azents/api/public/llm_provider_integration/v1
uv run ruff format --check src/azents/services/subscription_usage \
  src/azents/services/xai_oauth/runtime.py \
  src/azents/api/public/llm_provider_integration/v1
uv run pytest -q \
  src/azents/services/subscription_usage \
  src/azents/services/xai_oauth/runtime_test.py \
  src/azents/api/public/llm_provider_integration/v1
uv run pyright

git diff --check
```

Also dump OpenAPI to a temporary file or compare live schema semantically against the tracked Phase 1 spec and assert no public schema change. Do not regenerate/commit clients when the schema is unchanged.

## Explicit Non-Goals

- frontend query/components/translations/stories;
- deterministic E2E fixture/browser validation;
- living spec promotion;
- database migration, cache, persistence, polling, history, alerts, or chat warnings;
- xAI API-key billing;
- sending xAI email metadata;
- exposing unified billing, history, product usage, raw redirect metadata, or auto-top-up threshold;
- changing the Phase 1 public response contract;
- broad xAI OAuth refactors beyond the five-minute drift correction and shared lifecycle reuse.

## Completion Requirements

Before creating the PR, the root agent records files changed, exact checks and results, no-schema-diff evidence, source-contract ambiguities, confirmation that usage failures do not mutate entitlement/state, and confirmation that frontend/spec/E2E/migration scope was not added. The root agent then performs a fresh direct review of the complete phase diff and resolves every finding.
