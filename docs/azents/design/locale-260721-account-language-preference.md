---
title: "Account Language Preference Design"
created: 2026-07-21
tags: [locale, account, frontend, backend, migration, testing]
document_role: primary
document_type: design
snapshot_id: locale-260721
---

# Account Language Preference Design

- Snapshot: `locale-260721`
- Requirements: [`locale-260721/REQ`](../requirements/locale-260721-account-language-preference.md)
- ADR: [`locale-260721/ADR`](../adr/locale-260721-account-language-preference.md)

## Current Gap

`WorkspaceUser.locale` is persisted and exposed through workspace-member profiles, but next-intl resolves the rendered language through a browser cookie, `Accept-Language`, and an English fallback. The resulting profile value does not affect application localization and can vary across a single user's workspace memberships.

## Data and API Boundary

Add a non-null supported `locale` field to `User` with `en-US` as its database default. Include locale in the authenticated `GET /user/v1/me` projection and add a self-service update operation under the same User API boundary. Remove locale from `WorkspaceUser` models, creation inputs, update payloads, and public responses.

The database migration must:

1. add `users.locale` with an `en-US` default;
2. derive each existing user's source locale using the earliest `workspace_users` row ordered by `created_at ASC, id ASC`;
3. write the source value only when it is one of the supported locales, otherwise retain `en-US`; and
4. drop `workspace_users.locale` after the backfill.

## Request-Time Resolution

Introduce a server-only account-locale resolver for next-intl request configuration.

1. Read the authenticated access token from HTTP-only cookies.
2. When a usable access token exists, fetch the current user's locale from the internal Public API without response caching.
3. If a valid account locale is available, use it.
4. Otherwise retain the current browser `locale` cookie, `Accept-Language`, and `en-US` fallback sequence.

The resolver does not rotate refresh tokens during Server Component locale resolution because that path cannot safely persist rotated authentication cookies. The browser cookie remains synchronized after authenticated account-language updates so an access-token refresh boundary retains a stable locale render.

## Web UI

Extend Account Settings with a language selection control. Its save action calls the User API, writes the browser `locale` cookie through the existing LocaleProvider, and reloads the page after a successful update.

Remove language selection from the workspace member profile. Update Administrator workspace-member views and tRPC schemas to stop rendering or accepting locale.

## Failure Handling

- An unavailable or unauthorized internal current-user lookup does not block rendering; the resolver uses browser preference fallback.
- Unsupported stored or supplied locale values are rejected by the User API update contract and treated as unavailable by the resolver.
- Database migration always leaves an account locale populated with `en-US` when the source membership is absent or invalid.

## Traceability

| Requirement | ADR | Design mechanism |
| --- | --- | --- |
| `locale-260721/REQ-1` | `locale-260721/ADR-D1` | User model, User API, Account Settings form |
| `locale-260721/REQ-2` | `locale-260721/ADR-D2` | server-only account locale resolver, existing cookie/header fallback |
| `locale-260721/REQ-3` | `locale-260721/ADR-D1` | remove WorkspaceUser locale persistence, contracts, and UI |
| `locale-260721/REQ-4` | `locale-260721/ADR-D3` | deterministic Alembic data migration |

## Test Strategy

### E2E Primary Verification Matrix

| Scenario | Expected evidence |
| --- | --- |
| Guest with no locale cookie and Korean browser header | Korean UI is rendered |
| Guest with English locale cookie and Korean browser header | English UI is rendered |
| Authenticated user with English account locale and Korean browser state | English UI is rendered |
| Authenticated user changes account locale | Saved locale and subsequent UI render match the selection |
| User with multiple workspace memberships | Account locale is independent of active workspace |
| Existing migration source selection | Earliest membership locale is copied; absent or invalid source becomes `en-US` |

### E2E Plan

Add or update Web Surface E2E coverage for guest fallback and authenticated account-precedence behavior. Extend credential-free Public API E2E coverage for current-user locale update and workspace-member locale removal.

### Fixture and Prerequisite Requirements

Existing credential-free user/workspace setup is sufficient. No live credentials or new testenv fixture are required.

### Evidence and CI Policy

Run affected Python unit/API tests, generated-client checks, web lint/typecheck/build, and the credential-free E2E lanes required by CI. A failed mandatory check blocks the PR; optional live-external lanes are out of scope.

## Rollout and Rollback

This is a schema and API contract replacement, not a legacy-compatible dual-read rollout. The migration is applied once with deterministic fallback and the deployed application reads only `User.locale`. Database rollback is available only through the migration chain before deployment; application rollback after migration requires a compatible release that ignores the new User field rather than restoring workspace locale behavior.
