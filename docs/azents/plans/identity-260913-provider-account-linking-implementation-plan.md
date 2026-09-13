---
title: "Provider Account Linking Implementation Plan"
created: 2026-09-13
updated: 2026-09-13
tags: [backend, frontend, admin, external-channel, identity, oauth, security, testenv]
---

# identity-260913 Implementation Plan

- Requirements: [`identity-260913/REQ`](../requirements/identity-260913-provider-account-linking.md)
- ADR: [`identity-260913/ADR`](../adr/identity-260913-provider-account-linking.md)
- Design: [`identity-260913/DESIGN`](../design/identity-260913-provider-account-linking.md)
- Design delta: `None`
- Delivery shape: four dependent stacked PR phases
- Independent reviewer: assigned at phase review from the current branch's read-only review owner

## Approved mechanisms and phase boundaries

| Phase | PR boundary | Mechanisms | Dependencies |
| --- | --- | --- | --- |
| 1/4 | System Settings Sections, OAuth attempt persistence, and provider adapter contracts | M1, M2, M3 | approved Design only |
| 2/4 | Global link schema migration, repository/service, start/exchange/list/unlink APIs, authenticated Web callback, generated Public clients | M2, M4, M5, M6, M10, M11 | Phase 1 |
| 3/4 | Main Web account flow, Admin Web provider cards, Slack/Discord direct URL controls, removal of legacy native/UI routes | M1, M6, M7, M8, M10 | Phase 2 |
| 4/4 | Provider fakes, required E2E, migration tests, spec promotion, absence verification and plan cleanup | M8, M9, M10, M11 | Phase 3 |

## Phase 1 — foundation and migration boundary

- Add typed direct System Settings Sections for Slack and Discord identity OAuth Apps,
  including registry, redacted projections, optimistic Admin routes, generated Admin
  clients, and Admin Web card primitives.
- Add OAuth-attempt typed domain and persistence model, bounded repository lifecycle,
  state hashing, auth-Session/configuration-generation fields, and cleanup scheduling.
- Add typed provider adapter contracts and Slack SDK-backed identity operations. Add the
  Discord adapter dependency and test-only endpoint injection boundary without exposing
  tokens.
- Generate an Alembic migration through the repository migration workflow for OAuth
  attempts, System Setting enum values, global link schema transformation, and removal
  of origin/candidate tables. Preserve model draft/mutation link FKs and migration audit
  behavior.
- Validation: focused Python unit/repository/model tests, System Settings route tests,
  migration tests, and OpenAPI/Admin client generation checks.

## Phase 2 — backend account flow

- Replace external-account-link service/repository contracts with global identity
  projections and ownership-safe conflict behavior.
- Implement authenticated provider start/exchange routes and protected Main Web callback
  contract. Discard provider tokens after identity projection.
- Replace list/unlink API projections with global identity fields and regenerate Public
  clients. Remove origin/candidate route and generated symbols.
- Update linked-user model-setting lookup to global identity while retaining target
  authorization transaction fences.
- Validation: backend unit/repository/route/security tests and focused API contract
  tests.

## Phase 3 — surfaces and legacy removal

- Implement Main Web External accounts connect/result/list/disconnect flow and provider
  availability states.
- Implement Admin Web Slack/Discord System Settings cards, callback URL presentation,
  redacted secret actions, optimistic conflict, health and audit refresh behavior.
- Replace Slack/Discord native account-link custom interactions with direct Web URL
  buttons and remove `optional`, duplicate disconnected copy, code modals, and deferred
  account-link handoffs.
- Delete obsolete confirmation page, candidate/origin UI types, translations, routes,
  and native code path tests.
- Validation: TypeScript format/lint/typecheck/build, component stories, backend native
  presentation tests, and Web Surface smoke tests.

## Phase 4 — deterministic verification and promotion

- Extend provider fakes with authorization redirect, code exchange, identity lookup,
  cancellation, malformed response, replay, PKCE, and redacted request capture.
- Replace candidate/code E2E scenarios with Web OAuth and global reuse scenarios;
  include Admin configuration and target authorization denial.
- Add migration fixtures for empty, same-User duplicate, and cross-User conflict groups.
- Run full required quality, security, generated-client, E2E and absence verification.
- Update Living Specs and set the matching `implemented: 2026-09-13` only after all
  implementation and verification are complete.

## Integration order

1. Phase 1 migration/settings/attempt foundation.
2. Phase 2 backend API and global link consumers.
3. Phase 3 Web/Admin/native replacement and legacy removal.
4. Phase 4 fakes, E2E, spec promotion, absence audit and plan cleanup.

## Rollout and external prerequisites

- Drain old binaries before the migration and deploy phases in order.
- Register the exact displayed callback URLs in the reused Slack App and Discord
  Application before enabling provider settings.
- Do not import OAuth credentials from environment variables or Workspace connections.
- Live provider credentials are not required for CI; deterministic fakes are required.

## Scope checkpoints

Each phase must preserve `Design delta: None`. A new user-visible behavior, authority,
state source, provider scope, fallback, or rollout mode returns to technical feature
design before implementation continues.
