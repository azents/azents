---
title: "Provider Account Linking Phase 2 Global Link API"
created: 2026-09-13
tags: [backend, database, identity, oauth, security]
---

## Phase Execution Plan

- Phase: `2/4 — global link persistence and authenticated account API`
- Branch/base: `feat/provider-account-linking-260913-phase2` → `feat/provider-oauth-account-linking-260913`
- PR boundary: global provider-identity ownership, OAuth start/exchange/list/unlink Public API, and authenticated Web callback contract
- Inputs: approved `identity-260913/REQ`, `identity-260913/ADR-D1..D3`, `identity-260913/DESIGN` revision 1, Phase 1 foundation
- Approved Design mechanisms: `M2`, `M4`, `M5`, `M6`, `M10`, `M11`
- Authority references: `identity-260913/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`; `identity-260913/ADR-D2`, `ADR-D3`
- Design delta: `None`
- Non-goals: Main Web UI, Admin Web cards, native direct URL replacement, provider fakes/E2E, Living Spec promotion, and final candidate/origin surface cleanup owned by later phases

## Deliverables

- Evolve `external_account_links` to global active uniqueness keyed by provider, identity scope, and provider user ID; retain legacy workspace provenance and terminal revocation reason.
- Migrate same-User legacy duplicates deterministically and revoke cross-User conflicts without selecting an owner.
- Resolve and lock active identities globally while preserving existing target-specific authorization fences.
- Add authenticated provider availability, OAuth start, OAuth exchange, list, and elevated unlink contracts with sanitized stable outcomes.
- Finalize claimed Phase 1 OAuth attempts with request-local provider identity projections and no token persistence.
- Regenerate Public OpenAPI/Python/TypeScript clients for the Phase 2 contract.

## Validation

- Model and migration fixtures for empty, same-User duplicate, and cross-User conflict groups.
- Repository/service tests for global reuse, conflict nondisclosure, unlink fencing, attempt generation/session fences, and provider failure terminalization.
- Public route contract/security tests for auth, bounded input, callback mismatch, replay, and sanitized errors.
- Ruff, ty, focused pytest, OpenAPI dump, generated-client regeneration, and TypeScript Public client typecheck.

## Phase boundary note

Legacy native handlers and their temporary persistence contracts remain until the Phase 3 replacement/removal work. Their origin/candidate Public routes and generated symbols remain explicitly deprecated in this phase so the existing Web build stays reviewable; Phase 3 removes them authoritatively. They are not a second global-link authority; all new Phase 2 links use the global identity key and the public OAuth account flow is the only new connection entry.
