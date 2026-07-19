---
title: "Subscription Provider Usage Phase 3 Plan"
created: 2026-07-19
updated: 2026-07-19
tags: [plan, frontend, llm, oauth, billing, accessibility, testing]
---

# Subscription Provider Usage Phase 3 Plan

## Phase Objective

Add integration-scoped subscription usage to the existing Workspace LLM Settings cards for `chatgpt_oauth` and `xai_oauth`. Each eligible card owns an independent query and recovery flow. Usage loading, provider unavailability, transport failure, and unexpected presentation failure must never replace the settings page, hide another integration, or disable the existing integration management controls.

This phase consumes the generated public client added by Phase 1. It does not change OpenAPI, generated files, backend behavior, E2E fixtures, living specs, persistence, polling, history, alerts, AgentRun usage, API-key billing, or chat presentation.

## Implementation Ownership

- The root agent owns the plan, implementation, direct validation, review-feedback fixes, and PR creation.
- The phase remains stacked on the xAI backend PR.
- Tracked code, documentation, comments, Storybook fixtures, commit text, and PR text are English. Locale files contain their target localized copy.
- Validation includes a fresh direct review of the complete phase diff after automated checks pass.

## Data Flow and Isolation

Add `llmProviderIntegration.subscriptionUsage` to the tRPC router. It must call `llmProviderIntegrationV1GetSubscriptionUsage` from `@azents/public-client`, pass workspace handle and integration id, enable `throwOnError`, and map only expected public statuses. It must never raw-fetch a provider or Azents API URL.

A card-scoped container hook owns the query for exactly one integration. The query is enabled only when the integration provider is `chatgpt_oauth` or `xai_oauth` and the integration is enabled. Query policy:

- `staleTime`: 60 seconds;
- no polling/refetch interval;
- normal React Query stale focus behavior;
- retry disabled so the typed provider outcome or one card-local transport failure is presented immediately;
- manual refresh through the query result;
- successful data retained by React Query while a later refresh runs or fails.

The hook projects query state into a discriminated union:

- `IDLE` for unsupported providers;
- `DISABLED` for eligible disabled integrations;
- `LOADING` for the first request;
- `AVAILABLE` for a successful available response;
- `EXTERNAL` for a trusted provider-managed response;
- `UNAVAILABLE` for a typed unavailable response or initial request failure;
- `STALE_ERROR` when a previous successful available/external snapshot remains after a refresh error.

The settings page list state remains independent. No usage request participates in list bootstrap, global loading/error, catalog state, mutation state, or a `Promise.all`. Existing card header, enable toggle, edit, and delete controls remain usable in every usage state. A non-retryable `reconnect_required` outcome provides clear guidance without offering a false retry or destructive replacement action; a dedicated reconnect contract remains outside this frontend phase.

## Component Boundaries

Add a card-local container component that connects the query hook to a pure `SubscriptionUsageSummary` component. Keep normalized response data typed through the generated public client types.

`SubscriptionUsageSummary` renders:

- compact loading skeletons;
- disabled guidance without issuing a request;
- up to two primary limit rows in the summary;
- additional non-primary limits behind progressive disclosure;
- used percentage, semantic progress color, reset time, snapshot freshness, and refresh action;
- typed provider-unavailable copy and a retry action when appropriate;
- stale warning while preserving the last successful snapshot;
- xAI external usage action with safe new-tab attributes;
- management-only financial details only when the API response includes them.

Financial values must not be inferred or relabeled:

- ChatGPT opaque balances and spend values remain provider-formatted text and are not labeled as USD;
- xAI integer-cent fields may be formatted as USD currency;
- absent fields are omitted rather than synthesized;
- the UI never displays raw provider payloads, provider errors, account identifiers, emails, credentials, request identifiers, or rejected URLs.

A narrow React error boundary wraps only the usage subtree. Its fallback is the same card-local unavailable presentation with a recovery action; it must not unmount the integration card or settings list.

## Visual and Accessibility Rules

Preserve the existing integration card header and management layout. Place the usage region below a restrained divider so quota information does not compete with primary integration identity and controls.

- Below 75% uses the normal accent color.
- 75% through below 95% uses warning color.
- 95% and above uses danger color.
- Progress bars expose an accessible label containing the quota label and used percentage.
- Icon-only refresh, edit, and delete actions receive translated accessible labels/tooltips.
- Loading uses inline skeletons rather than a blocking page spinner.
- Narrow layouts stack reset/freshness/detail metadata without horizontal scrolling.
- External links communicate that they open a new tab.
- Date and currency formatting use the active locale.

## Localization

Add matching message keys in English, Korean, French, and Japanese for:

- section title, refresh/retry, loading, disabled, unavailable, stale, freshness, reset, and no-reset states;
- unavailable reason labels;
- additional-limit disclosure;
- external usage action;
- financial detail labels and boolean values;
- accessible labels for management and usage actions.

Provider-returned fixed messages are not rendered directly when localized product copy exists.

## Static Storybook Coverage

Add colocated static stories for the pure usage UI. Stories must not call tRPC or a live public API.

Required states:

- ChatGPT primary and secondary windows with management financial details;
- read-only projection with no financial details;
- xAI weekly usage with prepaid, pay-as-you-go, and auto top-up detail;
- warning and exhausted limit colors;
- trusted xAI external outcome;
- typed unavailable and reconnect-required outcomes;
- stale available snapshot after refresh failure;
- loading;
- disabled integration;
- narrow canvas behavior.

Interaction assertions cover refresh/retry invocation, financial/additional detail disclosure, visible quota labels, and external-link attributes.

## Direct Tests

Add a dependency-free TypeScript unit test for pure usage projection helpers when needed to verify:

- eligibility for only the two OAuth providers;
- unsupported and disabled state selection;
- successful response-to-ADT projection;
- initial request error versus stale refresh error;
- limit summary/detail partitioning;
- progress color thresholds.

Do not add a test-only public contract or duplicate generated response validation.

## Validation Commands

Run from `typescript/`:

```bash
pnpm run format
pnpm run lint
pnpm run typecheck
pnpm exec turbo run typecheck --filter=@azents/web
pnpm exec turbo run build --filter=@azents/web
pnpm exec turbo run build-storybook --filter=@azents/web
```

Run the focused web unit test command if a test module is added, then run:

```bash
git diff --check
git status --short
```

The final review verifies no generated file changed, no polling/persistence/global usage state was introduced, every eligible card remains independent, and sensitive/provider-authored values are absent from UI, logs, and fixtures.

## Explicit Non-Goals

- backend, OpenAPI, or generated client changes;
- deterministic provider fixtures or browser E2E implementation;
- live provider credentials or smoke tests;
- living spec promotion;
- integration list batching or shared server/client usage cache;
- periodic polling, durable history, charts, alerts, or chat warnings;
- AgentRun token/context accounting or developer API-key billing;
- integration entitlement, enabled-state, catalog, or runtime mutation from usage outcomes.

## Completion Requirements

Before opening the PR, record changed files, exact commands and results, Storybook coverage, build evidence, and direct-review findings. Confirm that an initial usage failure changes only its usage section, a refresh failure retains the previous successful snapshot, disabled integrations issue no request, read-only responses expose no financial section, and generated files remain unchanged.
