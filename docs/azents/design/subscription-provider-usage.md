---
title: "Subscription Provider Usage Design"
created: 2026-07-19
updated: 2026-07-19
tags: [backend, frontend, api, llm, oauth, billing, security, testing]
---

# Subscription Provider Usage Design

## Summary

Azents will show authenticated ChatGPT and xAI subscription usage on the Workspace LLM Settings integration cards.

The feature reads a live, integration-scoped snapshot through the existing encrypted OAuth credential. It normalizes provider-specific quota windows into one public contract, keeps financial details management-only, and does not persist usage history.

ADR-0169 records the architectural decisions behind this design.

## Problem

A workspace can connect ChatGPT OAuth or xAI OAuth and successfully execute Agents without seeing how close the shared provider account is to its subscription limit. Users learn about exhaustion only after provider requests fail or by opening a separate provider client or dashboard.

Azents already distinguishes subscription OAuth integrations from developer API-key integrations, stores refreshable encrypted credentials, and renders each integration in Workspace LLM Settings. It does not currently have a subscription-usage service, public usage endpoint, normalized usage model, or frontend usage state.

The missing information is operationally important but sensitive:

- usage and reset times explain whether the shared integration can continue serving runs;
- credit balances, spend control, pay-as-you-go, and auto top-up reveal financial configuration;
- upstream usage endpoints are implementation-backed and can drift;
- subscription usage must not be confused with AgentRun token usage, context pressure, or estimated API cost.

## Goals

- Read current ChatGPT and xAI subscription usage with the already connected OAuth credential.
- Show normalized limit windows and reset times on the corresponding integration card.
- Preserve provider-specific billing detail without exposing raw provider payloads.
- Restrict financial detail to integration managers while keeping operational quota state visible to integration readers.
- Represent loading, unavailable, external-redirect, stale-refresh, and disabled states explicitly.
- Keep the feature independent from Agent execution, retry, token accounting, and model catalog synchronization.
- Make provider drift diagnosable with deterministic contract fixtures and safe structured logging.
- Isolate every usage read so a broken private provider API can degrade only the affected integration card, never the LLM Settings view, other cards, or integration management actions.

## Non-goals

- Developer API-key billing or usage dashboards.
- Azents-owned accounting, invoice reconciliation, cost allocation, or remaining-request estimation.
- Durable provider usage history, charts, trend analysis, or usage alerts.
- Periodic collection across every workspace integration.
- Automatic model or integration failover based on subscription usage.
- Consuming or managing OpenAI rate-limit reset credits.
- Changing provider billing, spend control, pay-as-you-go, or auto top-up configuration.
- Persistent usage display in the global app header or chat header.

## Current Behavior

### Integration and credential ownership

`LLMProviderIntegration` is workspace-scoped. `chatgpt_oauth` and `xai_oauth` store access and refresh tokens in encrypted secrets and non-secret account/status metadata in provider config.

Runtime token refresh occurs before Agent execution. ChatGPT execution uses the ChatGPT Codex Responses backend. xAI execution uses the xAI inference API. Neither runtime path currently reads subscription usage.

### Public API and permissions

Integration list and detail reads require `LLM_INTEGRATIONS_READ`. Owner has all permissions; Manager and Member currently have integration read permission. Only Owner has `LLM_INTEGRATIONS_WRITE` in the current role map.

The integration list response includes non-secret provider config but never secrets.

### Frontend

`/w/{handle}/settings` renders `LlmSettings`. Each integration is one card containing provider badge, alias, enabled state, and Owner-only management actions.

The list query and model-catalog state are owned by `useLlmSettingsContainer`. There is no provider usage query or usage presentation component.

## Upstream Evidence

The design was validated against these upstream source snapshots on 2026-07-19:

- OpenAI Codex commit `0fb559f0f6e231a88ac02ea002d3ecd248e2b515`.
  - ChatGPT backend usage path: `/wham/usage`.
  - Codex API usage path: `/api/codex/usage`.
  - Snapshot fields include primary and secondary windows, plan type, credits, spend control, additional limits, reached type, and reset-credit availability.
- xAI Grok Build commit `7cfcb20d2b50b0d18801a6c0af2e401c0e060894`.
  - CLI proxy base: `https://cli-chat-proxy.grok.com/v1`.
  - Billing path: `/billing?format=credits`.
  - Auto top-up path: `/auto-topup-rule`.
  - Remote settings can supply `usage_billing_redirect_url` and replace inline billing fetch with an external usage page.
  - Billing fields include usage percentage, current weekly/monthly period, prepaid balance, pay-as-you-go values, billing history, and optional subscription tier enrichment.

These are implementation contracts, not public stability guarantees. Provider adapters and contract fixtures are mandatory.

## User Experience

### Primary workflow

1. User opens Workspace Settings.
2. Eligible enabled OAuth integration cards independently load usage.
3. The card shows one compact row per main quota window.
4. User can manually refresh the card.
5. Owner can expand financial details when available.
6. If xAI directs users to an external usage page, the card shows a trusted external action instead of a progress bar.

### Integration card layout

The existing header remains the first row:

- provider badge;
- integration alias;
- disabled badge when applicable;
- Owner management actions.

A new `SubscriptionUsageSummary` section is rendered below the header only for `chatgpt_oauth` and `xai_oauth`.

Available state:

- one or more limit rows;
- label such as `5-hour limit`, `Weekly limit`, or provider-supplied additional limit name;
- used percentage and progress bar;
- reset text when known;
- freshness text;
- refresh action.

The first card view shows at most two main windows. Additional metered limits appear in expanded details so an account with many limits does not make the integration list unscannable.

### Financial details

Owner-only expanded content can show:

ChatGPT:

- plan label;
- credit availability, unlimited state, and provider-formatted balance;
- individual spend-control limit, used value, remaining percentage, and reset time;
- reached-state explanation when available.

xAI:

- subscription tier when the provider supplies it;
- prepaid credit balance;
- pay-as-you-go usage and cap;
- auto top-up enabled state, amount, and monthly maximum.

The UI does not label an opaque provider credit balance as USD unless the provider contract explicitly defines USD cents.

### Visual states

- Below 75%: normal progress color.
- 75% through below 95%: warning color.
- 95% and above: danger color.
- 100%: danger state with reset time emphasized when known.

The UI displays `used`, not `remaining requests`.

### Loading

Each eligible card owns its loading state. A compact skeleton occupies the usage section; the integration header and actions remain available.

The whole settings page does not return to a global loading state when one usage query refreshes.

### Disabled integration

A disabled integration does not issue a provider usage request. The card shows `Enable this integration to refresh subscription usage.` Existing cached client data is not presented as current while disabled.

### Unavailable state

The card keeps the integration visible and shows a provider-neutral reason and action:

- reconnect required;
- account metadata unavailable;
- usage permission unavailable;
- provider rate limited;
- provider temporarily unavailable;
- provider response changed;
- usage unavailable for this account.

Raw provider error text and response bodies are not displayed.

### External state

For a validated xAI-managed usage URL, the card shows:

- `Usage is managed on xAI.`
- `View usage on xAI` external action.

The URL must use HTTPS and match an approved xAI host policy before it reaches the client.

### Stale refresh

React Query can retain successful data while a later refetch fails. The UI continues to show the previous snapshot with `Update failed · data from <time>` and a retry action.

The backend does not return a stale snapshot because it does not store one.

### Responsive behavior

The usage section is below the non-wrapping action row rather than inserted into it. On narrow screens:

- limit label and percentage remain on the first line;
- reset and freshness move below;
- financial details use a vertical stack;
- management actions remain reachable without horizontal scrolling.

## Public API

### Endpoint

```text
GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/subscription-usage
```

The route requires `LLM_INTEGRATIONS_READ` and verifies that the integration belongs to the current workspace.

Unsupported provider integrations return `409 Conflict`. Disabled integrations return the typed `unavailable` state without contacting the provider.

### Response union

The OpenAPI response is a discriminated union on `type`.

#### Available

```json
{
  "type": "available",
  "integration_id": "...",
  "provider": "chatgpt_oauth",
  "fetched_at": "2026-07-19T00:00:00Z",
  "plan_label": "Pro",
  "limits": [
    {
      "id": "primary",
      "label": "5-hour limit",
      "used_percent": 42.0,
      "window_minutes": 300,
      "resets_at": "2026-07-19T04:00:00Z",
      "primary": true
    }
  ],
  "financial_details": null
}
```

Fields:

- `integration_id`: requested integration identity.
- `provider`: closed supported provider enum.
- `fetched_at`: backend completion time in UTC.
- `plan_label`: optional display metadata; absence does not make the snapshot unavailable.
- `limits`: normalized non-empty list of provider-reported quota windows.
- `financial_details`: provider-specific union or null after permission projection.

#### External

```json
{
  "type": "external",
  "integration_id": "...",
  "provider": "xai_oauth",
  "fetched_at": "2026-07-19T00:00:00Z",
  "url": "https://grok.com/...",
  "message": "Usage is managed on xAI."
}
```

#### Unavailable

```json
{
  "type": "unavailable",
  "integration_id": "...",
  "provider": "xai_oauth",
  "fetched_at": "2026-07-19T00:00:00Z",
  "reason": "temporarily_unavailable",
  "message": "Subscription usage is temporarily unavailable.",
  "retryable": true
}
```

Allowed `reason` values:

- `disabled`;
- `reconnect_required`;
- `account_metadata_missing`;
- `permission_denied`;
- `entitlement_unavailable`;
- `rate_limited`;
- `temporarily_unavailable`;
- `invalid_provider_response`;
- `unsupported_account`.

Messages are fixed Azents copy. Provider-authored billing errors are diagnostic input only.

### Financial detail union

ChatGPT detail:

- `type: chatgpt`;
- `has_credits`;
- `unlimited`;
- nullable provider-formatted `balance`;
- nullable spend-control `limit`, `used`, `remaining_percent`, and `resets_at`;
- nullable reached-state enum.

xAI detail:

- `type: xai`;
- nullable USD-cent `prepaid_balance_cents`;
- nullable pay-as-you-go cap and used cents;
- nullable auto top-up state, amount cents, and monthly maximum cents.

`financial_details` is null when the current member lacks `LLM_INTEGRATIONS_WRITE`, even when the provider returned those values.

## Backend Design

### Layering

The public route calls `SubscriptionUsageService`. The service loads the integration with decrypted secrets through `LLMProviderIntegrationService` or the established secret-bearing repository service boundary, verifies eligibility, refreshes credentials, dispatches to the provider adapter, and applies permission projection.

The route never calls repositories or provider HTTP clients directly.

Suggested modules:

```text
azents/services/subscription_usage/
  service.py
  data.py
  chatgpt_client.py
  xai_client.py
```

Public response models remain under the existing LLM provider integration API version because usage is a child resource of the integration.

### Closed adapter contract

The service dispatches exhaustively on the eligible provider enum. Each adapter returns an internal union:

- `AvailableUsage`;
- `ExternalUsage`;
- `UnavailableUsage`.

Unexpected exceptions propagate. The service does not catch broad exceptions and convert them to `UnavailableUsage`.

Adding a provider requires:

- eligibility update;
- credential/config validation;
- adapter implementation;
- normalized mapping tests;
- public schema update;
- frontend rendering fixtures;
- E2E coverage.

### Credential freshness

Usage reads reuse the existing provider-specific OAuth refresh lifecycle. xAI already exposes both freshness checking and forced refresh. ChatGPT currently exposes only freshness checking, so implementation must extract a `refresh_runtime_tokens` operation with the same persistence and concurrent-refresh recovery semantics before the usage adapter can perform a forced retry.

Flow:

1. Load integration including encrypted secrets.
2. If connection status already requires refresh or entitlement recovery, return the corresponding unavailable reason.
3. Refresh when the access token is inside the normal refresh window.
4. Persist rotated credentials through the existing refresh service.
5. Invoke the usage adapter.
6. If the provider returns 401, force one refresh and retry the usage request once.
7. If forced refresh fails, let the existing refresh lifecycle update connection status and return `reconnect_required`.

Usage-specific 403 responses do not mark inference entitlement denied because billing visibility and inference entitlement can differ.

### ChatGPT adapter

The ChatGPT adapter uses a distinct backend root constant:

```text
https://chatgpt.com/backend-api
```

Request:

```text
GET /wham/usage
Authorization: Bearer <access token>
ChatGPT-Account-Id: <account id>
originator: azents
User-Agent: azents/<version>
```

The adapter requires `account_id`. Missing account metadata returns `account_metadata_missing` rather than attempting an ambiguous account read.

Normalization:

- primary window -> primary limit row;
- secondary window -> secondary limit row;
- additional rate limits -> non-primary rows with provider name/identifier;
- plan type -> `plan_label`;
- credits and individual spend control -> management financial detail;
- rate-limit reached type -> management detail and safe operational presentation.

Reset credits are parsed for compatibility but are not exposed or consumable in the first version.

### xAI adapter

The xAI adapter uses a distinct CLI proxy base constant:

```text
https://cli-chat-proxy.grok.com/v1
```

Required identity includes:

- Bearer access token;
- `X-XAI-Token-Auth: xai-grok-cli`;
- `x-userid` from integration `account_id`;
- pinned compatible Grok client version;
- Azents client-mode and client-identifier values where required by the proxy contract.

The compatibility version is an explicit constant covered by contract tests. It is not derived from the Azents application version.

Flow:

1. Require account id; otherwise return `account_metadata_missing`.
2. Fetch `/settings` as a best-effort remote-control read.
3. If remote settings contain `usage_billing_redirect_url`, validate it and return `ExternalUsage` without billing fetch.
4. Fetch `/billing?format=credits`.
5. Normalize usage percentage and current weekly/monthly period.
6. If a positive prepaid balance exists, fetch `/auto-topup-rule`.
7. Enrich plan label from remote settings when present.

Remote-settings failure alone does not block billing fetch. Billing response failure produces the corresponding unavailable state.

### External URL validation

Accepted xAI usage links must:

- use `https`;
- contain no user info;
- use an exact trusted host or subdomain of `x.ai` or `grok.com`;
- be normalized before serialization.

Invalid redirect values emit safe error telemetry and return `invalid_provider_response`; Azents does not expose or open the URL.

### No durable storage

No migration is required. The service does not write provider usage values to integration config, model catalog, Agent events, or a usage table.

The only possible write is existing OAuth credential rotation or connection-status transition owned by the refresh lifecycle.

## Frontend Data Flow

### tRPC router

Add `llmProviderIntegration.subscriptionUsage` using the generated public client.

Input:

- workspace handle;
- integration id.

The query is enabled only when:

- provider is `chatgpt_oauth` or `xai_oauth`;
- integration is enabled.

Recommended React Query behavior:

- `staleTime`: 60 seconds;
- refetch on window focus when stale;
- no periodic refetch interval;
- manual refresh action;
- retain previous successful data during refetch.

### Container state

Usage state is modeled as an ADT per eligible integration:

- `IDLE`;
- `LOADING`;
- `AVAILABLE`;
- `EXTERNAL`;
- `UNAVAILABLE`;
- `STALE_ERROR`.

The container converts query flags and data into this ADT. `IntegrationCard` and `SubscriptionUsageSummary` receive pure props and callbacks.

The settings page's integration list ADT remains independent so one usage failure does not turn the page into `ERROR`.

Each eligible card owns its query and failure boundary. The page must not aggregate usage requests with `Promise.all`, gate card rendering on usage completion, or throw usage-query failures into the page-level loading/error state. A provider failure, generated-client transport failure, or unexpected render failure in the usage subtree degrades only that card's usage section. Existing card header, enable toggle, alias edit, reconnect, and delete controls remain usable.

A failed initial read renders card-local `UNAVAILABLE`. A failed refresh retains the last successful snapshot as `STALE_ERROR`. Usage failures never clear the integration list cache or mutate inference entitlement. A narrow component error boundary provides the final frontend containment layer for unexpected usage presentation defects.

### Components

Suggested components:

```text
SubscriptionUsageSummary.tsx
SubscriptionUsageLimitRow.tsx
SubscriptionUsageDetails.tsx
```

Meaningful static Storybook states are required:

- ChatGPT two-window usage;
- xAI weekly usage with Owner financial details;
- read-only member projection;
- warning and exhausted limits;
- external xAI redirect;
- unavailable and reconnect-required;
- stale data after refresh error;
- mobile/narrow layout;
- disabled integration.

## Error Handling

### Controlled provider outcomes

- 401: force one refresh; then reconnect required if refresh cannot recover.
- 403: permission or billing entitlement unavailable; do not change runtime integration status.
- 429: rate limited and retryable.
- provider 5xx/network timeout: temporarily unavailable and retryable.
- malformed success body: invalid provider response, non-retryable until manual retry or provider contract update.
- xAI trusted redirect: external success state.

### Unexpected failures

Programming errors, repository failures, decryption failures outside the existing typed credential contract, and unexpected adapter exceptions propagate to normal server error handling.

They are not returned as a 200 response containing an arbitrary error string. The frontend still contains the resulting non-success response inside the affected integration card and does not promote it to the LLM Settings page error state.

### Isolation invariants

- One integration usage read maps to one child endpoint request and one card-local query.
- Provider contract failures are normalized only inside the owning adapter; raw exceptions and payloads never cross that boundary.
- Usage reads do not participate in the integration list query, page bootstrap, catalog sync, or Agent execution readiness.
- Failure for one integration does not cancel, invalidate, or hide another integration's usage request.
- Initial failure replaces only the card's usage section with an unavailable state.
- Refresh failure preserves the last successful client snapshot and marks it stale.
- Usage-read outcomes do not update runtime entitlement or enabled state. Only the shared OAuth lifecycle may mark a credential refresh requirement when refresh itself proves the credential invalid.
- Frontend usage rendering has a card-local error boundary so an unexpected component defect cannot unmount the integration list.

### Logging and observability

Structured logs include only:

- internal provider enum;
- integration id;
- operation `subscription_usage_read`;
- safe outcome category;
- HTTP status when available;
- adapter contract version/fingerprint;
- duration.

Logs exclude:

- access and refresh tokens;
- account id and email;
- provider response body;
- billing amounts;
- redirect query values;
- request headers.

Malformed provider responses should emit error-level logs through the standard logger integration so upstream drift is observable.

## Security and Privacy

- Provider calls occur only on the server.
- OAuth tokens never enter the browser, public response, logs, or telemetry.
- Workspace ownership is verified before secret-bearing integration lookup.
- Operational quota data follows `LLM_INTEGRATIONS_READ`.
- Financial data follows `LLM_INTEGRATIONS_WRITE` and is removed before public model conversion for other members.
- Provider raw billing history is neither exposed nor stored.
- External provider URLs are trusted-domain validated.
- Frontend copy does not reveal the connected account email unless the existing integration surface already intentionally displays it.

## Rollout Plan

### Phase 1: Backend contract and ChatGPT

- Add normalized domain models and public response union.
- Add endpoint, permission projection, and generated clients.
- Implement ChatGPT adapter and deterministic fixtures.
- Add integration-card usage UI states using ChatGPT data.

### Phase 2: xAI parity

- Add remote settings, billing, auto-top-up, and trusted redirect adapter behavior.
- Add xAI financial detail and external-state UI.
- Add xAI deterministic fixtures and E2E cases.

### Phase 3: UX hardening

- Complete mobile and stale-refresh states.
- Add accessibility labels and localized copy.
- Evaluate whether run-scoped chat warnings are justified using resolved integration provenance.

No legacy fallback or parallel old contract is introduced. Each phase must leave unsupported providers absent rather than rendering synthetic usage.

## Test Strategy

### E2E primary verification matrix

| Scenario | Role | Provider state | Expected UI |
|---|---|---|---|
| ChatGPT normal | Owner | primary + secondary windows | Two limit rows, reset times, refresh, financial detail |
| ChatGPT read-only | Member | same snapshot | Limit rows visible, financial detail absent |
| ChatGPT exhausted | Owner | 100% primary | Danger state and reset emphasized |
| ChatGPT provider unavailable | Owner | timeout/5xx | Integration remains usable; usage unavailable with retry |
| xAI normal | Owner | weekly period + prepaid + auto top-up | Weekly row and expandable financial detail |
| xAI external | Owner | trusted redirect setting | External xAI action; no billing bar |
| xAI invalid redirect | Owner | untrusted URL | No external link; invalid-response state |
| xAI usage denied | Member | billing 403 | Permission unavailable; integration status unchanged |
| Disabled integration | Owner | enabled=false | No provider request; disabled usage message |
| Stale refresh | Owner | success then timeout | Previous values retained with stale warning |
| Narrow viewport | Owner | two windows | No horizontal overflow; actions remain reachable |

### E2E execution plan

Use deterministic provider fixtures rather than live subscription credentials in required CI. The fixture server records path and safe header presence, returns pinned upstream-shaped payloads, and can transition between success and failure during one test for stale-refresh coverage.

Playwright verifies rendered labels, progress semantics, role-based financial visibility, manual refresh, external-link validation, and mobile layout. Network interception alone is not sufficient for backend adapter contract tests; E2E should run through the product API and fixture provider.

### Backend tests

- Closed provider dispatch and unsupported-provider rejection.
- Workspace ownership and read permission.
- Financial projection with and without write permission.
- Disabled integration does not call provider.
- Token refresh and one forced-refresh retry after 401.
- Usage-specific 403 does not mutate integration execution status.
- Exact ChatGPT paths and required headers.
- Exact xAI settings, billing, and auto-top-up paths and required headers.
- xAI remote redirect short-circuits billing.
- Redirect host validation.
- Normalization and clamping of percentages.
- Unknown/malformed payload produces typed invalid-response outcome and safe logs.
- Raw body, credentials, account metadata, and financial values are absent from logs.

### Frontend tests and stories

Pure usage components require Storybook stories for every meaningful ADT state. Component interaction tests cover refresh action, details disclosure, and external-link attributes. TypeScript tests cover query eligibility and response-to-ADT conversion.

### Live external tests

Optional live smoke tests may verify one ChatGPT and one xAI account when credentials are explicitly provided. They are excluded from required CI, must not print values or tokens, and should assert only contract availability and normalized field validity.

### Fixtures and evidence

Required evidence for feature completion:

- passing backend provider-contract tests;
- passing generated-client typecheck;
- passing E2E matrix on deterministic fixtures;
- Storybook desktop and narrow snapshots;
- logs demonstrating safe classified failures without secret or billing-value leakage.

Optional live tests are reported separately and do not convert missing credentials into required-CI skips.

## Spec Updates Required During Implementation

- Extend `docs/azents/spec/flow/chatgpt-oauth.md` with usage read behavior.
- Extend `docs/azents/spec/flow/xai-oauth.md` with settings/billing/redirect behavior.
- Update the workspace/integration domain spec if one is introduced or already owns permission projection.
- Keep AgentRun token/context usage specs unchanged except for an explicit distinction if cross-linking is useful.

## Alternatives Considered

### Dedicated workspace usage dashboard

Deferred. The current product has only two eligible providers and already has a repeated integration-card workspace. A dashboard becomes justified when Azents supports aggregation, history, alerting, or many integrations.

### One batch endpoint for every integration

Rejected initially. Per-integration reads provide independent loading, refresh, failure isolation, and authorization. The number of subscription integrations is expected to be small. A batch endpoint can be added later if measured request fan-out warrants it.

### Automatic polling

Rejected initially. Provider usage changes outside Azents and exact freshness is not guaranteed. Page-entry, stale focus refresh, and explicit refresh provide sufficient operational value without continuous provider traffic.

### Chat warning in the first version

Deferred. Correct chat presentation requires resolved integration provenance and clear behavior for subagents or per-prompt provider selection. The settings-card feature can ship independently.

## Validation Findings

- The public API mount prefix is `/llm-provider-integration/v1`, so the proposed child-resource path fits the existing router without a new API module.
- `LlmSettings` already renders repeated integration cards through a container/component split, so usage can load independently without changing page ownership.
- Both OAuth runtimes already centralize credential freshness and persistence. xAI also exposes forced refresh, while ChatGPT requires extraction of an equivalent forced-refresh operation before implementing one-retry-on-401 behavior.
- `docs/azents/spec/flow/xai-oauth.md` currently states a five-minute refresh window, while `services/xai_oauth/runtime.py` currently uses one hour. Subscription usage does not choose a third value. The implementation PR must resolve this existing spec/code drift and then reuse the corrected shared lifecycle.
- Current role mapping gives Manager and Member `LLM_INTEGRATIONS_READ` and reserves write access to Owner, matching the operational-versus-financial projection in this design.

## Open Risks and Assumptions

- OpenAI and xAI may change or restrict these implementation-backed endpoints.
- xAI compatibility headers and remote-settings schema may drift together.
- Provider plan and credit fields may vary by account tier or workspace role.
- A member with integration read permission will see shared quota percentage and reset time; this is an intentional operational visibility policy.
- The first implementation has no shared server cache, so concurrent readers can produce duplicate provider calls.
- Provider usage and inference authorization can disagree; the UI must not imply that unavailable usage means the integration cannot run.

No unresolved product decision blocks implementation planning. Server-side shared caching, durable history, alerting, and chat warnings remain intentionally deferred topics.
