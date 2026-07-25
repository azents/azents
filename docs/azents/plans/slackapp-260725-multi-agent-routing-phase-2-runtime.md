---
title: "Multi-Agent Slack App Routing Phase 2 Execution Plan"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, implementation, routing, lifecycle]
---

# Multi-Agent Slack App Routing Phase 2 Execution Plan

## Phase Boundary

- Phase: `PR 4/10 — Phase 2: Mode-aware routing and lifecycle`
- Branch/base: `feature/slack-multi-agent-app-routing` → `feature/slack-multi-agent-app-schema`
- PR boundary: Make every existing External Channel runtime, authorization, hydration, management, disconnect, Session lifecycle, and Agent decommission path safe in the presence of zero or multiple Multi App routes while all product creation paths remain Single-only.
- Primary source decisions: `slackapp-260725/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`, `ADR-D5`, and the mode-aware runtime gate in `ADR-D7`.
- Primary requirement coverage: runtime and lifecycle foundations for `REQ-2`, `REQ-3`, `REQ-7`, `REQ-9`, `REQ-11`, `REQ-12`, and `REQ-13`. Provider interaction handling and participant-visible selection remain PR 5; Workspace management APIs remain PR 6.
- Deliverables: deterministic route resolution; route-neutral source persistence; post-selection pending-context projection; one canonical External Channel lock order; explicit Single App management enforcement; internal Multi route removal/re-enable and whole-connection lifecycle services; Session and Agent lifecycle integration; and complete fail-closed and concurrency regression evidence.
- Non-goals: Slack shortcut, block-action, modal, or interactive Socket processing; participant-visible Agent selector controls; Agent-name/icon output presentation; Workspace permissions or public Multi App routes; OpenAPI or generated-client changes; Web UI; deterministic testenv Multi App creation; living-spec promotion; deployment changes; database upgrade/stamp execution; and Kubernetes or home-database writes.

No public, product, background, migration, or deterministic testenv path may create a Multi App or a second route in this phase. Direct Multi rows are allowed only in isolated transactional repository/service tests that are destroyed with their test database.

## Mandatory Source Read and Traceability Gate

Before editing implementation files, the implementation owner must read these files in full:

- `docs/azents/requirements/slackapp-260725-multi-agent-routing.md`
- `docs/azents/adr/slackapp-260725-multi-agent-routing.md`
- `docs/azents/design/slackapp-260725-multi-agent-routing.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-implementation-plan.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-phase-1-schema.md`
- this Phase Execution Plan
- `docs/azents/spec/domain/external-channel.md`
- `docs/azents/spec/flow/external-channel-provider-ingress.md`
- `docs/azents/spec/flow/external-channel-authorization.md`
- `docs/azents/spec/flow/external-channel-lifecycle.md`
- `docs/azents/spec/flow/external-channel-delivery.md`

The implementation owner must maintain a working checklist mapping every acceptance ID below to implementation paths, tests, and final evidence. The primary agent independently verifies the complete diff and checklist before assigning the stable independent reviewer. Partial implementation is not ready for review.

## Current Runtime Risks That This Phase Must Remove

The Phase 1 schema intentionally retained rolling-compatible old runtime behavior. PR 4 must remove these dependencies before Multi data is enabled:

- `ExternalChannelRepository.get_routable_route_by_connection_id()` orders routes and applies `limit(1)`, so a connection with multiple routes can select an arbitrary Agent.
- Event persistence chooses a route before creating or updating the canonical resource, message, and revision, and immediately writes route-scoped pending context.
- Event, approval, hydration, disconnect, and lifecycle paths use inconsistent binding/resource lock order.
- Active-binding lookups are still expressed as `(route_id, resource_id)` even though the schema now enforces one active binding per resource.
- Agent-scoped connection management joins by Agent but does not yet reject a Multi App connection explicitly.
- Whole-connection disconnect and provider uninstall operate over current routes but do not yet terminalize Phase 1 conversation admissions and channel defaults.
- Agent decommission deletes every route after Session retirement; it must distinguish Single whole-connection ownership from Multi catalog-association removal and preserve Multi route history until restrictive dependencies permit final cleanup.

PR 4 completion requires that no runtime routing decision depends on route ordering or connection-only `limit(1)` selection.

## Ownership and Paths

| Workstream | Owner | Expected paths | Output |
| --- | --- | --- | --- |
| Route resolution and route-neutral projection | `slack-app-impl-v3` | `python/apps/azents/src/azents/repos/external_channel/data.py`; `repository.py`; `python/apps/azents/src/azents/services/external_channel/event_processor.py`; optional focused resolver module under the same service package | Explicit resolution result, route-neutral canonical persistence, selected-route projection, and no arbitrary route selection |
| Authorization and binding concurrency | `slack-app-impl-v3` | `services/external_channel/access.py`; `repos/external_channel/repository.py`; focused service/repository tests | Resource-wide binding ownership, canonical lock order, idempotent Session/binding creation, and admission/request transitions |
| Mode-specific management and lifecycle | `slack-app-impl-v3` | `repos/external_channel/management.py`; `repos/external_channel/lifecycle.py`; `services/external_channel/management.py`; `services/external_channel/lifecycle.py`; directly affected provider-disconnect code | Single-only Agent management, internal Multi route lifecycle, whole Multi disconnect support, and retained-history behavior |
| Session and Agent lifecycle integration | `slack-app-impl-v3` | `services/agent_decommission.py`; External Channel lifecycle participant/finalizer integration; only directly required Session lifecycle files | Immediate selection fence, terminal bindings/defaults/admissions, restrictive cleanup, and no restore reactivation |
| Regression and concurrency evidence | `slack-app-impl-v3` | existing External Channel repository/service tests plus new focused mode-aware runtime tests | Single continuity, Multi internal fixtures, race convergence, lock-order assertions, and rollout gate audit |
| Independent review | `slack-app-review-v2` | read-only review of the final diff and all source documents | Critical/Warning findings with exact evidence, or explicit no-findings result |

The implementation owner does not create child agents, commit, push, edit PRs, modify Kubernetes, run shared or configured database upgrades/stamps, or start PR 5 work.

## Canonical Lock and Execution-Authority Contract

Every External Channel transaction that can select a route, create or terminate a binding, change an admission/request, or alter a relationship uses this order whenever the row class is present:

1. connection;
2. route, when a route-specific transition is required;
3. resource, ordered by resource ID for bulk work;
4. the resource-wide active binding;
5. conversation admission or access request; and
6. Session-owned dependent rows.

Repository methods must make the lock target and ordering explicit. A query that joins several roots with an unconstrained `with_for_update()` is not sufficient evidence of the order. Binding lookup and lock methods use `resource_id` as the primary uniqueness boundary and validate an expected route separately when route identity matters.

The existing Session lifecycle orchestrator may enter its participant while holding the locked Session tree. This phase must not create the reverse edge against an existing Session row: an External Channel transaction may insert a new root Session through the shared creation service, but it must not hold connection/route/resource locks and then lock an already existing Session. Existing-Session archive, restore, and purge remain caller-owned lifecycle operations. Add a focused concurrency or query-order test proving no conflicting reverse acquisition is introduced.

Slack sender, uploader, requester, approver, Agent administrator, Workspace administrator, connection creator, or broker wake-up never becomes the execution User. Durable work release remains an immutable invocation batch followed by a routing-only `SessionWakeUp(session_id)`. Any touched mutation of existing Session/Run execution state must preserve canonical `owner_generation` fencing; no fallback User or unfenced execution mutation may be added.

## Acceptance Matrix

### P2-D1 — Deterministic mode-aware route resolution

Implementation:

- Replace `get_routable_route_by_connection_id()` as a routing decision with explicit repository/service operations for:
  - the active binding for one resource;
  - the validated sole route of a Single App;
  - the validated active channel default of a Multi App; and
  - a previously selected open conversation admission.
- For a conversation without an open admission, initial route resolution is exactly: active binding → Single sole route → Multi channel default → selection-required.
- If an open admission already records a selected route, retries continue that immutable selection after checking for an active binding and never replace it with a newly configured or changed channel default.
- The connection is locked and must be `active` or `degraded` before new execution state is admitted.
- Existing active bindings load their recorded route and Session and never consult a current default or another candidate route.
- Single resolution requires exactly one route belonging to the connection, a matching `single` mode shadow, `available` catalog state, same-Workspace active Agent, and no ambiguity. Zero or multiple rows fail closed.
- Multi default and selected-admission resolution requires a matching `multi` mode shadow, `available` catalog state, same-Workspace active Agent, matching connection/resource/channel ownership, and an unexpired compatible admission when applicable.
- A missing, invalidated, removed, inactive, cross-Workspace, cross-connection, expired, or ambiguous route/default/admission returns a typed fail-closed or selection-required result. It never falls back to another route.
- Remove the connection-only route-ordering query from production routing. Remaining `limit(1)` uses must be non-routing scalar/history lookups and documented by the final scope audit.

Required tests:

- Existing binding wins over changed defaults and candidate routes.
- Single App resolves exactly its sole eligible route.
- Single zero-route, multiple-route, mode-shadow mismatch, removed route, inactive Agent, and cross-Workspace corruption fail without Session, binding, batch, or wake-up creation.
- Multi default resolves only its exact eligible route.
- Invalid Multi default behaves as unconfigured and never selects another associated route.
- Selected admission resolves only its stored route and rejects stale/cross-boundary state.
- An internally seeded Multi connection with two eligible routes and no default/selection produces selection-required, not either route.
- Production grep proves no connection-only `limit(1)` routing path remains.

### P2-D2 — Route-neutral canonical source persistence

Implementation:

- For an eligible tracked invocation, create or load the connection-scoped resource and persist principal, canonical message, immutable revision, attachment metadata, reference mappings, and optional permalink before selecting an Agent route.
- Split the current message persistence helper into a route-neutral canonical step and a route-scoped projection step.
- Route-neutral persistence is idempotent for original, edit, delete, duplicate, reordered, and hydration observations and does not create pending context, access request, binding, Session, invocation batch, InputBuffer, or wake-up.
- Continue ignoring unrelated unlinked ordinary traffic after the existing bounded correlated-mention wait. This phase does not normalize every Slack channel message.
- Connection-authored messages remain excluded without entering Agent context.
- Once resolution selects a route, project only the applied current revision into that route/resource pending context, apply the existing age/count/size trim, and then enter Agent-specific block/grant/access logic.
- A pending-selection Multi admission retains canonical source data without route-scoped pending context until a later phase selects a route.
- Edits/deletes and hydration keep their current observable semantics; no previously projected revision is rewritten.

Required tests:

- A Single App invocation preserves the current canonical rows, pending context, access behavior, hydration requirement, and wake-up behavior.
- A two-route Multi fixture persists resource/message/revision and one pending-selection admission while creating no route-scoped context, access request, Session, binding, batch, InputBuffer, or wake-up.
- A Multi default or selected admission projects pending context only to the chosen route.
- Duplicate/reordered events reuse canonical identities and do not duplicate projection.
- Provider text, file bodies, private URLs, credentials, and interaction capabilities remain absent from logs and new lifecycle projections.

### P2-D3 — Conversation admission runtime transitions

Implementation:

- Add locked repository operations to load the open admission for a resource and apply only valid idempotent transitions needed by this phase.
- Single sole-route and Multi channel-default invocations create or reuse an admission with the selected route and progress through `selected`, `awaiting_access`, or `bound` according to the existing grant/access outcome.
- Multi without an eligible default creates or reuses `pending_selection`; participant-visible selector delivery and interaction processing remain PR 5.
- Materialize route-scoped pending context from the retained source revision only after the selected route is revalidated under the canonical lock order.
- When approval is required, attach the existing Agent-specific access request to the selected route, create no Session or binding before Allow, and keep the conversation admission at `awaiting_access`.
- Successful already-granted binding creation or compatible Allow changes the admission to `bound` in the same transaction as the binding and durable release state.
- Duplicate callbacks/events/Allow decisions return the existing compatible state. Conflicting selected routes or an already bound resource never replace the binding.
- Expired, rejected, relationship-removed, or connection-disconnected admissions are terminal and cannot be reopened by a retry.

Required tests:

- Single/default admissions transition idempotently to awaiting access or bound.
- Pending selection stores no route context and creates no execution state.
- Approval Allow binds the admission exactly once and repeated Allow reuses the same Session/binding/batch.
- Concurrent default/selected/approval attempts converge on one resource-wide binding and one Session; losers return the recorded binding or a conflict without rerouting.
- Conflicting selected route, expired admission, removed route, inactive Agent, and existing binding fail closed.

### P2-D4 — Resource-wide binding lock and creation boundary

Implementation:

- Replace route-qualified active-binding lock/read calls in event and approval paths with resource-wide operations reflecting the Phase 1 unique index.
- When a caller expects a route, compare the locked binding's route ID and fail rather than treating another route's binding as absent.
- Resource lock precedes active-binding lock in every new-execution path. Connection and selected route locks precede the resource.
- `create_binding_idempotent` validates every immutable owner boundary before an idempotent conflict can return an existing row: resource connection, route connection/mode, Agent Workspace/lifecycle, Session Agent/Workspace/root ownership, and expected selected admission/access request.
- A uniqueness race never leaves an orphan newly created AgentSession. If the shared Session-creation boundary inserts a Session but another binding wins, the transaction must roll back or reuse the existing compatible binding without committing an unrelated Session.
- Initial binding activation, hydration reconciliation, pending-context release, Channel Work creation, invocation batch creation, InputBuffer creation, and routing-only wake semantics remain unchanged for valid Single Apps.

Required tests:

- A binding on route A is found when route B attempts the same resource and route B cannot create a Session or binding.
- Deterministic concurrent creators produce one committed root Session and one active binding.
- Owner-boundary attacks are rejected even when an active binding already exists and the idempotent path could otherwise return it.
- Event processing, Allow, hydration reconciliation, and initial-grant creation acquire resource before binding and use the same route mismatch behavior.
- Existing Single activation and release regression tests remain unchanged.

### P2-D5 — Formal Single App management boundary

Implementation:

- Existing Agent-scoped connection list, validate, replace, and disconnect operations accept only `app_mode = single` and require the path Agent to be the connection's exact sole route.
- The route must have a matching Single mode shadow. A Multi connection associated with the same Agent is not listed and cannot be mutated through the Agent-scoped connection endpoints.
- Single setup continues to create the connection and sole route atomically from the product perspective, writes `single` explicitly, and never exposes a mode selector.
- Removing/disconnecting the Single relationship runs whole-connection disconnect. No independent Single route-removal or re-enable operation exists.
- Agent-scoped access approval and Session Channels remain Agent/Session views and continue to work for a selected Multi route; do not incorrectly hide or reject those Agent-specific operations solely because the connection is Multi.

Required tests:

- Current Single list/setup/validate/replace/disconnect API and service behavior remains compatible.
- An internally seeded Multi connection is absent from Agent connection listing and rejected by Agent connection validate/replace/disconnect.
- A Multi-selected Agent approval remains authorized by that Agent's administrators and does not gain Workspace management authority.
- No public schema or generated client changes enter this PR.

### P2-D6 — Internal Multi route and connection lifecycle

Implementation:

- Add internal service/repository operations for Multi route impact projection, route removal, route re-enable, and whole Multi connection disconnect. Public Workspace authorization and routes are PR 6.
- Multi route removal locks connection → route → sorted resources → active bindings → selected admissions/access requests.
- Removal requires authoritative `multi` mode and a matching route mode shadow. It:
  - marks the preserved route `removed` with authenticated Azents administrator provenance supplied by the future service boundary;
  - invalidates every active channel default for the route in the same transaction;
  - disconnects every active binding for the route with a relationship-removal reason;
  - marks each formerly bound resource unavailable so the established Slack thread cannot be rebound to another Agent;
  - finishes active Channel Work and creates existing one-attempt Tracker cleanup intents;
  - removes unreleased route/resource pending context;
  - terminalizes open selected/awaiting-access admissions and pending access requests for the removed relationship without deleting their provenance; and
  - preserves connection credentials, health, transport, other routes, other resources, and retained history.
- Re-enable reuses the same preserved `(connection_id, agent_id)` route, clears catalog-removal metadata, requires an active same-Workspace Agent, and does not reactivate bindings, resources, defaults, access requests, admissions, work, or Sessions.
- Whole Multi disconnect supports zero, one, or many routes; invalidates all active defaults and open admissions; terminalizes every active resource/binding/work item; clears credentials and Socket lease state; and remains idempotent.
- Existing provider uninstall/revocation connection termination is made mode-aware and covers all routes/defaults/admissions without selecting one route.
- Provider calls remain post-commit and one-attempt. Cleanup failure never rolls back terminal local state.

Required tests:

- Removing one Multi route leaves the connection and other routes operational while invalidating only its defaults and terminalizing only its bindings/work.
- A removed bound resource cannot be selected or rebound to another route.
- Re-enable preserves route identity and permits only new conversations.
- Zero-route and multi-route whole disconnect terminalize all connection-owned live state and are idempotent.
- Single route removal delegates to/requires whole-connection disconnect and cannot leave a zero-route live Single App.
- Provider uninstall covers all routes and Phase 1 state without arbitrary route selection.
- Impact projection counts and mutation results are deterministic and contain no secrets or Slack message/file bodies. Generation-fenced public confirmation remains PR 6.

### P2-D7 — Session lifecycle and Agent decommission integration

Implementation:

- Session archive continues to terminalize only bindings in the locked Session tree, finish their work, remove their route/resource pending context, and create cleanup intents. It does not remove routes, defaults, connection credentials, canonical messages, or conversation admissions owned outside that Session unless their own lifecycle requires a terminal transition.
- Restore validates terminal state and never reactivates a binding, work item, pending context, admission, default, or route.
- Purge continues deleting only Session-owned roots in restrictive order. Conversation admissions, defaults, routes, resources, messages, and connection history remain canonical non-Session roots.
- Agent decommission fences new route selection through Agent lifecycle immediately.
- Before final Agent deletion:
  - each Single route runs or requires whole Single connection disconnection;
  - each Multi route runs the Multi association-removal transition;
  - active bindings/Sessions complete their existing archive/purge lifecycle; and
  - direct route deletion occurs only after restrictive references are terminal and removable.
- Multi connections and other Agent routes survive decommission. Channel defaults for the decommissioned route become invalidated, not reassigned.
- Cleanup queries use stable ordering and do not delete a route early to bypass retained-history foreign keys.

Required tests:

- Archive/restore/purge regression coverage remains green for Single Apps.
- Archive of one Session under a Multi route does not affect other bindings or defaults.
- Agent decommission makes all of the Agent's routes immediately unselectable, disconnects its Single connections, removes its Multi associations, and leaves other Multi routes/connections intact.
- Finalization remains blocked while route-owned restrictive roots remain.
- Restore never revives route availability or relationship-removed resources.

### P2-D8 — Rollout gate, observability, and scope audit

Implementation:

- All product writers remain Single-only. Multi data appears only in isolated backend tests.
- No Workspace Multi creation endpoint, feature flag, public schema, generated client, Web UI, or deterministic testenv fixture is added.
- Add structured safe categorical logs or existing metric hooks for route resolution source and fail-closed reason only where the repository has an established observability pattern. Do not introduce a new metrics subsystem in this phase.
- Logs may contain durable IDs, App mode, transition, and safe reason codes. They never contain provider message text, file bytes, credentials, raw interaction bodies, response URLs, private image URLs, or Slack capability values.
- Preserve route IDs, binding IDs, AgentSession IDs, credential ciphertext, invocation history, approvals, canonical messages, and hydration state for existing Single data.
- Do not remove `route_mode` in this phase; it remains a rolling-compatibility field. New routing reads connection App mode and catalog availability.
- No migration is expected. If implementation proves an additional durable constraint is required, stop and report the exact deficiency to the primary agent. Any approved fix must be a newly generated Alembic revision and must never edit the Phase 1 revision.

Required tests and audits:

- Existing Single HTTP and Socket event, approval, hydration, lifecycle, Session Channels, file-transfer, delivery, archive, restore, purge, and decommission tests pass.
- Focused internal Multi service/repository tests cover zero/multiple routes without a product creation path.
- Grep every production caller of route lookup, binding lookup/lock, pending-context creation, connection disconnect, and Agent route deletion.
- Grep production/public/testenv paths for `ExternalChannelAppMode.MULTI` creation and classify every match; any non-isolated-test writer is a blocker.
- Verify no generated OpenAPI/client file, living spec, TypeScript UI, Helm, Kubernetes, or home configuration enters the diff.

## Detailed Runtime Flow

### Eligible new message

1. Lock the receiving connection and require active/degraded status.
2. Load or create the canonical resource for the authenticated connection.
3. Lock the resource.
4. Lock the resource-wide active binding.
5. Persist the principal, message, and applied immutable revision without route context.
6. If a binding exists, validate and use its recorded route/Session.
7. If an existing open admission records a selected route, revalidate and continue that selection; otherwise resolve Single sole route, Multi default, or selection-required.
8. Create/reuse the conversation admission for a newly selected unbound invocation.
9. Revalidate the selected route and project the applied revision to route-scoped pending context.
10. Apply existing block/grant/access behavior.
11. Create a new Session/binding only when authorized, transition admission consistently, commit durable batch/work/input state, and send only a routing wake after commit.

The implementation may split these steps across narrowly scoped transactions only if durable state makes retries converge and no provider acknowledgement or wake-up can observe a missing prerequisite. It must not hold a database transaction across Slack network calls.

### Existing bound message

1. Resolve the authenticated connection and resource.
2. Lock resource and active binding.
3. Load the exact recorded route and Session.
4. Persist the canonical revision and project it only to that route.
5. Apply the existing Agent-specific grant and release behavior.

Defaults, selectors, route ordering, and other associated Agents are never consulted.

### Pending selection

1. Persist canonical source state.
2. Create/reuse one `pending_selection` admission.
3. Commit with no pending context, access request, Session, binding, batch, InputBuffer, or wake-up.
4. PR 5 owns provider interaction admission, selector presentation, and participant selection.

## Test Placement

Prefer focused tests adjacent to the changed boundary:

- repository resolution, owner checks, admission transitions, lifecycle bulk operations, and PostgreSQL concurrency in `python/apps/azents/src/azents/repos/external_channel/`;
- event routing, route-neutral persistence, hydration, binding, and wake behavior in `services/external_channel/event_processor_test.py` or a focused mode-aware runtime test module;
- approval races and route mismatch in `services/external_channel/access_test.py` or the current access test location;
- Single management mode enforcement in `services/external_channel/management_test.py` and public route regression tests without changing schemas;
- Session lifecycle and Agent decommission behavior in their existing focused tests.

PostgreSQL/Testcontainers tests must exercise real row locks and uniqueness. Mock-only call-order assertions are supplementary and cannot replace database race evidence.

## Final Validation Gate

All commands run after the final implementation edit.

From `python/apps/azents`:

1. `uv run ruff format .`
2. `uv run ruff check .`
3. `uv run pyright`
4. focused mode-aware routing, event, access, management, lifecycle, Agent decommission, Session lifecycle, repository, and PostgreSQL concurrency tests
5. `uv run pytest`

From the repository root:

6. `git diff --check`
7. inspect `git diff --name-only` against this phase boundary
8. audit every production `limit(1)` under External Channel and prove no use selects a route by connection
9. audit every active-binding lookup/lock and prove the resource-wide ownership boundary
10. audit every production/public/background/testenv Multi creation match
11. verify no generated clients, living specs, TypeScript UI, infrastructure, Kubernetes, or home files changed

Docker/Testcontainers absence may produce a declared local skip, but it is not positive PostgreSQL concurrency evidence. PR 4 cannot be considered CI-green until its PostgreSQL lock/race tests execute without Docker-related skips in CI and pass.

## Required Completion Report

The implementation owner returns one complete report containing:

- explicit confirmation that all mandatory source documents were read in full;
- every `P2-D1` through `P2-D8` item mapped to implementation paths, tests, and final evidence;
- exact changed files;
- exact final commands and results after the last edit;
- exact Docker/PostgreSQL skip status;
- the final list of remaining External Channel `limit(1)` calls with why each is not route selection;
- confirmation that every active-binding caller uses the resource-wide boundary;
- confirmation that existing Single behavior and identities remain intact;
- confirmation that no public/product/testenv Multi creation path exists;
- confirmation that no Slack provenance or administrator identity became execution User authority and that touched execution mutations preserve `owner_generation` fencing; and
- any remaining blocker.

The primary agent rejects a report that relies on pre-final-edit tests, omits real PostgreSQL race coverage without an explicit CI requirement, describes acknowledged missing acceptance work, or claims behavior absent from the live diff.
