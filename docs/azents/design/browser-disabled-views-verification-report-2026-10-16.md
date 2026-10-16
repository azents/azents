---
title: "Browser-Disabled Agent View Verification"
created: 2026-10-16
tags: [browser, frontend, testing, security]
document_role: supporting
document_type: supporting-verification-report
---

# Browser-Disabled Agent View Verification

## Requested correction

An Agent with Browser disabled must expose no Browser-use views or entry points. Preserve the enabling setting, historical tool-call text, other supporting views, backend permission checks, native tabs/profiles and Runtime lifecycle. This is a focused correction to existing opt-in behavior, not a new capability or input authority.

## Root cause and correction

The session panel added Browser unconditionally. Its supporting-content renderer mounted the Browser page for `page=browser` without checking the Agent flag. Historical Browser tool results produced Open in Browser links based only on the current route and result identity. Server opt-in admission already prevented use, but these UI entry points still exposed an unavailable feature.

The corrected UI filters the Browser destination, independently guards content mounting, and gives deep tool-result links a false-default scoped current-Agent availability value. Disabled/stale Browser deep links resolve to Files, clearing Browser target parameters and preserving unrelated query parameters. Selection resolves synchronously before effects, and disabled Browser cannot be reopened through a retained selection callback. Removing Browser content unmounts its existing live attachment; it does not close native pages, erase profiles or restart Runtime.

## Current Agent and cache boundary

Independent review reproduced a five-minute QueryClient cache entry containing enabled Browser overriding fresh disabled server props because React Query initialData does not replace an existing entry. A metadata-only correction was insufficient: an earlier pending enabled read could finish after the server boundary and appear newer merely because it completed later.

The final correction uses the server Agent immediately while the current boundary hydrates. It cancels prior scoped Agent reads before seeding the existing query cache with the current server response, then invalidates for a new post-boundary read. Obsolete hydration effects cannot write after new server props arrive. Mount auto-refetch is deferred until seeding; subsequent focus/invalidation reads remain active. No timestamp ordering, persisted content version, new API, preference or input authority is introduced.

Tests exercise the actual QueryClient/QueryObserver with app cache defaults and deferred requests: cached enabled with fresh disabled props, subsequent enable/disable propagation, cancelled delayed pre-boundary responses and superseded hydration. Independent targeted re-review reported no remaining blocking findings in the corrected cache/lifecycle scope and passed all four tests.

## Local verification

- Web Node suite: 570 passed, including three panel-state tests and four current-Agent cache/hydration tests.
- Web TypeScript, ESLint, formatting, Storybook build and Next.js production build: passed.
- Nine actual component stories at 390x844 and 1200x900: 18 interaction passes with no page errors, covering enabled/disabled views, stale content suppression, tool-result links and dynamic link removal, plus existing conversation/mobile/Terminal presentation.
- Tool-result link stories passed accessibility checks. Existing ChatSessionView fixture accessibility warnings remain: aria-allowed-attr, color-contrast, button-name and nested-interactive also occur in the unchanged Conversation baseline. The disabled Browser story adds no new warning category; this report does not claim accessibility-clean chat fixtures or expand into unrelated presentation repairs.
- Browser Web E2E fixture Ruff, formatting and configured type checker: passed.
- Documentation catalog and whitespace validation: passed.

The authenticated Browser Web E2E retains its enabled Browser flow, then disables Browser through the public Agent API and opens a stale exact-target Browser URL. It must land on Files, retain an unrelated query field, remove Browser target parameters and show no Browser tab, live viewport or Open in Browser history link. Submitted-SHA CI is required to establish this assembled-product boundary; local static/component checks are not presented as a local product E2E pass.

## Remaining operational boundary

Final exact-SHA CI evidence belongs in the PR after completion. No merge, deployment, live account operation, Browser profile cleanup or Runtime restart is authorized or performed by this correction.
