---
title: "Multi-Agent Slack App Routing Phase 1 Execution Plan"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, implementation, schema, migration]
---

# Multi-Agent Slack App Routing Phase 1 Execution Plan

## Phase Boundary

- Phase: `PR 3/10 — Phase 1: App mode and schema foundation`
- Branch/base: `feature/slack-multi-agent-app-schema` → `plan/slack-multi-agent-app`
- PR boundary: Add the durable Single App / Multi App schema and repository foundation without exposing or creating Multi Apps through any product, public API, service, background task, migration, or deterministic testenv path.
- Primary source decisions: `slackapp-260725/ADR-D1`, `ADR-D2` persistence only, `ADR-D5`, `ADR-D6` durable storage only, and `ADR-D7` additive-schema phase.
- Primary requirement coverage: schema and migration foundations for `REQ-2`, `REQ-9`, `REQ-12`, and `REQ-13`. Later phases own observable routing, lifecycle, interaction, API, and UI behavior.
- Deliverables: Immutable connection App mode; backfilled Single App state; mode-constrained Agent associations; catalog availability; bounded provider-interaction admissions; route-neutral conversation admissions; channel defaults; resource-wide active-binding uniqueness; repository DTOs and operations; and complete migration, installed-schema, repository, and compatibility tests.
- Non-goals: Mode-aware event routing; Multi App lifecycle behavior; Slack interaction parsing or processing; Multi App management APIs; OpenAPI or generated clients; Web UI; living-spec promotion; production data creation; database upgrade or stamp execution; and deployment changes.

## Mandatory Source Read and Traceability Gate

Before editing implementation files, the implementation owner must read these files in full:

- `docs/azents/requirements/slackapp-260725-multi-agent-routing.md`
- `docs/azents/adr/slackapp-260725-multi-agent-routing.md`
- `docs/azents/design/slackapp-260725-multi-agent-routing.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-implementation-plan.md`
- this Phase Execution Plan

The implementation owner must maintain a working checklist that maps every acceptance ID in this plan to an implementation path, a test path, and final evidence. A progress report is not a completion report. The owner returns control only when every acceptance ID is implemented and validated, or when one concrete blocker prevents further work.

The primary agent independently verifies the completed checklist and diff before assigning the independent reviewer. The independent reviewer does not review an acknowledged partial implementation.

## Ownership and Paths

| Workstream | Owner | Required paths | Output |
| --- | --- | --- | --- |
| Domain and repository foundation | `slack-app-impl-v3` | `python/apps/azents/src/azents/core/enums.py`; `python/apps/azents/src/azents/rdb/models/external_channel.py`; `python/apps/azents/src/azents/repos/external_channel/data.py`; `python/apps/azents/src/azents/repos/external_channel/repository.py`; required existing Single App writers | Enums, DTOs, models, named constraints, validation boundaries, and repository operations |
| Migration and installed schema | `slack-app-impl-v3` | one generated revision under `python/apps/azents/db-schemas/rdb/migrations/versions/`; `python/apps/azents/db-schemas/rdb/revision`; External Channel schema tests | Preflight failures, backfill, constraints, triggers, downgrade guards, and ORM/migration parity |
| Focused regression evidence | `slack-app-impl-v3` | `python/apps/azents/src/azents/rdb/external_channel_app_mode_migration_test.py`; `python/apps/azents/src/azents/rdb/models/external_channel_test.py`; `python/apps/azents/src/azents/repos/external_channel/repository_test.py`; only directly affected existing Single App tests | Identity preservation, ambiguity rejection, boundary enforcement, idempotency, secret exclusion, and old-writer compatibility |
| Independent review | `slack-app-review-v2` | read-only access to the final diff and all five source documents | Critical/Warning findings with exact evidence, or an explicit no-findings result |

The implementation owner does not create child agents, commit, push, edit PRs, run configured or shared database migrations, modify Kubernetes, or start later phases.

## Acceptance Matrix

### P1-D1 — Connection App mode

Implementation:

- Add PostgreSQL enum `external_channel_app_mode` with `single` and `multi`.
- Add `external_channel_connections.app_mode` with a `single` server default for rolling old-writer compatibility.
- Backfill every existing connection to `single`.
- Make App mode immutable after insertion with a named PostgreSQL trigger and function.
- Add a unique connection `(id, app_mode)` key for route mode-shadow enforcement.
- Existing Agent-scoped connection creation explicitly creates `single`; no product path creates `multi`.

Required tests:

- An old SQL writer omitting `app_mode` creates `single`.
- Repository/service Single App writers create `single` explicitly.
- Updating `single` to `multi` and `multi` to `single` fails at the database boundary.
- No product, public API, service, background task, migration, or deterministic testenv fixture creates `multi`.

### P1-D2 — Stable Agent route association and mode constraints

Implementation:

- Add route `connection_app_mode`, `catalog_status`, `catalog_removed_at`, and `catalog_removed_by_user_id`.
- Backfill existing routes to `connection_app_mode = single` and `catalog_status = available` while preserving `route_mode`.
- Add unique `(connection_id, agent_id)` and unique `(connection_id, id)`.
- Add partial unique `connection_id` where `connection_app_mode = 'single'`.
- Add the composite route-to-connection mode-shadow foreign key.
- `create_agent_route` locks the connection, reloads the Agent, requires the supplied shadow to equal authoritative connection mode, and rejects cross-Workspace Agents before insert.
- New route inserts retain `route_mode = dedicated`; the reserved `platform` value is not used to represent either App mode.
- A newly inserted route must use `catalog_status = available` with null catalog-removal timestamp and administrator provenance. Re-enabling a preserved removed route is a later lifecycle operation, not a new-route insert.
- Route creation does not infer ownership or execution User from provider principals or administrators.

Required repository and constraint tests:

- Valid Single route creation succeeds.
- App-mode shadow mismatch fails before insert.
- Cross-Workspace Agent association fails before insert.
- A new route using reserved `route_mode = platform` fails before insert.
- Removed status or non-null catalog-removal metadata on a new route fails before insert.
- Duplicate `(connection_id, agent_id)` fails.
- A second Single route fails.
- Multiple routes for an internally seeded Multi connection succeed when Agents are distinct and in the same Workspace.
- An old SQL writer omitting new route fields receives `single` and `available` defaults.

### P1-D3 — Bounded provider-interaction admission

Implementation:

- Add interaction type and status enums and `external_channel_interactions`.
- Enforce unique `(connection_id, provider_interaction_key)`.
- `admit_interaction` inserts once and returns the existing first admission on retry without overwriting its projection or metadata.
- Interaction projection validation is fail-closed before persistence:
  - canonical JSON is at most 16 KiB UTF-8;
  - maximum nesting depth is 4;
  - each mapping or array contains at most 64 entries;
  - keys are at most 128 characters and scalar strings at most 2,048 characters;
  - binary values are rejected; and
  - case-insensitive normalized keys containing `token`, `secret`, `authorization`, `cookie`, `response_url`, `raw_body`, or `payload`, and keys ending in `url` or `uri`, are rejected.
- String values that look like an absolute HTTP/Slack URL, Slack token, cookie, or Authorization credential are rejected even under an otherwise safe key.
- Projection string values and provider/callback/action/resource-correlation identifiers must use a bounded opaque-identifier character set rather than free-form prose.
- Initial admission requires status `accepted` with null error fields. Later status/error transitions belong to the interaction-processing phase and must use their own safe mutation boundary.
- Raw provider bodies, response URLs, tokens, authorization values, cookies, Slack message text, file bytes, and capability-bearing provider URLs are not stored.
- When a principal is supplied, repository validation requires provider and tenant compatibility with the connection.

Required tests:

- First admission returns `created = true`; identical retry returns the same ID with `created = false`.
- A retry with conflicting projection cannot overwrite the first durable projection.
- Exact-size/depth/entry/string boundaries pass and one-over-boundary values fail.
- Every forbidden key category fails recursively and no forbidden value reaches the stored row.
- Safe-key URL/token/raw-text values and scalar-field URL/token/raw-text values fail before insert.
- Non-`accepted` initial status and non-null initial error fields fail before insert.
- Cross-provider or cross-tenant principal association fails.

### P1-D4 — Route-neutral conversation admission

Implementation:

- Add conversation-admission origin and status enums and `external_channel_conversation_admissions`.
- Enforce one open admission per resource for `pending_selection`, `selected`, and `awaiting_access`.
- Add unique `(connection_id, id)` on resources and interactions and unique
  `(resource_id, id)` on messages so PostgreSQL can enforce the complete boundary.
- Enforce named composite foreign keys for:
  - admission `(connection_id, resource_id)` → resource `(connection_id, id)`;
  - admission `(resource_id, source_message_id)` → message `(resource_id, id)`;
  - admission `(connection_id, selected_route_id)` → route `(connection_id, id)`; and
  - admission `(connection_id, interaction_id)` → interaction `(connection_id, id)`.
- When `initiating_principal_id` is present, repository validation requires the principal provider and tenant to match the receiving connection.
- The repository validates every immutable owner boundary before attempting the idempotent insert. An existing open-resource conflict must not suppress a cross-connection, cross-resource, cross-message, cross-route, cross-interaction, or cross-principal mismatch through `ON CONFLICT DO NOTHING`.
- `create_conversation_admission_idempotent` returns the existing open admission for a retry and never changes its original source, principal, origin, selection, or interaction.
- A terminal admission may coexist with a later open admission; two open admissions may not.

Required tests:

- Retry returns the same open admission ID and preserves the first payload.
- Each open status participates in the partial uniqueness fence.
- A terminal row permits a later open admission.
- Cross-connection resource, cross-resource source message, cross-connection selected route, and cross-connection interaction each fail without selecting a winner.
- Cross-provider or cross-tenant initiating principal fails.
- Repeat every owner-boundary attack after a valid open admission already exists and prove the idempotent conflict path still rejects it rather than returning the existing admission.

### P1-D5 — Channel-default persistence boundary

Implementation:

- Add channel-default status enum and `external_channel_channel_defaults`.
- Enforce one active default per `(connection_id, provider_channel_id)`.
- Enforce composite `(connection_id, route_id)` ownership.
- `create_channel_default` follows connection → route lock order. The route lock query is scoped by both requested route ID and the already locked connection ID so a cross-connection request never locks a foreign route. Creation requires:
  - authoritative connection mode `multi`;
  - route connection and route mode shadow matching the connection;
  - route catalog status `available`;
  - active Agent lifecycle;
  - Agent Workspace matching connection Workspace; and
  - creation status `active` with no invalidation metadata.
- Authentication and Workspace permission checks remain later management-service work; the repository accepts only the authenticated Azents User ID supplied by that future boundary and never derives it from Slack provenance.

Required tests:

- A valid internally seeded Multi connection and available active route can create a default.
- Single connection, cross-connection route, mode-shadow mismatch, cross-Workspace Agent, removed route, inactive Agent, invalidated creation, and invalidation metadata on active creation each fail.
- A duplicate active default for the same connection/channel fails; a terminal invalidated history row may coexist as designed.

### P1-D6 — Resource-wide active binding uniqueness

Implementation:

- Preflight existing data before replacing the current partial unique index.
- Replace active `(resource_id, route_id)` uniqueness with one active binding per `resource_id`, independent of route.
- Preserve every existing binding ID, route ID, AgentSession ID, lifecycle field, and retained reference.

Required tests:

- Two active bindings for the same resource through different internally seeded routes fail.
- A terminal binding and one active binding for the same resource remain valid.
- Existing valid binding identity and references remain unchanged across migration.

## Migration Execution Contract

The revision must be generated with `uv run alembic revision`; an executed migration is never edited. The revision pointer must identify the new head, whose parent is the previously committed head.

### Valid parent-revision fixture

Start from the exact parent revision and seed a real FK-valid legacy graph containing, at minimum:

- Workspace and required authenticated User/membership rows;
- active Agent;
- AgentSession;
- External Channel connection with stable provider identity and sentinel encrypted credentials;
- exactly one `dedicated` route;
- external principal and participant access state;
- resource;
- message and current message revision with attachment metadata;
- pending context and an active access request under the parent schema;
- active binding to the AgentSession; and
- any directly referenced event or retained-history row required to keep the graph valid.

Capture a pre-upgrade snapshot of every seeded durable ID, FK reference, route mode, provider identity, credential sentinel, lifecycle field, and relevant row count. After upgrade assert exact equality for all captured values, plus `single`/`available` backfills. Assert no Multi connection and no extra route was created.

### Independent ambiguity fixtures

Every case starts from the parent revision and must reach its own expected error before schema mutation. Do not combine cases and do not let a broader cardinality check mask a more specific error.

| Case | FK-valid parent data | Expected diagnostic |
| --- | --- | --- |
| Zero route | Connection with no route | exactly one dedicated route |
| Multiple distinct routes | One dedicated and one otherwise parent-valid route for distinct same-Workspace Agents | exactly one dedicated route |
| Non-dedicated sole route | One parent-valid non-`dedicated` route | exactly one dedicated route |
| Duplicate association | One dedicated and one otherwise parent-valid route for the same Agent | duplicate connection-Agent route |
| Cross-Workspace route | One dedicated route whose Agent belongs to another Workspace | route crosses Workspace boundary |
| Multiple active bindings | One resource with active bindings through two parent-valid routes and Sessions | resource has multiple active bindings |

Specific duplicate-association and multiple-active-binding preflights execute before the broad Single cardinality preflight so their diagnostics are reachable. The migration never deletes, retags, or selects a winner.

### Downgrade boundary

Safe downgrade succeeds only while all data remains representable by the parent schema. Downgrade must reject when any Phase-1-only durable state would be discarded, including:

- any `multi` connection or non-`single` route shadow;
- removed catalog status or non-null catalog-removal metadata;
- any interaction, conversation-admission, or channel-default row; or
- any state that violates the parent dedicated-route or binding constraints.

Tests separately prove a clean safe downgrade and each unsafe state category. Production or shared databases are never downgraded, stamped, or upgraded by this work.

## Installed-Schema and ORM Parity Matrix

The PostgreSQL integration test and ORM metadata test must verify names and exact constrained/referred columns for:

- enum types for App mode, route catalog status, interaction type/status, conversation origin/status, and channel-default status;
- `uq_external_channel_connections_id_app_mode`;
- connection App-mode immutability trigger and function;
- `uq_external_channel_agent_routes_connection_agent`;
- `uq_external_channel_agent_routes_connection_id_id`;
- `uq_external_channel_agent_routes_single_connection` and its `single` predicate;
- `fk_external_channel_agent_routes_connection_app_mode`;
- `uq_external_channel_resources_connection_id_id`;
- `uq_external_channel_messages_resource_id_id`;
- `uq_external_channel_interactions_connection_provider_key`;
- `uq_external_channel_interactions_connection_id_id`;
- `uq_external_channel_conversation_admissions_open_resource` and its exact open-status predicate;
- `fk_external_channel_conversation_admissions_connection_resource`;
- `fk_external_channel_conversation_admissions_resource_source_message`;
- `fk_external_channel_conversation_admissions_connection_selected_route`;
- `fk_external_channel_conversation_admissions_connection_interaction`;
- `fk_external_channel_channel_defaults_connection_route`;
- `uq_external_channel_channel_defaults_active_connection_channel` and its `active` predicate;
- `uq_external_channel_bindings_active_resource` and its `active` predicate; and
- all three new tables, required indexes, restrictive delete behavior, nullability, and server defaults.

Migration and ORM names, columns, predicates, enum values, and delete behavior must match exactly.

## Internal Multi Test Fixture Exception

The rollout gate prohibits Multi data from product code, public APIs, services, migrations, background work, and deterministic testenv/E2E fixtures before enablement. It does not prohibit isolated transactional PostgreSQL repository tests from directly inserting a Multi connection solely to prove declarative Multi cardinality and channel-default constraints. Such rows must be local to the test transaction/container, must not use a product creation path, and must be rolled back or destroyed with the isolated database.

## Rolling Compatibility and Scope Audit

Before completion, verify:

- old connection and route writers can omit new columns and still create only Single-compatible rows;
- all touched current writers explicitly use `single` and `available` where typed DTOs require them;
- existing `route_mode` remains present and unchanged;
- no connection-only runtime routing, lifecycle, interaction processing, API, generated-client, Web, spec, deployment, Kubernetes, or home-database change entered the diff;
- no public/product path creates `multi` or a second route; and
- sender, uploader, requester, approver, administrator, owner, or wake-up identity is never used as execution User authority.

## Final Validation Gate

All commands run after the final implementation edit, not before it.

From `python/apps/azents`:

1. `uv run ruff format .`
2. `uv run ruff check .`
3. `uv run pyright`
4. focused migration, installed-schema, repository, and directly affected Single App tests
5. `uv run pytest`
6. `uv run python -m compileall -q db-schemas/rdb/migrations/versions/<new_revision>.py`

From the repository root:

7. `git diff --check`
8. inspect `git diff --name-only` and compare every file with this phase boundary
9. grep production and fixture paths for Multi creation and report every match as allowed internal test setup or a blocker

Docker/Testcontainers absence may produce an explicit local skip, but it is not positive evidence that PostgreSQL behavior passed. The completion report must give exact passed/skipped counts and the environment reason. PR 3 cannot be declared CI-green until the PostgreSQL migration, installed-schema, and repository tests execute without Docker-related skips in CI and pass.

## Required Completion Report

The implementation owner returns one complete report containing:

- explicit confirmation that all five source documents were read in full;
- every acceptance ID with implementation path, test path, and pass evidence;
- exact changed files;
- exact final commands and results after the last edit;
- exact Docker/PostgreSQL skip status;
- confirmation that every migration ambiguity fixture and repository boundary test exists in the diff;
- confirmation that migration and ORM schema names and columns match;
- confirmation that no public/product Multi creation path exists; and
- any remaining blocker.

The primary agent rejects a report that describes acknowledged missing work, relies on tests run before the final edits, or claims behavior that is absent from the live diff.
