---
title: "Provider Account Linking Phase 1 Foundation"
created: 2026-09-13
tags: [backend, admin, database, identity, oauth, security]
---

## Phase Execution Plan

- Phase: `1/4 — foundation and migration boundary`
- Branch/base: `feat/provider-oauth-account-linking-260913` → `origin/main`
- PR boundary: typed Admin-managed provider OAuth Sections, OAuth attempt persistence, and provider adapter foundation (global link schema migration moves to Phase 2 with its consumers)
- Inputs: approved `identity-260913/REQ`, `identity-260913/ADR-D1..D3`, `identity-260913/DESIGN` revision 1
- Deliverables: M1/M2/M3 backend foundations compile and have focused tests; Admin API and generated Admin clients expose the Sections; no Phase 2 API or Phase 3 Web UI behavior is added
- Non-goals: public start/exchange routes, Web callback page, global link consumer replacement, native URL controls, provider-fake E2E, spec promotion
- Interfaces: System Setting registry/projection contract, OAuth attempt repository/service contract, typed provider identity adapter contract, OAuth attempt schema
- Approved Design mechanisms: `M1`, `M2`, `M3`
- Authority references: `identity-260913/REQ-5`, `identity-260913/REQ-8`, `identity-260913/REQ-9`; `identity-260913/ADR-D1`, `ADR-D2`; current System Settings and External Channel specs
- Design delta: `None`
- Removal obligations: none in Phase 1; global link/origin/candidate removal belongs to Phase 2/3
- Absence verification: Phase 1 proves no provider token/code columns in the attempt model and no raw provider exception/SDK retry logging; legacy candidate/origin references remain intentionally until their owning phases

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| System Settings Sections | Primary agent | `python/apps/azents/src/azents/core/*system_setting*`, registry, Admin service/data/routes, generated Admin surfaces | existing System Settings | Slack/Discord Section definitions, redacted detail, optimistic direct mutation and health | focused Python/Admin API tests; generated client check |
| OAuth attempt foundation | Primary agent | new `core/external_account_oauth.py`, `rdb/models/external_account_oauth.py`, repository/service modules | auth Session and System Setting generation APIs | typed attempt lifecycle with hash-only state, PKCE verifier encryption, live-session/generation claim fence | model/adapter/service tests; migration tests; review of transaction boundary |
| Provider adapters | Primary agent | provider OAuth core module and dependency manifest | existing Slack SDK and Authlib | typed Slack/Discord identity exchange adapters with request-local token boundary | SDK/Authlib-shaped tests, sanitized traceback sentinel, dependency lock update |
| Schema foundation | Primary agent | generated Alembic migration, `db-schemas/rdb/revision` | M1/M2 | System Setting enum values and OAuth attempt table only | migration upgrade/down consistency and schema fingerprint |

- Integration order: System Setting registry → attempt model/repository/service → provider adapters → migration generation/review → OpenAPI/Admin client generation → focused tests
- Independent review: one read-only reviewer reviews only Phase 1 diff against Requirements/ADR/Design M1–M3, migration safety, secret handling, provider adapter correctness, and absence of unauthorized runtime behavior; output is a bounded review report before PR creation
- Final validation: `uv run ruff check`, `uv run ty check --error-on-warning`, focused `pytest` for System Settings/OAuth attempt/provider/migration tests, `uv run python src/cli/dump_openapi.py`, Admin client generation, and `pnpm --filter @azents/admin-client typecheck`
- Scope-drift check: confirm M1–M3 are complete; reject public account-link API/UI, global link schema migration, native URL replacement, legacy route deletion, provider fake E2E, or any new behavior not in Design Authority
- Context checkpoint: Phase 1 completes Sections, attempt state transitions, provider adapter outputs, migration revision, focused test evidence, changed paths, remaining Phase 2–4 scope, and non-blocking provider-library risk
