---
title: "System Settings"
created: 2026-07-19
tags: [backend, frontend, admin, scheduler]
spec_type: domain
domain: system-settings
owner: "@Hardtack"
code_paths:
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
  - /system/v1/settings/file-lifecycle
  - /system/v1/settings/file-lifecycle/archive-retention/preview
  - /system/v1/settings/file-lifecycle/retention-applications/{application_id}
last_verified_at: 2026-07-19
spec_version: 1
---

# System Settings

## Overview

System Settings owns instance-wide, administrator-managed product policy. The current file lifecycle
setting is archived-session retention: how long an archived root `SessionAgent` tree remains
restorable before durable purge may delete it. This setting is stored in the database and is not a
process environment override.

Only a user with a live database-backed `system_admin` role may read, preview, or update these
settings. Public API users and workspace roles have no system-settings authority.

## Archived-session retention policy

`system_file_lifecycle_settings` is a singleton row. A fresh installation starts at 30 whole days.
`archived_session_retention_days` accepts a non-negative integer or null; null means Unlimited. Zero
is valid and means that a newly archived root is eligible for the next asynchronous purge pass. No
settings or archive request performs synchronous permanent deletion.

The row also stores an optimistic `revision`, the latest administrator ID, and timestamps. Every
successful update increments the revision. An archive snapshots the current revision and value on its
root session, so later future-only setting changes do not silently alter that root's deadline.

## Admin API

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

## Preview and confirmation

Before applying `recalculate_existing`, Admin Web calls
`POST /system/v1/settings/file-lifecycle/archive-retention/preview`. Preview is read-only and returns:

- archived roots affected before purge fencing;
- roots whose derived deadline is already due;
- finite purge jobs that would be scheduled or rescheduled;
- purge jobs that would be cancelled by Unlimited retention; and
- roots excluded because purge fencing already started.

Admin Web shows these counts in an explicit confirmation modal. A future-only update does not require
that destructive-impact confirmation because it preserves existing deadlines.

## Durable recalculation

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

## Admin Web contract

Admin Web exposes an Archived session retention page in the authenticated Admin navigation. It shows
the authoritative current value, revision, updater, update time, Unlimited toggle, whole-day input,
and application-scope choice. Save remains disabled for invalid values, unchanged future-only input,
or while a durable application is active.

The page polls an active application every three seconds until completion and renders its durable
status, counters, retry summary, and timestamps. When polling observes completion, it invalidates the
settings query so the authoritative absence of an active application re-enables editing. Reloading the
page resumes the application returned by the settings endpoint.

## Related Specs

- Root archive snapshots, restore, and purge semantics are defined in
  [`conversation.md`](conversation.md).
- Scheduler execution and durable task leases are defined in
  [`../flow/periodic-execution.md`](../flow/periodic-execution.md).
- Owned file cleanup is defined in
  [`../flow/file-exchange-storage.md`](../flow/file-exchange-storage.md).

## Changelog

- **2026-07-19** — v1. Added the database-backed archived-session retention policy, Admin-only optimistic update and preview API, selectable application scope, durable recalculation, and Admin Web progress recovery.
