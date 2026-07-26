---
title: "Multi-Agent Slack App Routing Implementation Plan"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, implementation, rollout, testing]
---

# Multi-Agent Slack App Routing Implementation Plan

- Requirements: [Multi-Agent Slack App Routing Requirements](../requirements/slackapp-260725-multi-agent-routing.md) (`slackapp-260725/REQ`)
- ADR: [Multi-Agent Slack App Routing](../adr/slackapp-260725-multi-agent-routing.md) (`slackapp-260725/ADR`)
- Design: [Multi-Agent Slack App Routing Design](../design/slackapp-260725-multi-agent-routing.md) (`slackapp-260725/DESIGN`)
- Stack prefix: `Slack multi-agent apps`

## Feature Summary

Ship separate Agent-admin-owned Single Slack Apps and Workspace-admin-owned Multi
Slack Apps on one External Channel runtime model. Existing dedicated connections
become Single Apps without reinstallation. Multi Apps add Workspace management,
multiple Agent associations, channel defaults, message-shortcut selection,
mention-triggered selection, durable approval continuity, resource-wide binding
safety, and minimal Agent identity presentation.

The feature requires stacked delivery because schema, routing, provider interaction,
public API, generated clients, Web UI, test fixtures, rollout gates, and living specs
have sequential dependencies. Multi App data must not exist until every worker and API
path is mode-aware.

## Delivery Stack

| PR | Branch | Base | Scope | Completion gate |
| --- | --- | --- | --- | --- |
| 1/10 — Design baseline | `design/slack-multi-agent-app` | `main` | Approved Requirements, ADR, Design, traceability, and feasibility | Snapshot validation and docs hooks pass |
| 2/10 — Implementation plan | `plan/slack-multi-agent-app` | PR 1 branch | This plan, phase boundaries, E2E matrix, prerequisites, rollout, and cleanup contract | Plan covers every requirement and implementation phase |
| 3/10 — Phase 1: App mode and schema foundation | `feature/slack-multi-agent-app-schema` | PR 2 branch | Additive migrations, App mode, route constraints and availability, admissions, defaults, binding uniqueness, domain/repository models | Existing data backfill tests and ambiguity-abort tests pass; no Multi App creation path exists |
| 4/10 — Phase 2: Mode-aware routing and lifecycle | `feature/slack-multi-agent-app-routing` | PR 3 branch | Remove connection-only route selection, route-neutral source persistence, lock order, mode-specific management/lifecycle, Single App behavior | Existing Single App E2E remains unchanged; all runtime paths are mode-aware |
| 5/10 — Phase 3: Slack interaction and Agent selection | `feature/slack-multi-agent-app-interactions` | PR 4 branch | HTTP/Socket interaction admission, conversation admission, shortcut/modal flow, mention selector, defaults at runtime, approval continuity, Agent presentation | Duplicate/retry/concurrency provider tests pass for HTTP and Socket fixtures |
| 6/10 — Phase 4: Multi App management API | `feature/slack-multi-agent-app-api` | PR 5 branch | Workspace permissions, Multi App management and impact APIs, channel defaults, OpenAPI, generated Python/TypeScript clients | Workspace authorization tests and generated-client drift checks pass |
| 7/10 — Phase 5: Management and selection UI | `feature/slack-multi-agent-app-web` | PR 6 branch | Agent Single App surface, Workspace Multi App table/detail, catalog/defaults, impact dialogs, Slack handoff page, localized copy | Stories, component tests, TypeScript quality, and browser flows pass |
| 8/10 — E2E validation | `validation/slack-multi-agent-app` | PR 7 branch | Complete deterministic E2E matrix, fixture prerequisite audit, migration upgrade evidence, implementation/spec comparison, discovered fixes | All planned E2E and quality commands pass with recorded evidence |
| 9/10 — Spec promotion | `docs/slack-multi-agent-app-specs` | PR 8 branch | Run spec review, update living specs, add `implemented` date to Requirements and Design after verified completion | Specs match implementation; snapshot validation passes |
| 10/10 — Cleanup | `cleanup/slack-multi-agent-app-plans` | PR 9 branch | Remove this implementation plan and phase plans after implementation/spec promotion | No behavior changes; docs hooks and CI pass |

All PR titles use the exact `Slack multi-agent apps [N/10]: ...` prefix. All descendant
branches remain based on the preceding stack branch until front-to-back merge and
retargeting.

## Stable Delivery Team

| Role | Assigned subagent | Persistent ownership | Planned phases |
| --- | --- | --- | --- |
| Implementation owner | `slack-app-impl-v3` | Phase-plan-bounded implementation and focused validation across backend, API, Web, testenv, documentation promotion, and cleanup paths | PR 3 through PR 10 |
| Independent reviewer | `slack-app-review-v2` | Read-only independent review against the approved documents, current phase execution plan, diff, migration safety, runtime correctness, authorization, UI behavior, and validation evidence | PR 3 through PR 10 |

The primary agent is the sole orchestrator and integration owner. It creates and
updates phase execution plans, assigns and continues the stable role owners, verifies
their output, applies accepted localized review findings, controls phase progression,
creates PRs, and monitors CI. Implementation remains owned by the implementation
subagent. Workstream-level reimplementation returns to that owner.

The original implementation assignment `slack-app-impl-v2` became unavailable before
producing an implementation artifact and was replaced by `slack-app-impl-v3`.
`slack-app-impl-v3` is the continuing implementation owner; a phase change is not a
reason to replace it. The independent reviewer did not participate in implementation.

## Dependency and Parallelization Map

- PRs 1 through 10 are sequential stack dependencies and no later-phase
  implementation starts before the preceding PR exists.
- Within a phase, work may run in parallel only when the phase execution plan assigns
  non-overlapping paths and all required interfaces already exist.
- Shared schema, generated artifacts, routing contracts, and integration files have
  one implementation owner at a time.
- The independent reviewer starts only after primary verification of the complete
  phase diff.
- Every implementation PR adds and reports its own tracked phase execution plan
  before implementation work begins.

## Cross-Phase Invariants

The following invariants apply to every phase:

- Never infer an execution User from Slack sender, uploader, requester, approver,
  Agent administrator, Workspace administrator, or broker wake-up.
- PostgreSQL canonical state remains authoritative. Provider callbacks and brokers
  only route or wake durable work.
- Existing migration files are immutable. Generate every new Alembic revision with
  `alembic revision`, review it, and update the revision pointer.
- Do not create Multi App data while a connection-only `limit(1)` routing path exists.
- A Slack resource has at most one active binding regardless of route.
- Existing route, binding, Session, approval, message, and history identities are not
  moved between Single Apps and Multi Apps.
- App mode is immutable and no Single-to-Multi conversion API or fallback is added.
- Generated OpenAPI clients are updated only through generators.
- No provider secret, response URL, raw interaction body, Slack message text, file
  bytes, or private image URL enters logs or validation evidence.
- Slack file-upload rejection diagnosis remains a separate maintenance concern and is
  not mixed into this feature stack.

## Phase Details

### PR 1 — Design baseline

Already prepared from the confirmed collaborative design. It contains no runtime or
living-spec behavior changes.

Validation:

- documentation snapshot/frontmatter validation;
- generated docs index through pre-commit;
- `git diff --check`; and
- complete REQ-1..14 and ADR-D1..8 traceability.

### PR 2 — Implementation plan

Record the review and delivery contract before code changes. This PR contains no
schema or runtime behavior.

Validation:

- docs hooks;
- plan-to-design phase coverage; and
- confirmation that no current-behavior spec is changed early.

### PR 3 — App mode and schema foundation

#### Data changes

- Add immutable connection App mode and backfill existing rows to `single`.
- Add the connection mode constraint shadow on Agent routes.
- Add unique connection/Agent association and Single App route cardinality.
- Add Multi App catalog availability fields.
- Add provider interaction admission, conversation admission, and channel-default
  tables.
- Replace active `(resource_id, route_id)` binding uniqueness with resource-wide
  active uniqueness after a preflight.
- Preserve the current route-mode column and behavior for rolling compatibility.

#### Domain and repository changes

- Add enums, models, DTOs, named indexes, foreign keys, and repository operations for
  the new records.
- Add migration guards for missing/duplicate Single routes, cross-Workspace routes,
  duplicate associations, and multiple active bindings.
- Add no-op-compatible defaults so old writers continue producing Single App data.

#### Tests

- migration upgrade from representative pre-feature schema/data;
- every migration ambiguity abort condition;
- model/constraint tests for Single and Multi cardinality;
- interaction and conversation admission uniqueness;
- channel-default connection/route ownership; and
- resource-wide binding uniqueness.

No API can create a Multi App in this phase.

### PR 4 — Mode-aware routing and lifecycle

#### Runtime changes

- Replace every connection-only route lookup with binding, Single sole-route,
  channel-default, or selected-admission resolution.
- Persist resources/messages/revisions before selecting a route.
- Materialize pending context only after route selection.
- Introduce one connection→route→resource→binding→admission/request lock order across
  event processing, approval, disconnect, hydration, and decommission.
- Make current Agent-scoped management explicitly Single App-only.
- Add Multi route removal and whole Multi connection lifecycle services without
  exposing creation APIs yet.
- Preserve existing authorization, hydration, invocation-batch, AgentSession, Channel
  Work, delivery, archive, restore, purge, and decommission ownership.

#### Tests

- existing Single App event/approval/binding/lifecycle regression suite;
- no arbitrary route selection with multiple internal fixture routes;
- route removal and default invalidation transaction tests;
- concurrent binding creation and approval conflicts;
- Agent decommission and Session lifecycle behavior; and
- runtime fail-closed behavior for invalid mode/cardinality state.

This phase is the minimum runtime version required before Multi App data may exist.

### PR 5 — Slack interaction and Agent selection

#### Provider changes

- Extend the fixed HTTP endpoint to route form-encoded Slack interactions after raw
  signature/replay verification.
- Extend Socket Mode dispatch to interactive envelopes with durable admission before
  acknowledgement.
- Add bounded parsers and Slack Web API operations for shortcut, block action, modal
  open/update, option loading or pagination, and view submission.
- Add interaction expiry and duplicate-safe state transitions.

#### Conversation changes

- Add the message shortcut source-retention and selector flow.
- Add mention-without-default selection control and shared selector.
- Resolve Single sole route and Multi channel defaults through conversation admission.
- Reuse existing Agent-specific approval after selection.
- Reject stale/removed/cross-Workspace route submissions without execution.
- Render the current Agent name in bold at the top of every Agent-associated Slack
  output.
- Use Agent image icon override only when the validated capability is present; fall
  back without delivery failure.

#### Fixture and tests

- signed HTTP interaction callbacks and duplicates;
- Socket interactive envelopes and acknowledgements;
- modal trigger expiry, view-hash conflicts, stale submissions, and catalog changes;
- large Agent catalog paging/search without silent truncation;
- shortcut source text/file retention and approval continuation;
- mention selector and channel-default resolution;
- duplicate selection and resource binding races; and
- Agent-name/icon rendering for text, progress, controls, errors, and files.

### PR 6 — Multi App management API and generated clients

#### Authorization

- Add External Channel Workspace read/write permissions.
- Grant read/write to Workspace Owner and Manager.
- Keep ordinary Members outside Multi App management authority.
- Keep AgentAdmin authority scoped to Single App management.

#### API changes

- Add Workspace Multi App list/create/read/update/validate/disconnect operations.
- Add Agent catalog list/add/remove and re-enable operations.
- Add channel-default list/set/replace/clear operations.
- Add impact preview and generation-fenced destructive mutations.
- Add opaque Slack-to-Azents channel-management handoff loading.
- Keep the existing Agent-scoped routes as the formal Single App API.

#### Generated artifacts and tests

- dump Public OpenAPI;
- regenerate Python and TypeScript public clients;
- update typed tRPC boundaries only through generated operations;
- test zero-Agent creation, Workspace authorization, cross-Workspace rejection,
  impact conflicts, redacted credentials, and pagination; and
- confirm no Multi mutation is exposed through Agent-scoped endpoints.

This phase is merged/deployed only after the mode-aware runtime phase is present on all
instances. It is the backend Multi App enablement boundary.

### PR 7 — Management and selection UI

#### Agent settings

- Keep `Connect Slack` as the Single App action with no mode selector.
- Show Single App health, transport, capability, edit, validate, and disconnect.
- Explain that Single disconnect removes the App and terminates affected threads.
- Show associated Multi Apps in a separate read-only Workspace-managed subsection.

#### Workspace integrations

- Add an operational Multi App table and detail workspace.
- Support zero-Agent setup, Agent catalog management, health/edit/validate,
  channel-default management, impact previews, and full disconnect.
- Keep controls adjacent to the App, Agent association, or channel default they
  mutate.
- Cover loading, empty, reconnect required, permission denied, stale preview,
  invalidated default, large-list pagination, and mobile states.

#### Slack management handoff

- Add the authenticated focused Web page opened from Slack.
- Recheck Workspace write permission and handoff expiry before showing or mutating the
  current channel default.

#### Tests

- pure component stories and interaction tests;
- container/tRPC integration tests;
- sequential TypeScript format, lint, typecheck, tests, and build; and
- browser flows for Single and Multi management.

### PR 8 — E2E/testenv validation

Run the complete primary matrix below against deterministic HTTP and Socket Slack
fixtures. Record commands, environment, fixture versions, results, and sanitized
evidence. Fix implementation defects in this PR or in the responsible earlier branch,
then rebase descendants with `scripts/rebase-stacked-prs.sh`.

Also produce a strict implementation-versus-current-spec comparison. Do not update
living specs in this PR unless a discovered correctness fix changes behavior that
cannot safely wait for spec promotion.

### PR 9 — Spec promotion

Run `/spec-review` against the complete implementation and validation evidence.
Expected spec candidates:

- `docs/azents/spec/domain/external-channel.md`;
- `docs/azents/spec/flow/external-channel-provider-ingress.md`;
- `docs/azents/spec/flow/external-channel-authorization.md`;
- `docs/azents/spec/flow/external-channel-lifecycle.md`;
- `docs/azents/spec/flow/external-channel-delivery.md`;
- Agent and Workspace domain specs if permission or management ownership changes are
  not already covered by External Channel specs.

After implementation and validation are complete, add the same implementation date
to the Requirements and Design snapshots. Do not rewrite the accepted ADR.

### PR 10 — Cleanup

Remove this implementation plan and all phase-specific plans. Keep immutable
Requirements/ADR/Design history and current living specs. Do not include runtime,
refactor, test, or dependency changes.

## E2E Primary Validation Matrix

| Requirement group | Scenario | Primary phase | Required fixture/evidence |
| --- | --- | --- | --- |
| `REQ-3`, `REQ-12` | Existing dedicated connection migrates to Single App with unchanged invocation, binding, Session, and credentials | PR 4 / PR 8 | Pre-feature DB snapshot plus signed HTTP and Socket events |
| `REQ-1`, `REQ-4` | Workspace authority creates and manages zero-Agent and populated Multi Apps | PR 6 / PR 8 | Workspace Owner, Manager, Member fixtures and multiple Slack installations |
| `REQ-2` | One Multi App exposes several Agents and one Agent appears in several Apps without duplicate association | PR 6 / PR 8 | Multiple Agents, Single Apps, and Multi Apps in one Workspace |
| `REQ-5`, `REQ-6` | Shortcut lists available and access-required Agents, retains source text/files, and selects once | PR 5 / PR 8 | Signed shortcut, modal, files metadata, duplicate submission |
| `REQ-7` | Web and Slack handoff show and mutate one channel default under Workspace authority | PR 6-7 / PR 8 | Current-channel interaction and authenticated Web session |
| `REQ-8` | Mention without default creates a selector but no channel default | PR 5 / PR 8 | Events API mention plus block action/modal callback |
| `REQ-9` | Concurrent default, shortcut, and modal submissions create one binding and Session | PR 4-5 / PR 8 | Deterministic barrier/race fixture and DB assertion |
| `REQ-10` | Access-required selection creates no run before Allow and releases original source exactly once | PR 5 / PR 8 | Approval decision fixture, duplicate callbacks, retained files |
| `REQ-11` | Multi association removal keeps App/other Agents, while Single removal disconnects the App | PR 4,6-7 / PR 8 | Impact preview, active bindings/defaults, post-removal messages |
| `REQ-13` | Cross-App/Workspace/Agent/principal payloads fail without invocation | PR 4-6 / PR 8 | Forged IDs, stale modal state, wrong connection, inactive Agent |
| `REQ-14` | Every Agent output starts with bold name and icon override safely falls back | PR 5 / PR 8 | Capability on/off, image present/missing/invalid, text/progress/file output |
| `ADR-D7` | Multi creation remains unavailable until mode-aware runtime enablement | PR 3-6 / PR 8 | Phase-gate configuration and mixed-version safety assertion |

## Fixture and Prerequisite Support

### Required deterministic support

The Slack provider fake must support:

- signed JSON Events API and form-encoded interactivity on the fixed HTTP endpoint;
- Socket Mode `events_api` and interactive envelopes with acknowledgement capture;
- message shortcuts, block actions, modal open/update/submission, view hashes, and
  option/pagination callbacks;
- conversations, channel labels, source messages, metadata-only files, and Agent
  selector state;
- duplicate, reordered, expired, rate-limited, and provider-rejected callbacks;
- message posting, updates, file completion, optional icon override, and sanitized
  operation capture; and
- distinct provider App/Team identities for Single and Multi fixtures.

### Credential and environment snapshot

Deterministic E2E uses fake credentials only. A test prerequisite snapshot records
fixture App IDs, Team IDs, transports, granted capabilities, Workspace roles, Agent
administrators, Agents, channels, and expected route/binding identities. It contains
no real tokens or message/file contents.

Live Slack validation is optional diagnostic evidence. It requires an explicitly
provisioned test Workspace/App/channel and is skipped when credentials are absent.
Deterministic fixture failures are never converted to skips.

### External/manual prerequisites

- Newly created Multi Apps need Slack interactivity and shortcut configuration in the
  generated manifest/manual guide.
- Agent image override for new Apps needs Slack message-customization capability.
- Existing Single Apps are not required to reinstall or reauthorize; missing
  capability uses the default bot icon.
- Production Multi App creation remains blocked until operators confirm every API and
  worker instance is mode-aware.

No external prerequisite blocks schema, runtime, API, Web, or deterministic E2E
implementation.

## Test Strategy by Phase

| Phase | Python | TypeScript | Migration/API | E2E |
| --- | --- | --- | --- | --- |
| PR 3 | Ruff, format, Pyright, focused repository/model Pytest | None unless shared types change | Alembic upgrade/constraint tests | Migration fixture only |
| PR 4 | Ruff, format, Pyright, event/access/lifecycle Pytest | None | Existing Single APIs regression | Existing Single Slack flows |
| PR 5 | Ruff, format, Pyright, HTTP/Socket/interaction/delivery Pytest | Fixture types if needed | Provider contract tests | Shortcut/default/approval/race flows |
| PR 6 | Ruff, format, Pyright, management/auth/API Pytest | Generated-client checks | OpenAPI dump and client generation | Workspace authorization API flows |
| PR 7 | Backend focused tests for handoff | Format, lint, typecheck, tests, build sequentially | Generated client usage | Agent/Workspace browser flows |
| PR 8 | Full affected Python quality suite | Full affected TypeScript quality suite | Migration from representative snapshot, API drift | Complete deterministic matrix |
| PR 9 | Spec-linked focused checks | Spec-linked checks as needed | Snapshot/docs validation | No new behavior; evidence references PR 8 |
| PR 10 | Docs hooks | None | None | None |

## Known Blockers and Risks

No known product or architecture blocker remains.

Non-blocking implementation risks:

- PostgreSQL cardinality and active-binding constraints require careful migration
  preflight and canonical lock-order changes.
- Slack modal limits require paged or remotely loaded large catalogs without silent
  truncation.
- Provider-safe Agent avatar URLs may be unavailable; bold Agent name is the required
  fallback identity.
- Native Slack task/plan blocks must accept the shared leading Agent-name section;
  deterministic provider fixtures must validate the exact payload.
- Once Multi data exists, old connection-only runtime rollback is unsafe and is not a
  supported recovery path.

## Rollout Notes

- Merge and deploy front-to-back.
- Do not enable or expose Multi App creation before PR 4 mode-aware runtime is fully
  deployed on every API and worker instance.
- PR 6 is the backend Multi App enablement boundary; verify the runtime fleet before
  deployment or route exposure.
- Stop new Multi mutations and forward-fix after enablement failures. Do not downgrade
  or stamp the production database.
- Existing Single connections and credentials remain active throughout the additive
  and runtime phases.
- Request hardtack review on every PR.
- Create the entire current stack before waiting on CI; then monitor all PRs and fix
  failures on the responsible branch before rebasing descendants.

## Cleanup Contract

This plan and any phase-specific plans are temporary implementation artifacts. PR 10
removes them only after:

- all implementation PRs are merged or merge-ready and validated;
- the complete E2E matrix passes;
- current specs describe the implemented behavior;
- Requirements and Design share the verified `implemented` date; and
- no open implementation or spec blocker remains.
