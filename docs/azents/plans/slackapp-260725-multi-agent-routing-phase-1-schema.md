---
title: "Multi-Agent Slack App Routing Phase 1 Execution Plan"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, implementation, schema, migration]
---

# Multi-Agent Slack App Routing Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `PR 3/10 — Phase 1: App mode and schema foundation`
- Branch/base: `feature/slack-multi-agent-app-schema` → `plan/slack-multi-agent-app`
- PR boundary: Add the durable Single App / Multi App schema and repository foundation without exposing or creating Multi Apps.
- Inputs: Approved `slackapp-260725` Requirements, accepted ADR, approved Design, PR 2 multi-phase implementation plan, existing External Channel schema and repository contracts.
- Deliverables: Immutable connection App mode, backfilled Single App state, mode-constrained Agent associations, catalog availability, provider-interaction admissions, route-neutral conversation admissions, channel defaults, resource-wide active-binding uniqueness, repository DTOs/operations, and focused migration/schema/repository tests.
- Non-goals: Mode-aware event routing, Multi App lifecycle behavior, Slack interaction processing, Multi App management APIs, OpenAPI/client generation, Web UI, living-spec promotion, production data creation, database upgrade/stamp execution, and deployment changes.
- Interfaces: PostgreSQL is canonical; `external_channel_connections.app_mode` is authoritative and immutable; route `connection_app_mode` is a constraint shadow; existing `route_mode` remains for rolling compatibility; route IDs and all retained references are preserved; no public path creates `multi` data.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema/domain/repository foundation | `slack-app-impl-v3` | `python/apps/azents/src/azents/core/enums.py`; `python/apps/azents/src/azents/rdb/models/external_channel.py`; `python/apps/azents/src/azents/repos/external_channel/data.py`; `python/apps/azents/src/azents/repos/external_channel/repository.py`; required existing Single App call sites | Approved persistence design and current schema conventions | Mode/catalog/admission/default domain records, RDB models, constraints, and repository operations | Ruff, whole-project Pyright, focused repository tests |
| Migration and schema verification | `slack-app-impl-v3` | New Alembic revision generated under `python/apps/azents/db-schemas/rdb/migrations/versions/`; `python/apps/azents/db-schemas/rdb/revision`; External Channel model and migration tests | Completed model contract and current migration head | Preflight aborts, Single backfill, named enum/index/FK/trigger constraints, binding-index replacement, safe downgrade boundary | Migration integration tests against PostgreSQL 17; installed-schema metadata tests |
| Focused regression tests | `slack-app-impl-v3` | Existing External Channel repository/service tests only where required by explicit new fields; new Phase 1 tests under `python/apps/azents/src/azents/` | Schema and repository implementation | Identity-preservation, ambiguity-abort, uniqueness, Workspace-boundary, idempotency, secret-exclusion, and old-writer compatibility coverage | Focused Pytest followed by feasible backend test suite |

- Integration order: Define enum and DTO contracts; define RDB models and named constraints; update existing Single App writers with explicit `single` and `available` values; generate the Alembic revision with `uv run alembic revision`; implement preflights/backfills/constraints; add repository operations; add migration/schema/repository tests; run focused checks; run whole-project Pyright and feasible Pytest.
- Independent review: `slack-app-review-v2` performs read-only review after primary verification. Review criteria are migration ambiguity aborts, identity preservation, PostgreSQL constraint fidelity, App-mode immutability, rolling compatibility, Workspace isolation, sender provenance separation, no Multi creation path, and test sufficiency. Output is Critical/Warning findings with exact evidence or an explicit no-findings result.
- Final validation: From `python/apps/azents`, run `uv run ruff check --fix .`, `uv run ruff format .`, `uv run pyright`, focused External Channel and migration tests, and the feasible backend Pytest suite. Run `git diff --check` from the repository root.
- Scope-drift check: Compare the final diff with this plan and PR 3 in the multi-phase plan. Remove routing/lifecycle/interaction-processing/API/UI/spec/deployment changes and confirm no code path can create Multi App data.

## Migration Contracts

The implementation owner must generate, not hand-create, the new Alembic revision.
The migration must abort without selecting or repairing a winner when it finds:

- a connection with zero routes, more than one route, or a non-`dedicated` route;
- a cross-Workspace connection-to-Agent route;
- duplicate `(connection_id, agent_id)` associations; or
- more than one active binding for one resource.

The upgrade preserves every existing connection, route, resource, message, revision,
binding, AgentSession, access request, credential, and retained-history identity. It
backfills all existing connections and routes to `single`, keeps `route_mode`, and
adds no Multi App row.

## Constraint Contracts

- PostgreSQL ENUMs represent App mode, route catalog status, interaction type/status,
  conversation-admission origin/status, and channel-default status.
- A composite foreign key keeps route `(connection_id, connection_app_mode)` equal to
  connection `(id, app_mode)`.
- Unique `(connection_id, agent_id)` preserves one stable association per Agent.
- A partial unique index permits one route for each `single` connection.
- A partial unique index permits one active binding for each resource regardless of
  route.
- Interaction admission is unique by `(connection_id, provider_interaction_key)` and
  stores no raw body, response URL, token, or capability-bearing provider URL.
- One open conversation admission exists per resource.
- One active channel default exists per `(connection_id, provider_channel_id)`, and a
  composite foreign key prevents a cross-App route default.
- Connection App mode cannot be updated after insertion.

## Rollout Gate

PR 3 supplies schema and repository capability only. Agent-scoped setup continues to
create Single Apps. No public API, fixture, migration, background task, or management
service may create a Multi App or a second route. Multi data remains disabled until
PR 4 mode-aware runtime behavior is deployed across the fleet and the later
management phase explicitly opens creation.
