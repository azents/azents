---
title: "Session Subscription Usage Validation — 2026-07-19"
created: 2026-07-19
updated: 2026-07-19
tags: [frontend, llm, oauth, ux, testing, validation]
---

# Session Subscription Usage Validation — 2026-07-19

## Scope

Validated the frontend-only projection of the selected OAuth model's subscription usage into draft and concrete-session composers. The change reuses the shipped integration-scoped subscription-usage API and query state without changing backend, OpenAPI, provider adapter, permission, or persistence behavior.

No new Web Surface E2E was added. Existing subscription-usage validation remains authoritative for the provider and public API contracts; this validation covers the new composer selection, presentation, interaction, and build integration.

## Automated Results

| Check | Result |
|---|---|
| Prettier format check | Passed |
| ESLint without cache | Passed with zero warnings |
| TypeScript typecheck | Passed |
| azents-web unit tests | 45 passed, including 4 composer subscription-usage projection tests |
| azents-web production build | Passed |
| Storybook production build | Passed |

Commands:

```console
cd typescript/apps/azents-web
pnpm exec eslint src .storybook --max-warnings 0 --no-cache
pnpm run typecheck
pnpm run test
pnpm run build
pnpm run build-storybook
```

The TypeScript public client was regenerated from the existing public OpenAPI document before the final checks. Generated files are ignored build artifacts and were not edited manually or committed.

## Scenario Coverage

- Selected ChatGPT OAuth and xAI OAuth options resolve to their stored integration IDs.
- Switching the selected model changes the integration-specific query identity.
- API-key and unsupported providers hide the subscription usage projection.
- Available and stale snapshots project the primary provider limit.
- Warning and critical severity thresholds are deterministic.
- Loading, unavailable, external, and unsupported states remain explicit.
- Desktop and compact mobile component states compile in Storybook.
- Refresh, trusted external-link attributes, accessible labels, and financial-detail omission are encoded in colocated Storybook interaction assertions.
- Subscription usage failures remain isolated from model selection and message submission controls.

## Documentation Comparison

- ADR-0170 owns the selected-model placement and operational-only visibility decision.
- The implemented design records the compact desktop/mobile behavior and frontend-only validation boundary.
- `docs/azents/spec/domain/conversation.md` is the current-behavior source of truth for composer projection, provider eligibility, freshness, and failure isolation.
- ChatGPT OAuth and xAI OAuth provider flow contracts are unchanged because the session projection reuses the existing integration-scoped endpoint and provider adapters.

## Findings

No product-code defect remained after final validation. A local ignored generated TypeScript client had temporarily reflected a different branch's OpenAPI state; regenerating it from the current branch restored the expected subscription-usage export. Cache-independent lint and the production build then passed.
