---
title: "Discord Thread Automatic Archive Duration Design"
created: 2026-08-20
updated: 2026-08-20
implemented: 2026-08-20
tags: [discord, external-channel, backend, frontend, api, database]
document_role: primary
document_type: design
snapshot_id: discord-260820
---

# discord-260820/DESIGN: Discord Thread Automatic Archive Duration

- Snapshot: `discord-260820`
- Document reference: `discord-260820/DESIGN`
- Requirements:
  [`discord-260820/REQ`](../requirements/discord-260820-thread-auto-archive-duration.md)
- Decisions:
  [`discord-260820/ADR`](../adr/discord-260820-thread-auto-archive-duration.md)

## Current Behavior and Gaps

`DiscordConnectionConfiguration` currently validates only `target_guild_id` and is
serialized into `external_channel_connections.provider_config`. Single and Multi
management projections expose that JSON, but all Discord credential-edit operations
replace the entire credential/configuration authority and reactivate the connection.
There is no non-secret Discord connection policy mutation.

`DiscordDeliveryClient.ensure_thread` currently passes the constant `60` to the
supported Discord SDK thread-create operation. Durable conversation provisioning calls
this method directly. The direct provider-effect fallback can also call it when a
Thread Resource has not yet retained a delivery channel. That fallback receives a
`ProviderTarget` whose connection snapshot contains credentials and tenant identity but
not provider configuration.

The Web has Discord setup/edit drafts for dedicated Single Apps and Workspace Multi
Apps. Setup submits Application ID, Guild ID, and Bot Token. Existing edit submits the
same complete secret-bearing replacement. There is no connection-policy draft or
policy-only save action.

These gaps affect `discord-260820/REQ-1` through `REQ-5`.

## Requirement and Decision Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `discord-260820/REQ-1` | closed typed duration literal, API validation, Single/Multi Selects |
| `discord-260820/REQ-2` | migration backfill, setup defaults, required typed field |
| `discord-260820/REQ-3` | connection-owned `provider_config`, shared delivery snapshot |
| `discord-260820/REQ-4` | dedicated policy-only repository/service/API mutations |
| `discord-260820/REQ-5` | duration passed only to new-thread SDK creation; reuse unchanged |
| `discord-260820/ADR-D1` | typed connection configuration is the sole policy authority |
| `discord-260820/ADR-D2` | non-secret Single/Multi mutation preserves operational authority |
| `discord-260820/ADR-D3` | forward migration establishes one required persisted shape |

## Architecture and Ownership

`external_channel_connections.provider_config` remains the only durable source of
truth. The Discord-specific typed configuration contains:

- provider discriminator;
- target Guild ID; and
- `thread_auto_archive_duration_minutes`, restricted to `60 | 1440 | 4320 | 10080`.

The value is not copied to routes, participation settings, Resources, Bindings,
Sessions, ingress items, or provider-effect request payloads. Repository boundaries
that load an RDB connection for provider execution decode the JSON into the typed
Discord configuration and place that immutable snapshot on `ProviderTarget` when an
effect may outlive its creating transaction. Conversation provisioning already loads
the connection configuration and decodes it before calling the provider.

This preserves connection-wide ownership while ensuring each process-local provider
operation uses one validated snapshot. A later policy update affects a later Thread
creation; it does not rewrite an effect already committed and executing.

## Data Model and Migration

No table or column is added. A generated Alembic revision updates every row whose
provider is Discord:

- preserve all existing JSON keys;
- add or replace `thread_auto_archive_duration_minutes` with `1440`; and
- retain SQL `NULL` only where the row was already structurally invalid, with migration
  validation preferring failure over inventing a missing target Guild.

Repository evidence indicates Discord creation always supplies a non-null
`provider_config` containing the target Guild. The migration test constructs
representative Single, Multi, active, and disconnected rows and verifies field
preservation and the one-day value. Downgrade removes only the new key and preserves the
remaining JSON object.

`db-schemas/rdb/revision` advances to the generated revision. No existing migration is
modified.

## Backend Typed Contracts

A shared Discord duration type alias or enum-like literal represents the four values.
`DiscordConnectionConfiguration` requires the new field and validates through Pydantic.
Setup request bodies therefore reject unsupported values before service execution.

A full-value request model carries only
`thread_auto_archive_duration_minutes`. It is not a generic patch and has no nullable or
omission semantics.

Management projections may continue exposing the existing redacted `provider_config`
JSON because generated clients already model it. Server-side mutation and runtime code
must decode that JSON before reading the value.

## Management API and State Transitions

Two provider-specific authenticated operations are added:

- Agent-scoped Single App duration replacement under the existing connection path; and
- Workspace-scoped Discord Multi App duration replacement under the existing Multi App
  path.

The Single route uses the current Agent-admin not-found-shaped ownership boundary. The
Multi route requires Workspace External Channel write permission and an
`expected_generation` value.

The repository mutation:

1. selects and locks the requested active Discord connection in the required ownership
   and App mode;
2. decodes its current provider configuration;
3. replaces only `thread_auto_archive_duration_minutes`;
4. persists the complete validated configuration;
5. flushes and refreshes `updated_at`; and
6. returns the existing redacted managed projection.

It does not modify `configuration_generation`, encrypted credentials, Application ID,
target Guild, provider tenant or Bot identity, callback selector, App claim, capability,
status, health timestamps/codes, Gateway lease fields, routes, Bindings, or Sessions.
No Discord activation or validation call follows the commit.

The Multi mutation compares the locked row's `updated_at` to
`expected_generation`. A mismatch returns the existing 409 generation-changed result.
The successful response includes the new generation through `ManagedMultiConnection`.

## Provider Thread Creation

`DiscordDeliveryClient.ensure_thread` receives the validated duration as a required
argument. It passes that exact value to the existing public SDK thread-create method.
The method keeps its current order:

1. fetch an existing root thread;
2. return it unchanged when present;
3. create only when absent using the supplied duration;
4. reconcile once after an SDK error; and
5. return the reconciled thread without an archive-duration update.

The duration is consumed only in step 3. Existing and reconciled Threads therefore
remain untouched.

Conversation provisioning decodes the connection's `provider_config`, verifies its
Guild matches the Resource scope through existing authority, and passes the duration to
`ensure_thread`.

For direct effects, `ProviderTarget` gains a required typed Discord configuration
snapshot or explicit `None` for non-Discord providers. Every constructor and
revalidation path refreshes it from the current connection row. The Discord delivery
branch rejects a missing/mismatched configuration and supplies its duration when the
fallback must create the Resource's provider Thread. Ordinary delivery to an already
retained Thread does not use the duration.

## Frontend Behavior

### Single App

The Discord setup dialog adds a required Select after the Guild field with these
localized labels:

- 1 hour;
- 1 day;
- 3 days; and
- 7 days.

Its initial value is `1440`. The setup tRPC mutation sends the value in the generated
Discord configuration request.

For an existing active Discord connection, the connection card exposes the same Select
and a policy-only Save action initialized from `provider_config`. This control is
separate from the secret-bearing credential replacement dialog. Saving calls the new
policy mutation and invalidates the connection list. It has normal disabled, pending,
saved, and error states. There is no description or helper copy below the Select.

### Multi App

The Workspace Discord setup form adds the same defaulted Select. The selected
connection detail exposes the same policy-only Select and Save action for mutable active
Discord connections. It calls the generation-fenced Multi endpoint, refreshes list and
detail queries, and updates its local generation from refreshed server state.

Disconnected Multi history remains read-only. Agent settings continue to show
associated Multi Apps without an edit action.

### Localization and stories

All supported locales receive natural labels for the field and four values, plus Save,
saved, and error copy only where existing shared copy cannot be reused. No locale adds
helper text below the Select.

Existing pure component Storybook stories are updated for Discord setup and active
connection-management states, including the one-day default and a non-default saved
value.

## Generated API Clients

After adding the public routes and request/response schemas:

1. regenerate the public OpenAPI document with the backend command;
2. run the repository OpenAPI client generation workflow;
3. use the generated TypeScript functions in the Web tRPC router; and
4. do not hand-edit generated files.

The generated Python public client is updated by the same workflow where configured.

## Security and Permissions

- Single mutation requires current Agent administrator authority and exact Single App
  ownership.
- Multi mutation requires Workspace Owner/Manager External Channel write permission,
  exact Workspace ownership, Discord provider, Multi App mode, active mutability, and a
  current generation.
- Request validation accepts only the four supported numeric values.
- Responses remain redacted and contain no encrypted or decrypted credentials.
- Duration-only updates do not extend provider authority and perform no provider I/O.

## Failure, Concurrency, Rollout, and Recovery

Validation errors are ordinary 400 responses. Missing, foreign, disconnected, wrong
provider, or wrong App-mode connections use the existing not-found-shaped management
boundary. A stale Multi generation returns 409 and the UI refreshes authoritative
state.

The policy mutation is one PostgreSQL transaction and has no provider side effect to
retry or compensate. A process failure before commit leaves the old value; success
changes the value for later Thread creation. A Thread creation already executing uses
its validated process-local snapshot.

The schema/data migration and application ship together without a feature flag or
legacy reader fallback. Rollback to code that ignores the additional JSON key is safe;
the migration downgrade removes the key when a full database rollback is required.

## Observability and Operational Risks

No new success log or metric is required for an ordinary management update. Existing
HTTP request/error observability covers validation and authorization failures. Discord
Thread-create test evidence verifies the outbound SDK argument.

Primary risks are incomplete provider-target propagation and accidental reuse of the
credential replacement lifecycle. Required-argument type checking, constructor updates,
repository tests, and assertions that operational fields remain unchanged mitigate
those risks.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected evidence |
| --- | --- |
| Create a Discord Single App with the default | UI shows one day; API stores `1440`; the next fake-provider Thread create records `1440` |
| Create a Discord Multi App with three days and use two routes | one connection stores `4320`; Threads created for both routes record `4320` |
| Change an active connection from one day to seven days | credentials and health remain unchanged; an existing Thread is untouched; the next created Thread records `10080` |
| Attempt an unsupported API value | request fails before persistence and provider I/O |
| Open Agent read-only Multi context | current Multi App is visible without a duration edit action |

The deterministic Discord fake already records `auto_archive_duration` for created
Threads and is extended only where management setup/inspection needs to expose the
value. Required CI coverage uses fake-provider credentials and PostgreSQL fixtures.
Live Discord verification is optional and must skip when credentials or a disposable
Guild are unavailable; it is not a CI acceptance dependency.

### Backend tests

- Pydantic tests accept exactly the four values and reject other integers.
- Migration tests upgrade and downgrade representative Discord JSON while preserving
  unrelated fields and Slack rows.
- Management repository/service/route tests cover Single and Multi ownership,
  generation conflicts, disconnected rejection, persisted projection, and unchanged
  credentials, configuration generation, callback, claim, Gateway, capability, and
  health fields.
- Conversation provisioning and direct-effect tests assert the current configured
  value reaches `ensure_thread`.
- Discord delivery tests assert exact SDK arguments for all four supported values and
  prove existing/reconciled Threads perform no update.

### Frontend tests and stories

- tRPC router schemas accept the four values and call generated Single/Multi API
  functions with the correct body.
- Container tests or extracted pure-state tests cover one-day initialization,
  server-value initialization, dirty/save behavior, refresh, pending disablement,
  generation conflict refresh, and no credential mutation call.
- Storybook covers setup default, active policy editing, non-default value, and
  read-only disconnected/Multi context where applicable.

### Quality gates

Run focused Pytest, Ruff, configured Python type checking, OpenAPI generation checks,
TypeScript formatting, lint, type checking, relevant build/tests, documentation
validation, Spec review, pre-commit hooks, and GitHub CI. Deterministic migration,
management, and provider-argument tests may not skip.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Hard-coded 60-minute Discord Thread creation constant | `discord-260820/REQ-1`, `REQ-2`; `discord-260820/ADR-D1` | required typed connection duration passed to SDK create | `DiscordDeliveryClient.ensure_thread` and callers | source search finds no fixed archive duration in production thread creation; tests assert configured values |
| Historical Discord configuration without the duration field | `discord-260820/REQ-2`; `discord-260820/ADR-D3` | migrated required typed configuration with `1440` | Alembic data migration and setup payloads | migration tests and typed decode cover all Discord rows |
| Credential replacement as the only Discord configuration edit path | `discord-260820/REQ-4`; `discord-260820/ADR-D2` | separate policy-only Single/Multi mutation; credential edit remains for identity/secret replacement | management API, service, repository, and Web controls | tests assert policy save never invokes activation or changes operational fields |
| Existing Discord Threads and retained delivery-channel identities | None; retained | `discord-260820/REQ-5` | no migration or provider update | SDK tests assert reuse returns without create/update; no backfill provider job exists |
| Agent read-only Multi App context | None; retained | current External Channel management Specs | unchanged Agent surface | Storybook/component assertion exposes no policy save action |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| `M1` | Discord connection `provider_config` is the sole durable duration authority | `discord-260820/REQ-3`; `discord-260820/ADR-D1` | `decided` |
| `M2` | Supported duration is a required closed typed value of 60, 1440, 4320, or 10080 minutes | `discord-260820/REQ-1`; Discord provider constraint | `required` |
| `M3` | A forward migration backfills every Discord connection to 1440 and removes the need for a missing-field runtime fallback | `discord-260820/REQ-2`; `discord-260820/ADR-D3` | `decided` |
| `M4` | Single and Multi policy-only mutations update only validated provider configuration and management generation | `discord-260820/REQ-4`; `discord-260820/ADR-D2` | `decided` |
| `M5` | New Thread creation receives a validated connection snapshot; existing/reconciled Threads are never mutated | `discord-260820/REQ-3`, `REQ-5`; current delivery one-attempt lifecycle | `derived` |
| `M6` | Single and Workspace Multi setup default to one day and existing connection surfaces provide separate policy Save controls | `discord-260820/REQ-1`, `REQ-2`, `REQ-4` | `required` |
| `M7` | Agent-visible Workspace Multi context remains read-only and the Select has no helper text | `discord-260820/REQ-1`, `REQ-3`; confirmed non-goals | `required` |
| `M8` | Public OpenAPI and generated clients carry the new validated setup and policy contracts | `discord-260820/REQ-1`, `REQ-4`; project generated-client constraint | `derived` |

## Authority Audit

- Every Requirement maps to one or more material mechanisms and deterministic test
  evidence.
- Connection ownership, supported values, one-day default, non-disruptive update, and
  new-Threads-only lifecycle are directly authorized by confirmed Requirements and the
  accepted ADR.
- The Design introduces no route-level override, provider-thread update, deployment
  setting, credential fallback, compatibility reader, or second editable Multi surface.
- Multi generation fencing retains the current destructive/stale-editor management
  convention without changing Discord runtime configuration generation.
- Generated-client and typed-JSON mechanisms are required project constraints rather
  than new product decisions.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

| Area | Result | Repository evidence |
| --- | --- | --- |
| Persistence | Feasible | `provider_config` is connection-owned JSONB and already projected to Single/Multi management clients |
| Validation | Feasible | `DiscordConnectionConfiguration` is the existing typed setup contract and can close the allowed value set |
| Migration | Feasible | Discord rows are provider-identifiable and current creation persists a target-Guild JSON object; JSONB update preserves unrelated keys |
| Policy-only update | Feasible | management repository already has locked non-secret access-policy mutations and separate complete credential replacement helpers |
| Multi concurrency | Feasible | `updated_at` is already the exposed generation and existing service helpers implement generation conflicts |
| Provisioning | Feasible | the service already loads connection configuration before `ensure_thread` |
| Direct-effect fallback | Feasible | provider targets are rebuilt from the locked current connection during planning and revalidation |
| Discord provider call | Feasible | the SDK protocol already accepts the exact four-value literal and `ensure_thread` is the only production thread-create wrapper |
| Single UI | Feasible | Discord setup/edit state and connection projections already expose target Guild and support separate per-connection actions |
| Multi UI | Feasible | setup/detail drafts, generation, refresh, permissions, and disconnected history are already modeled |
| Deterministic testing | Feasible | the Discord fake records `auto_archive_duration`; service, route, delivery, Storybook, and PostgreSQL fixtures cover the affected boundaries |

No confirmed Requirement or accepted decision is blocked. The implementation must
update every `ProviderTarget` constructor because the new typed field is required, but
this is a bounded compiler- and test-visible change.

Feasibility result: **feasible for Design revision 1**.

## Assumptions and Non-Blocking Risks

- Current Discord rows have the target-Guild configuration established by prior setup
  migrations and creation code; the migration validates this expectation.
- A policy update concurrent with an already planned Thread create may leave that one
  operation using the prior snapshot. This is acceptable because the provider call was
  already committed for immediate execution; every later operation reads current state.
- Discord may restrict longer durations for a Guild without the required provider
  features. The API accepts Discord's supported values, while a provider rejection
  remains an ordinary sanitized Thread-create failure.

## Design Approval

- Mode: `Collaborative`
- Decision owner: Requester
- Approved on: `2026-08-20`
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Approved scope: Implement the requester-confirmed one-hour/one-day/three-day/seven-day
  Discord connection setting with a one-day default and migration, connection-wide
  new-Thread application, non-disruptive Single and Multi management, no existing
  Thread mutation, no helper text below the Select, generated contracts, tests, and one
  focused pull request.
