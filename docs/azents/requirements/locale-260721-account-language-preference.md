---
title: "Account Language Preference Requirements"
created: 2026-07-21
updated: 2026-07-21
tags: [locale, account, frontend, backend]
document_role: primary
document_type: requirements
snapshot_id: locale-260721
---

# Account Language Preference Requirements

- Snapshot: `locale-260721`
- Document reference: `locale-260721/REQ`

## Problem

The current language value belongs to a workspace membership profile but does not control the application interface language. A person can therefore select one language in their profile while the application renders in another language based on browser state.

## Primary Actor

An authenticated Azents user who wants one consistent interface language across all of their workspaces.

## Primary Scenario

A signed-in user chooses a language in Account Settings. On the next render, every application surface uses that account language regardless of the browser locale cookie or browser default language.

## Supporting Scenarios

- A signed-out visitor selects a language and receives that language on later visits in the same browser.
- A signed-out visitor without a saved browser language receives the best supported browser language, or English when none is supported.
- An existing user receives an account language migrated from their earliest workspace membership.

## Goals

- Make interface language an account-level preference.
- Apply a deterministic language resolution order for authenticated and signed-out visitors.
- Remove workspace-member language state and its public exposure.

## Non-Goals

- Per-workspace interface-language preferences.
- Adding languages beyond the currently supported locales.
- URL-based locale routing.

## Requirements

### REQ-1. Account-wide interface language

Authenticated users can view and change an account-level interface language in Account Settings.

**Acceptance criteria**

- The account language is returned by the authenticated current-user API.
- Updating the account language persists the selected supported locale.
- A saved account language is applied across every workspace the user can access.

### REQ-2. Deterministic language resolution

The application resolves language consistently for both authenticated and signed-out requests.

**Acceptance criteria**

- An authenticated account language takes precedence over a browser locale cookie and browser default language.
- A signed-out request uses the browser locale cookie before the browser default language.
- A request without a supported resolved locale uses `en-US`.

### REQ-3. Workspace-member locale removal

Workspace membership no longer stores or exposes an interface language.

**Acceptance criteria**

- Workspace-member API responses and updates have no locale field.
- Workspace profile and administrator member surfaces do not display or edit a locale.

### REQ-4. Existing-language migration

Existing account language is initialized deterministically from prior workspace membership data.

**Acceptance criteria**

- Each existing user receives the locale from their earliest workspace membership ordered by membership creation time and then membership ID.
- Users without an eligible supported source locale receive `en-US`.

## Fixed Constraints

- Supported locales remain `en-US`, `ko-KR`, `ja-JP`, and `fr-FR`.
- The locale migration fallback is `en-US`.
- No legacy workspace-language compatibility path is retained after the migration.

## Open Assumptions

- The account language is stored for every user, including users who have not joined a workspace.

## Confirmation

Confirmed by the requester on 2026-07-21 before ADR and design decisions began.
