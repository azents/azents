---
title: "Admin-Managed System Configuration Implementation Plan"
created: 2026-07-20
tags: [architecture, backend, frontend, admin, configuration, security, infra, testenv]
---

# Admin-Managed System Configuration Implementation Plan

## Feature Summary

Implement the accepted [Admin-Managed System Configuration Design](./admin-managed-system-configuration.md) and [ADR-0172](../adr/0172-generalize-admin-managed-system-configuration.md) as an instance-scoped, provider-neutral System Settings capability. Platform GitHub App configuration is the first Section and establishes the persistence, secret, candidate, health, audit, environment-overlay, runtime-resolution, and Admin UX contracts reused by future Sections.

## Boundaries

### In scope

- Typed provider-neutral Section registry and lifecycle service.
- PostgreSQL current, candidate, health, audit, and application-migration marker state.
- `CredentialCipher` encryption for current and candidate Admin-managed secrets.
- Live database-backed `system_admin` authorization through the existing protected Admin mount.
- Typed Platform GitHub App Admin API, candidate validation, impact confirmation, health checks, and audit projection.
- Permanent field-level `AZ_GITHUB_PLATFORM_*` environment overlays without copying values into PostgreSQL.
- GitHub App-ID binding for user installations and Platform Toolkit credentials.
- Upgrade-time legacy binding from the existing environment App ID, with explicit claim or reconnect behavior when unavailable.
- Dynamic Public API and Worker resolution at operation boundaries.
- OAuth effective-generation checks and Public Toolkit reconnect-required projection.
- Admin Web System Settings surfaces and Main Web reconnect guidance.
- Dedicated optional Helm `existingSecret` block with independently omitted field bindings.
- Deterministic E2E/testenv validation, optional protected live GitHub coverage, spec promotion, and plan cleanup.

### Out of scope

- Moving PostgreSQL, Redis, object-storage connectivity, credential-encryption roots, JWT material, bootstrap token, topology/endpoints, Runtime Control authentication, Runtime Provider deployment, RBAC, NetworkPolicy, or other deployment trust boundaries into Admin settings.
- Adding `@azents/admin-client` to `typescript/apps/azents-web`.
- Exposing bootstrap token, Admin secret plaintext, secret fingerprints, or effective generation.
- Copying, importing, or materializing environment values into Admin current/candidate state.
- Providing a shadow-fallback preparation API.
- Adding a default Runtime Provider Section in this delivery.
- Automatically selecting a default Runtime Provider when one is registered.
- Redis Pub/Sub, PostgreSQL LISTEN/NOTIFY, or process-local cache as a correctness dependency.
- Retaining replayable setting or secret payload history.
- Managing Kubernetes Secret values, GitOps state, RBAC, or NetworkPolicy through Admin Web.
- Backward-compatible aliases or one-time Helm import behavior for the GitHub environment variables.

## PR Stack

All PRs use the title prefix `Admin-managed system configuration [N/10]`.

### PR 1/10 — Design

Branch: `design/admin-managed-system-configuration`

Contents:

- Accepted provider-neutral architecture and Platform GitHub App first-consumer design.
- ADR-0172 for persistent boundaries, environment overlay policy, secret lifecycle, runtime consistency, and GitHub identity migration.

Validation:

- Documentation frontmatter and generated index.
- Relative-link, whitespace, and repository-boundary consistency checks.

### PR 2/10 — Implementation plan

Branch: `feature/admin-system-settings-plan`

Contents:

- This plan with explicit delivery, validation, prerequisite, rollout, spec, and cleanup boundaries.

Dependencies:

- PR 1/10.

Validation:

- Documentation frontmatter and generated index.
- Markdown diff check.

### PR 3/10 — Provider-neutral foundation

Branch: `feature/admin-system-settings-foundation`

Contents:

- PostgreSQL Section, activation, validation, health, audit, and application-migration enums/tables.
- Alembic-generated schema migration and revision update.
- Typed Section definition/registry contracts.
- Current/candidate/health/audit repositories and DTOs.
- Provider-neutral `SystemSettingsService` lifecycle, optimistic concurrency, advisory locking, schema-version handling, secret encryption/redaction, environment overlay, and HMAC effective generation.
- Generic application-migration runner and marker repository without GitHub data transformation yet.
- Focused repository/service/crypto tests.

Dependencies:

- PR 2/10.

Validation:

- Migration generation and upgrade tests.
- Focused repository/service tests.
- Ruff, Pyright, and relevant backend tests.

### PR 4/10 — Admin API and generated clients

Branch: `feature/admin-system-settings-admin-api`

Contents:

- Platform GitHub App typed Section definition and local validation.
- GitHub external candidate validator, current health checker, sanitized metadata, and impact analysis.
- Protected inventory, detail, patch, candidate validation/confirmation/cancel, health-check, and audit routes.
- Stable conflict and validation response contracts.
- Admin/Public OpenAPI dump as applicable.
- Regenerated Python and TypeScript Admin clients; no generated file is manually edited.
- Route/service tests for authorization, version conflicts, secret actions, candidate lifecycle, impact confirmation, and redaction.

Dependencies:

- PR 3/10.

Validation:

- Admin authorization and route tests.
- Candidate validation classification tests using deterministic GitHub HTTP fixtures.
- OpenAPI dump and Admin Python/TypeScript client regeneration.
- Backend quality checks and generated-client type checks.

### PR 5/10 — GitHub identity binding and legacy migration

Branch: `feature/admin-system-settings-github-binding`

Contents:

- Nullable Platform App ID bindings on `github_user_installations` and encrypted `github_app_platform` Toolkit credentials.
- Explicit partial uniqueness/index changes and Alembic-generated migration.
- App-aware installation synchronization and ownership checks.
- `bind_legacy_platform_github_app_v1` application migration executed only by Public API, Admin API, and Worker entrypoints that receive the overlay.
- Applied/skipped marker behavior, atomic Toolkit decrypt/re-encrypt, corruption failure, and explicit claim/leave-unbound confirmation actions.
- Binding-aware impact counts and reconnect-required domain state.

Dependencies:

- PR 4/10.

Validation:

- Upgrade with valid, absent, empty, and invalid environment App IDs.
- Concurrent migration participant serialization and idempotency.
- Atomic rollback on Toolkit decryption/validation failure.
- App-aware installation synchronization, ownership, claim, and reconnect tests.
- Migration revision and backend quality checks.

### PR 6/10 — Dynamic GitHub runtime cutover

Branch: `feature/admin-system-settings-github-runtime`

Contents:

- Remove Platform GitHub App fields from process-lifetime `Config.github` after migration support is available.
- Resolve Platform settings through `SystemSettingsService` at Public API and Worker operation boundaries.
- Inject the service into `GitHubToolkitProvider` without registry-time secret capture.
- Carry effective generation in encrypted Platform OAuth state and reject changed-generation callbacks before code exchange.
- Compare Toolkit/installations App ID before installation-token exchange and expose no GitHub tools on mismatch.
- Add Public Toolkit authorization-state projection and stable reconnect-required reasons.
- Regenerate Public OpenAPI plus Python and TypeScript Public clients.
- Preserve non-GitHub `Config` inputs and existing Toolkit configuration.

Dependencies:

- PR 5/10.

Validation:

- Public install URL/OAuth and Worker token issuance use operation-boundary resolution.
- OAuth start/callback generation mismatch fails without token exchange.
- App-ID mismatch/null binding fails before external token calls.
- Same-App key/client-secret rotation preserves bindings.
- Public projection is redacted and Main Web still has no Admin-client dependency.
- Backend quality checks, OpenAPI/client generation, and generated-client type checks.

### PR 7/10 — Product surfaces and Helm cutover

Branch: `feature/admin-system-settings-surfaces`

Contents:

- Admin Web System Settings navigation, inventory, Platform GitHub App form, source badges, fallback warnings, secret actions, validation/health state, and impact confirmation.
- Main Web reconnect-required presentation through the Public client only.
- Static stories and component/container tests for meaningful UI states.
- Dedicated `server.platformGitHubApp` Helm block with `existingSecret` and per-field key omission.
- Remove GitHub keys from `azents.serverAuthSecretEnv`; inject the dedicated helper only into Public API, Admin API, and Worker.
- Update Helm schema, README, NOTES, render tests, and affected ArgoCD consumer values with whole-object replacement awareness.

Dependencies:

- PR 6/10.

Validation:

- TypeScript format, lint, typecheck, relevant tests, Storybook coverage, and builds.
- Assert Main Web dependency graph excludes `@azents/admin-client`.
- Helm disabled/full/mixed-field render matrix and schema validation.
- Verify Scheduler has no Platform GitHub App Secret references.

### PR 8/10 — E2E and testenv validation

Branch: `test/admin-system-settings-validation`

Contents:

- Deterministic browser/API/Worker E2E coverage for the complete user-visible matrix.
- Testenv fixture, restart, migration, provider-response, Redis-outage, and secret-sentinel support.
- Optional protected live GitHub App smoke coverage and prerequisite snapshot rules.
- Validation report with commands, environment, results, sanitized evidence, failures, fixes, and strict implementation/spec comparison.
- Defect fixes discovered by validation, kept within this phase unless an earlier phase must be amended and the stack rebased.

Dependencies:

- PR 7/10.

Validation:

- Full planned deterministic E2E matrix.
- Backend and TypeScript quality suites.
- OpenAPI/generated-client drift checks.
- Helm render matrix.
- Optional live scenario pass/fail/skip policy.

### PR 9/10 — Spec promotion

Branch: `docs/admin-system-settings-spec-promotion`

Contents:

- Run `/spec-review` against the complete implementation stack.
- Add the System Settings living domain spec.
- Update Toolkit spec for Platform App binding, runtime resolution, and reconnect projection.
- Update User/Auth spec only for the existing `system_admin` authorization relationship and preserved bootstrap/final-admin boundaries.
- Update operator/Helm documentation for the dedicated GitHub Secret block and environment/Admin handoff.
- Mark the design implemented only after PR 8/10 validation evidence is complete.
- Keep ADR-0172 immutable.

Dependencies:

- PR 8/10.

Validation:

- Documentation frontmatter and generated indexes.
- Strict spec-to-code path and behavior comparison.
- Spec review findings resolved.

### PR 10/10 — Cleanup

Branch: `docs/admin-system-settings-cleanup`

Contents:

- Remove this temporary implementation plan.
- Remove only stale plan references made obsolete by promoted specs.
- Retain ADR-0172, implemented design, validation report, living specs, and code.

Dependencies:

- PR 9/10.

Validation:

- Documentation validation.
- Clean diff limited to lifecycle cleanup.

## Data, API, and Runtime Changes by Phase

| Area | Foundation | Admin API | Binding | Runtime | Surfaces |
|---|---|---|---|---|---|
| System Settings tables | Add | Read/write | Reuse | Read | Display |
| Platform GitHub App typed Section | Registry contract | Define/validate | Impact/claim | Resolve | Manage |
| Current/candidate secrets | Encrypt/redact | Mutate/activate | No copy | Consume | Replace/clear UI |
| Environment overlay | Resolve/source | Enforce read-only | Migration App ID | Runtime input | Source/fallback UI + Helm |
| GitHub installation binding | — | Impact preview | Persist/migrate | Enforce | Reconnect UX |
| OAuth effective generation | Generate service value | Internal only | — | Persist/compare | Error presentation |
| Generated clients | — | Admin | — | Public | Consume |
| Living specs | Candidate list only | Deferred | Deferred | Deferred | Deferred to PR 9 |

## E2E Primary Validation Matrix

| Scenario | Surface | Credential mode | Primary assertion | Required support |
|---|---|---|---|---|
| Fresh bootstrap and inventory | Admin Web/API | none | Section is not configured; bootstrap/final-admin boundaries remain intact | Existing Admin bootstrap fixture |
| Admin-managed configuration | Admin Web/API + Public API + Worker | deterministic or live | Candidate validates/activates; OAuth and token issuance use DB base | GitHub provider fixture/live App |
| Full environment ownership | Admin/API/Worker | controlled env | Fields are source-visible, read-only, and not persisted | Restartable multi-process fixture |
| Mixed ownership | Admin/API/Worker | env + Admin | Complete effective Section validates and operates consistently | Per-process env fixture |
| Present-empty overlay | Admin/API/Worker | empty env field | Field stays environment-owned and fails closed without DB fallback | Raw env presence control |
| Environment removal with fallback | restart matrix | env then remove | Stored Admin fallback becomes effective after all consumers restart | Restart orchestration |
| Environment removal without fallback | restart matrix | env then remove | Section becomes explicitly incomplete/unconfigured | Restart orchestration |
| App ID change | Admin + Main Web | two Apps or deterministic identities | Impact confirmation; existing Toolkits remain stored and become reconnect-required | Two-App fixture or controlled provider |
| Same-App credential rotation | Admin + Worker | rotated key/secret | Existing bindings remain usable | Deterministic signer/token fixture |
| Upgrade with env App ID | startup migration | encrypted legacy fixture | Legacy rows and Toolkit credentials bind atomically and idempotently | Pre-upgrade DB snapshot |
| Upgrade without env App ID | startup migration | encrypted legacy fixture | Skipped marker; resources remain unbound until claim/reconnect | Pre-upgrade DB snapshot |
| Migration corruption | startup migration | malformed ciphertext | Startup fails and no partial rows/marker commit | Corrupt encrypted fixture |
| OAuth settings change mid-flow | Public API | controlled mutation | Callback returns `system_setting_changed` before code exchange | Exchange-call spy |
| Concurrent Admin mutations | Admin API | none | One version wins; stale mutation/confirmation returns stable `409` | Parallel API helper |
| Unauthorized access | Admin API | ordinary User/Workspace OWNER | `403`; no setting metadata disclosed | Multi-role auth fixture |
| Secret redaction | API/log/audit/report | sentinel secrets | Sentinel is absent from every output/evidence channel | Log/audit/response scanner |
| Redis unavailable | API/Worker | controlled outage | Settings remain PostgreSQL-correct | Redis fault control |
| Helm disabled/full/mixed | Helm render | Secret references | Exact env references and consumer set; Scheduler excluded | Helm test matrix |

## Fixture and Prerequisite Support

### Deterministic test support

- A fake GitHub HTTP boundary must classify authenticated App lookup, OAuth credential rejection, user installation listing, installation token issuance, provider outage, and rate limit outcomes without external network access.
- Testenv must be able to restart Public API, Admin API, and Worker with controlled per-field environment presence, including explicit empty strings.
- Pre-upgrade PostgreSQL snapshots must contain legacy user-installation rows and encrypted Platform Toolkit credentials generated through the product cipher contract.
- Worker verification must exercise a Platform Toolkit token/tool path rather than only inspect stored data.
- A provider exchange-call spy must prove generation and App-binding failures happen before external token exchange.
- Secret sentinel scanning must cover API responses, application logs, structured events, audit projections, validation reports, and browser screenshots/artifacts.
- Redis fault injection is required only to demonstrate that settings correctness does not depend on Redis; it must not disable unrelated worker infrastructure needed by the test harness.

### Optional live GitHub prerequisite

- A dedicated non-production GitHub App with approved displayable App ID/slug and at least one test installation.
- Protected CI credentials for private key and client secret; values are never printed or attached.
- A disposable test user authorization path and repository/account identifiers approved for sanitized evidence.
- Explicit workflow opt-in or protected label so normal PR CI remains deterministic.
- Cleanup/revocation behavior for temporary user OAuth and installation tokens.

Missing optional live credentials produce SKIP. Present but invalid credentials, a missing declared installation, or a failed configured live environment produce FAIL.

## Test Strategy by Phase

### Foundation

- Repository locking, version conflict, row absence/version zero, candidate replacement/expiry, health generation matching, audit redaction, and migration markers.
- Secret action semantics, ciphertext replacement/deletion, plaintext exclusion, overlay precedence, present-empty behavior, canonical generation stability, and schema-version failure.
- Direct/validated/confirmed activation transitions and unexpected error propagation.

### Admin API

- Live `system_admin` authorization and bootstrap/debug/final-admin regression coverage.
- Typed request/response models, environment-owned write conflict, local `422`, stable `409`, external invalid/unavailable candidate state, retry/cancel/confirm, pagination, and redaction.
- GitHub App JWT/App identity validation and OAuth client credential classification with sanitized provider responses.

### Binding and runtime

- Partial unique indexes, App-aware sync/delete, ownership, claim, reconnect, and encrypted credential migration.
- Operation-boundary reads, coherent per-operation snapshots, OAuth generation mismatch, App mismatch before token exchange, and same-App rotation.
- No runtime fallback to removed `Config.github` values.

### Product surfaces and Helm

- Admin inventory/form state ADTs, source badges, fallback warnings, secret actions, validation/health, candidate expiry, and impact confirmation.
- Main Web reconnect-required reason display through Public client only.
- Helm schema/lint/render tests for no block, all fields, every individual omitted key, and mixed ownership.

### Validation

- Full deterministic E2E matrix plus optional live smoke.
- Backend Ruff, Pyright, and full/focused Pytest.
- TypeScript format, lint, typecheck, test, and affected builds.
- OpenAPI dump and all generated clients reproducible without manual edits.
- Documentation validation and strict spec comparison.

## External and Manual Blockers

| Blocker | Blocking phase | Policy |
|---|---|---|
| Protected live GitHub App credentials unavailable | Optional part of PR 8 | Record SKIP; deterministic validation remains required |
| Helm binary unavailable in a developer environment | Local surface validation | Use repository CI image; configured CI absence is a failure |
| Current deployment consumer values are not available in this repository | PR 7 rollout evidence | Update in-repo ArgoCD consumers and document external consumer action |
| Migration fixture cannot decrypt with the test root | PR 5 | Block the phase until fixture is regenerated through product code; never hand-edit ciphertext |
| GitHub provider behavior differs from documented deterministic classification | PR 4 or 8 | Preserve sanitized typed failure, update deterministic fixture, and require live evidence before completion |

No manual Kubernetes writes are required to implement the repository stack. Live-cluster changes require separate explicit approval.

## Spec Impact Candidates

- New `docs/azents/spec/domain/system-settings.md` for implemented Sections, persistence, lifecycle, source resolution, API, redaction, and runtime behavior.
- `docs/azents/spec/domain/toolkit.md` for Platform App ID binding, App-aware ownership, reconnect-required projection, and token resolution.
- `docs/azents/spec/domain/user-auth.md` for System Settings' use of the existing live `system_admin` boundary only.
- Helm/operator documentation for the dedicated Platform GitHub App Secret block and explicit environment/Admin handoff.
- Existing historical GitHub design documents remain historical; current behavior is promoted to living specs.

## Rollout and Recovery

- Apply schema migrations before any new application process serves System Settings-dependent operations.
- Public API, Admin API, and Worker race safely through the same GitHub binding migration marker and advisory lock.
- Existing deployments with the old GitHub keys in the core auth Secret must move the Secret reference to `server.platformGitHubApp` during the Helm cutover.
- The four `AZ_GITHUB_PLATFORM_*` names remain stable; only their resolver and Helm Secret surface change.
- Removing an environment binding reveals the stored Admin base after all relevant processes restart. Without a fallback, operators plan an unconfigured maintenance interval and then submit Admin values.
- Candidate activation never deletes current state before validation/confirmation succeeds.
- An App ID change preserves Toolkit configuration and installation records for reconnect; recovery does not require destructive cleanup.
- A failed legacy binding migration rolls back data and marker and prevents participating consumers from serving.
- Rollback to a pre-System-Settings application is not a supported mixed-runtime target after Phase 4 removes `Config.github`; deployment rollback must restore a compatible application/database/chart set.

## Cleanup

After implementation, validation, and spec promotion:

- set the design's `implemented` date to the validated completion date only after validation is complete;
- delete this temporary implementation plan in PR 10/10;
- retain ADR-0172, the implemented design, validation report, living specs, and tested code as the source of truth;
- do not merge any PR in the stack without explicit user approval.
