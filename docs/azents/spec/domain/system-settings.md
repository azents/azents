---
title: "System Settings"
created: 2026-07-19
updated: 2026-07-20
tags: [backend, frontend, admin, scheduler, security, infra]
spec_type: domain
domain: system-settings
owner: "@Hardtack"
code_paths:
  - python/apps/azents/src/azents/core/system_setting.py
  - python/apps/azents/src/azents/core/github_system_setting.py
  - python/apps/azents/src/azents/api/admin/system_setting/**
  - python/apps/azents/src/azents/services/system_setting/**
  - python/apps/azents/src/azents/services/github_platform_system_setting/**
  - python/apps/azents/src/azents/repos/system_setting/**
  - python/apps/azents/src/azents/repos/github_platform_system_setting/**
  - python/apps/azents/src/azents/rdb/models/system_setting.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/ec609e0da8ab_add_system_settings_foundation.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/8842bd30d5c6_bind_github_resources_to_platform_app_.py
  - typescript/apps/azents-admin-web/src/app/system-settings/**
  - typescript/apps/azents-admin-web/src/features/system-settings/**
  - typescript/apps/azents-admin-web/src/trpc/routers/systemSettings.ts
  - infra/charts/azents/templates/server/apiserver-deployment.yaml.tpl
  - infra/charts/azents/templates/server/adminserver-deployment.yaml.tpl
  - infra/charts/azents/templates/server/worker-deployment.yaml.tpl
  - infra/charts/azents/values.yaml
  - infra/charts/azents/values.schema.json
  - python/apps/azents/src/azents/api/admin/system/v1/**
  - python/apps/azents/src/azents/services/archived_session_retention.py
  - python/apps/azents/src/azents/repos/archived_session_retention/**
  - python/apps/azents/src/azents/rdb/models/archived_session_retention.py
  - python/apps/azents/src/azents/scheduler/registry.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/653ef7db49af_add_archived_session_retention_.py
  - typescript/apps/azents-admin-web/src/app/retention/**
  - typescript/apps/azents-admin-web/src/features/retention/**
  - typescript/apps/azents-admin-web/src/trpc/routers/retention.ts
api_routes:
  - /system-setting/v1/sections
  - /system-setting/v1/sections/platform-github-app
  - /system-setting/v1/sections/platform-github-app/candidate/validate
  - /system-setting/v1/sections/platform-github-app/candidate/confirm
  - /system-setting/v1/sections/platform-github-app/candidate
  - /system-setting/v1/sections/platform-github-app/health-check
  - /system-setting/v1/audit-events
  - /system/v1/settings/file-lifecycle
  - /system/v1/settings/file-lifecycle/archive-retention/preview
  - /system/v1/settings/file-lifecycle/retention-applications/{application_id}
last_verified_at: 2026-07-20
spec_version: 2
---

# System Settings

## Overview

System Settings owns instance-wide, administrator-managed product configuration and policy. Two
independent setting families currently use this domain:

- the provider-neutral Section lifecycle, whose first compiled Section is the Platform GitHub App;
- archived-session retention under the file-lifecycle API.

Only a user with a live database-backed `system_admin` assignment may read or mutate either family.
Public API users, Workspace roles, environment configuration, and UI visibility never grant System
Settings authority.

## Provider-neutral Section lifecycle

### Registry and persistence

A compiled `SystemSettingRegistry` defines every typed Section. A definition declares the Section key,
schema version, separate Pydantic config and secret models, activation mode, environment bindings,
candidate TTL, local validator, and any in-memory payload migrations needed to read older schema
versions. The first and currently only definition is `platform_github_app`, schema version 1, with
confirmed activation and a 24-hour candidate TTL.

PostgreSQL is the correctness source. The lifecycle uses these tables:

- `system_settings`: one current Admin-managed base row per Section, with optimistic version, encrypted
  secret payload, secret metadata, activation validation metadata, updater, and timestamps;
- `system_setting_candidates`: at most one pending candidate per Section, including base version,
  encrypted candidate secrets, validation result, redacted impact, and expiry;
- `system_setting_health`: the latest explicit health result for one effective generation;
- `system_setting_audit_events`: append-only metadata events for candidate replacement, validation,
  cancellation, activation, and health checks; and
- `system_data_migrations`: durable outcome markers for one-time application data migrations.

Secrets use the deployment-rooted `CredentialCipher`. Current and candidate ciphertext is never
returned through Admin or Public APIs. Audit events record field names and `replace`/`clear` actions,
not plaintext, ciphertext, or comparable fingerprints. Cancelling or expiring a candidate deletes its
ciphertext.

Each resolution computes an internal HMAC-based effective generation over the complete typed effective
payload. The generation fences validation, confirmation, health checks, OAuth callbacks, and runtime
operations, but it is never exposed through API responses or UI.

### Admin base and environment overlays

The Admin-managed row is the durable fallback. A configured environment binding overrides only its
bound field for the process that resolves the Section. Precedence is determined by environment-variable
presence, including an explicitly present empty string; truthiness is not used. Environment values are
never copied into PostgreSQL.

A field projection reports `admin`, `environment`, or `unset`, the environment-variable name, whether
an Admin fallback exists, and when that fallback last changed. Secret field values are always omitted.
An environment-owned field is read-only through the Admin mutation API, but an obscured Admin fallback
remains stored so it can become effective after the environment binding is removed and all relevant
processes restart.

PostgreSQL is read at each operation boundary. Redis, process-local cache, and notification delivery are
not required for correctness.

### Mutation, validation, and confirmation

A patch requires `expected_version`. Omitted fields remain unchanged; explicit null on a non-secret
field clears the Admin fallback. Secret fields require an explicit `replace` or `clear` action object.
A stale Admin version or an attempted write to an environment-owned field returns a stable `409`
response.

A non-direct Section mutation replaces the previous candidate and stores the complete proposed Admin
base. Platform GitHub App validation runs immediately after patch and may be retried. Candidate status
is `pending`, `valid`, `invalid`, or `unavailable`. External validation results contain only sanitized
codes, messages, action hints, metadata, and aggregate impact.

A valid candidate activates immediately when no confirmation is required. Otherwise confirmation must
supply the unchanged candidate ID, Admin version, and one of the candidate's allowed confirmation
actions. Confirmation rechecks candidate expiry, Admin version, effective generation, and aggregate
impact inside the serialized Section transaction. Drift returns `409` and requires reload or
revalidation. Successful activation increments the Admin version, replaces current ciphertext, deletes
the candidate, and appends a metadata-only audit event.

### Health and audit

Health checks validate the current effective Section without mutating the Admin base. A result is stored
only if the effective generation is unchanged and has status `healthy`, `invalid`, or `unavailable`.
A health row from another effective generation is ignored. The audit list is paginated and may include
Admin API, application-migration, or system sources; it never exposes effective generations or secret
material.

## Platform GitHub App Section

### Fields and effective status

The Section contains four required fields:

| Field | Secret | Environment binding |
| --- | --- | --- |
| `app_id` | no | `AZ_GITHUB_PLATFORM_APP_ID` |
| `client_id` | no | `AZ_GITHUB_PLATFORM_CLIENT_ID` |
| `private_key` | yes | `AZ_GITHUB_PLATFORM_PRIVATE_KEY` |
| `client_secret` | yes | `AZ_GITHUB_PLATFORM_CLIENT_SECRET` |

The App ID must contain ASCII digits. The private key must be an unencrypted RSA PEM key. External
validation verifies the App identity and OAuth client credentials. The redacted detail status is
`not_configured`, `incomplete`, `invalid`, `ready`, `unavailable`, or `reconnect_required`.

A Platform App identity change reports only aggregate counts for affected Users, installations,
Toolkits, and Agents. On upgrade, the durable application migration binds previously unbound legacy
installations and Platform Toolkits only when `AZ_GITHUB_PLATFORM_APP_ID` is present. When the first
Admin-managed App ID encounters remaining unbound legacy resources, confirmation can either atomically
claim them for that App or leave them unbound. A later App ID change preserves existing resources and
activates only after explicit impact confirmation; affected Toolkits then require reconnect.

Changing only the private key, client ID, or client secret while retaining the same App ID preserves
identity bindings.

### Admin API and Admin Web

`GET /system-setting/v1/sections` returns the registry-driven redacted inventory. Platform GitHub App
detail, patch, candidate validation/confirmation/cancellation, current-effective health check, and
metadata-only audit list are exposed beneath `/system-setting/v1`.

Admin Web exposes System Settings in authenticated Admin navigation. It renders inventory and Platform
GitHub App detail, field source and fallback state, explicit secret actions, candidate validation and
health state, aggregate binding impact, and confirmation choices. It never renders secret plaintext,
effective generations, or resource identifiers from impact analysis.

### Helm and process delivery

The Helm chart's optional `server.platformGitHubApp.existingSecret` block maps the four environment
bindings to consumer-owned Secret keys. No Platform GitHub App secret literal is present in chart
defaults. Selected keys are injected into Public API, Admin API, and Worker only; Scheduler receives no
Platform GitHub App Secret reference. An empty `server.platformGitHubApp.*Key` value leaves that field
under Admin-managed database control, while a non-empty Secret key permanently owns the field for the
receiving processes until the key value is cleared and those processes restart.

## Archived-session retention policy

`system_file_lifecycle_settings` is a singleton row. A fresh installation starts at 30 whole days.
`archived_session_retention_days` accepts a non-negative integer or null; null means Unlimited. Zero
is valid and means that a newly archived root is eligible for the next asynchronous purge pass. No
settings or archive request performs synchronous permanent deletion.

The row also stores an optimistic `revision`, the latest administrator ID, and timestamps. Every
successful update increments the revision. An archive snapshots the current revision and value on its
root session, so later future-only setting changes do not silently alter that root's deadline.

### Admin API

`GET /system/v1/settings/file-lifecycle` returns the current settings and the oldest active durable
recalculation application, if one exists. Returning the application with settings lets Admin Web
recover progress after reload rather than relying on browser-local mutation state.

`PATCH /system/v1/settings/file-lifecycle` requires:

- `expected_revision` for optimistic concurrency;
- the new whole-day value or null for Unlimited; and
- `application_scope`, either `new_archives_only` or `recalculate_existing`.

A stale revision returns `409 retention_revision_conflict`. A second update while an existing-archive
application is pending, running, or waiting to retry returns
`409 retention_application_in_progress`. Invalid negative or fractional values are rejected by the
request schema and service boundary.

`new_archives_only` commits the new revision without rewriting existing archive snapshots or purge
jobs. `recalculate_existing` commits the new revision and creates one durable application in the same
transaction. At most one recalculation application may be active.

### Preview and confirmation

Before applying `recalculate_existing`, Admin Web calls
`POST /system/v1/settings/file-lifecycle/archive-retention/preview`. Preview is read-only and returns:

- archived roots affected before purge fencing;
- roots whose derived deadline is already due;
- finite purge jobs that would be scheduled or rescheduled;
- purge jobs that would be cancelled by Unlimited retention; and
- roots excluded because purge fencing already started.

Admin Web shows these counts in an explicit confirmation modal. A future-only update does not require
that destructive-impact confirmation because it preserves existing deadlines.

### Durable recalculation

A recalculation application snapshots its target revision and retention value. It stores status,
stable root cursor, cumulative affected/immediately-eligible/scheduled/cancelled/skipped counts,
attempt count, lease ownership, next retry time, bounded error summary, requester, and timestamps.
Status is `pending`, `running`, `retry_wait`, or `completed`.

The scheduler claims one application with an expiring lease and processes at most 100 archived roots
per pass in stable ID order. For each root that has not entered purge fencing, it derives the new
`purge_after` from the original `archived_at`, replaces the root's policy snapshot, and creates,
reschedules, or cancels unstarted purge work. Unlimited clears the deadline. A finite deadline in the
past becomes scheduler-eligible but is not deleted by recalculation. Fenced roots are counted as
skipped and never moved back to a reversible state.

Failure releases the application into bounded exponential retry wait. Completion is durable and
queryable through
`GET /system/v1/settings/file-lifecycle/retention-applications/{application_id}`. Missing IDs return
404.

### Admin Web contract

Admin Web exposes an Archived session retention page in the authenticated Admin navigation. It shows
the authoritative current value, revision, updater, update time, Unlimited toggle, whole-day input,
and application-scope choice. Save remains disabled for invalid values, unchanged future-only input,
or while a durable application is active.

The page polls an active application every three seconds until completion and renders its durable
status, counters, retry summary, and timestamps. When polling observes completion, it invalidates the
settings query so the authoritative absence of an active application re-enables editing. Reloading the
page resumes the application returned by the settings endpoint.

## Related Specs

- Platform Toolkit identity binding, runtime token resolution, and reconnect projection are defined in
  [`toolkit.md`](toolkit.md).
- System administrator authentication and role invariants are defined in
  [`user-auth.md`](user-auth.md).
- Root archive snapshots, restore, and purge semantics are defined in
  [`conversation.md`](conversation.md).
- Scheduler execution and durable task leases are defined in
  [`../flow/periodic-execution.md`](../flow/periodic-execution.md).
- Owned file cleanup is defined in
  [`../flow/file-exchange-storage.md`](../flow/file-exchange-storage.md).

## Changelog

- **2026-07-20** — v2. Added the provider-neutral typed Section lifecycle, encrypted current/candidate
  persistence, field-level environment precedence, Platform GitHub App validation and impact
  confirmation, metadata-only health/audit projections, Admin Web contract, and dedicated Helm Secret
  delivery.
- **2026-07-19** — v1. Added the database-backed archived-session retention policy, Admin-only
  optimistic update and preview API, selectable application scope, durable recalculation, and Admin Web
  progress recovery.
