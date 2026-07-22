---
title: "Account Language Preference"
created: 2026-07-21
tags: [locale, account, frontend, backend, migration]
document_role: primary
document_type: adr
snapshot_id: locale-260721
---

# Account Language Preference

- Snapshot: `locale-260721`
- Requirements: [`locale-260721/REQ`](../requirements/locale-260721-account-language-preference.md)

## Context

The current `WorkspaceUser.locale` is workspace-scoped state, but interface localization is user-scoped. It is not used by the active next-intl request resolution path, which currently resolves only browser cookie, `Accept-Language`, and an English fallback. The product requires a single account language that supersedes browser preferences for authenticated users.

## Decisions

### locale-260721/ADR-D1. Store interface language on User

**Status**: Accepted on 2026-07-21

**Requirements**: `locale-260721/REQ-1`, `locale-260721/REQ-3`

The canonical interface-language preference belongs to `User`, not `WorkspaceUser`. The User API owns its read and update contract, and Account Settings owns the user-facing control.

**Rejected alternative**: Retain `WorkspaceUser.locale` and select one workspace's value at render time. This would make a global UI preference depend on the current workspace and leave multi-workspace users with ambiguous behavior.

### locale-260721/ADR-D2. Resolve locale with account preference first

**Status**: Accepted on 2026-07-21

**Requirements**: `locale-260721/REQ-2`

Authenticated rendering resolves a valid account locale before the existing browser `locale` cookie and `Accept-Language`. Signed-out rendering retains cookie, then header, then `en-US` resolution. The browser cookie remains the persistence mechanism for signed-out preference and is synchronized when an authenticated user changes their account language.

**Rejected alternative**: Use only the browser cookie for all visitors. This cannot make a user's selected language consistent across browsers or workspaces.

### locale-260721/ADR-D3. Migrate from the earliest workspace membership

**Status**: Accepted on 2026-07-21

**Requirements**: `locale-260721/REQ-4`

The migration initializes each existing `User.locale` from the user's earliest `WorkspaceUser`, ordered by `created_at ASC, id ASC`. If that row has no supported locale, or no membership exists, the migration stores `en-US`.

**Rejected alternative**: Use the most recently updated or most recently joined membership. These values are less aligned with the requester-specified first membership rule and may reflect unrelated workspace profile changes.

## Consequences

- The public API and generated clients change for both current-user and workspace-member models.
- The migration permanently drops `workspace_users.locale`; no fallback reads or writes remain.
- Account locale must be available to server-side locale resolution without exposing authentication tokens to client code.
