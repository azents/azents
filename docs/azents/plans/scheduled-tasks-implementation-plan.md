---
title: "Scheduled Tasks Implementation Plan"
created: 2026-08-16
tags: [scheduled-task, scheduler, engine, external-channel, api, frontend, testenv]
---

# Scheduled Tasks Implementation Plan

- Requirements: [`scheduled-260816/REQ`](../requirements/scheduled-260816-agent-scheduled-tasks.md)
- Decisions: [`scheduled-260816/ADR`](../adr/scheduled-260816-agent-scheduled-tasks.md)
- Approved Design: [`scheduled-260816/DESIGN`](../design/scheduled-260816-agent-scheduled-tasks.md)
- Approved Design revision: `3`
- Approved mechanism IDs: `M1` through `M15`
- Design delta: `None`
- Implementation owner: Primary agent (`/root`)
- Independent reviewer: `scheduled-stack-reviewer` (`/root/scheduled-stack-reviewer`)

## Delivery Shape

The feature ships as one documentation base PR followed by eight stacked
implementation PRs. The documentation PR records the approved authority and delivery
plan before code review begins. Each implementation PR owns one reviewable integration
boundary, carries its mandatory phase execution plan, and receives focused local
validation and independent review. All nine PRs are created before stack-wide CI
monitoring begins.

| Phase | Branch | Base | PR title | Approved mechanisms | Primary boundary |
| --- | --- | --- | --- | --- | --- |
| Docs | `feature/scheduled-tasks-0-docs` | `origin/main` | `Scheduled Tasks: Approve design and delivery plan` | approved `M1`–`M15` authority | Requirements, ADR, approved Design revision 3, implementation plan, and Phase 1 execution plan |
| 1 | `feature/scheduled-tasks-1-foundation` | Docs | `Scheduled Tasks [1/8]: Add the domain foundation` | `M1`, `M3`, `M4`, `M13`, `M14` | generated schema migration, Task persistence, AgentRun binding field, closed Mailbox/Event readers and projections |
| 2 | `feature/scheduled-tasks-2-dispatch` | Phase 1 | `Scheduled Tasks [2/8]: Add dispatch and start admission` | `M1`, `M2`, `M3`, `M4`, `M13` | schedule validation, Task service, bounded Scheduler dispatcher, cycle admission, FIFO trigger, pending-to-started Run binding |
| 3 | `feature/scheduled-tasks-3-toolkit` | Phase 2 | `Scheduled Tasks [3/8]: Add ScheduledToolkit execution` | `M3`, `M5`, `M9`, `M10`, `M13`, `M15` | root-only auto-bound Toolkit, managed Skill VFS source, idle and compaction continuity, terminal result transaction, run-terminal tool behavior |
| 4 | `feature/scheduled-tasks-4-channel` | Phase 3 | `Scheduled Tasks [4/8]: Add channel presentation and progress` | `M6`, `M8`, `M12` | exact Binding revalidation, registration controls, Scheduled-owned Tracker, interim progress, terminal publication and exact-thread parent surfacing |
| 5 | `feature/scheduled-tasks-5-lifecycle` | Phase 4 | `Scheduled Tasks [5/8]: Integrate Session and Binding lifecycle` | `M4`, `M7`, `M12` | Task and pre-start cleanup, started-cycle preservation, Scheduled-aware archive admission, Binding terminalization, purge ordering |
| 6 | `feature/scheduled-tasks-6-api` | Phase 5 | `Scheduled Tasks [6/8]: Add the Public API and clients` | `M11`, `M12`, `M13` | versioned CRUD/current-cycle API, service authorization, OpenAPI, generated Python and TypeScript clients |
| 7 | `feature/scheduled-tasks-7-web` | Phase 6 | `Scheduled Tasks [7/8]: Add the management interface` | `M11`, `M12` | dedicated Agent route, list/create/edit/delete/progress UI, Session and opaque Binding selection, navigation, stories and localization |
| 8 | `feature/scheduled-tasks-8-validation` | Phase 7 | `Scheduled Tasks [8/8]: Validate and document the feature` | full `M1`–`M15` validation | deterministic testenv/E2E, failure and recovery matrix, removal evidence, Living Spec promotion, implementation dates, plan cleanup |

## Fixed Interfaces and Integration Boundaries

- `scheduled_tasks` is the only durable user Task definition, schedule cursor,
  due-lease, active-fence, and pending-occurrence authority.
- The existing `scheduled_task_states` table remains exclusively owned by
  code-registered maintenance Scheduler tasks.
- Session-scoped Toolkit State under namespace `scheduled` owns admitted and started
  cycle state and Scheduled provider projection. Channel Work state is never reused.
- The generated migration adds the new table, PostgreSQL schedule enum, nullable
  `agent_runs.scheduled_task_cycle_id`, and persisted Mailbox/Event enum values. No
  executed migration is modified and no historical product data is restored.
- Closed Mailbox/Event unions, validators, lowerers, history/live projections, and
  public readers are extended together in Phase 1 before Phase 2 emits any new kind.
- The M4 start boundary crosses the current durable pending-Run and activation
  pipeline. The cycle binding is carried through pending creation and committed in
  the cycle-locking activation transaction that changes the cycle from `admitted`
  to `started`.
- A stale trigger whose Task or active fence disappeared is consumed without an
  AgentRun or transcript event. Deletion after start never removes the cycle binding
  or interrupts the Run.
- `submit_scheduled_task_result` uses an explicit engine-recognized terminal client
  tool outcome. The canonical result Event and cycle/Task transition commit before
  the engine completes the Run and before any provider effect.
- `ScheduledToolkitProvider` is root-only, unprefixed, auto-bound, independent of
  ToolkitConfig or credentials, and owns management tools, execution guidance,
  continuation hooks, terminal action, cycle state, and the release Skill.
- `VfsProjectionService` adds one deterministic required `scheduled` release source
  for eligible root previews and Runs. The persisted AgentRun projection remains
  immutable recovery authority.
- Opaque Binding handles are passed unchanged to the current resolver. Task rows
  store only the resolved Binding ID; every mutation and provider effect reloads and
  revalidates current Workspace, Agent, Session, Binding, route, connection, and
  provider authority.
- Provider registration, progress, terminal publication, parent surfacing, and
  Tracker cleanup are immediate process-local effects after canonical commit. There
  is no durable outbox, retry, replay, compensation, or fallback destination.
- Slack exact-thread terminal parts use `reply_broadcast=true`. Discord exact-thread
  parts are created in the Thread and the exact messages are forwarded to the
  parent through a typed public-SDK forwarding operation.
- `session.scheduled-task` owns row-scoped Task/cycle cleanup without claiming the
  whole Mailbox or Toolkit State tables. It depends on `session.execution`, and
  `session.external-channel` is ordered after it so Task references are removed
  before Binding purge and verification.
- Session archive retains ordinary running-work rejection. It permits archive only
  when every active Run in the locked subtree is bound to a valid started Scheduled
  cycle that the archive transition preserves. Archived Sessions admit only the
  matching typed Scheduled continuations.
- Binding disconnect and every route, connection, App-uninstall, Agent-decommission,
  and Session-archive terminalization path invoke the Scheduled collaborator inside
  the caller-owned transaction. Started cycles survive while later provider effects
  fail closed.
- Public API, Agent tools, Web mutations, and provider controls use one shared Task
  service and exact authorization rules. No route or tool alias, fuzzy lookup,
  implicit Session creation, compatibility reader, or legacy mode is added.
- The Web create flow selects an authorized existing root Session or uses the current
  empty Team Session creation API. It does not add a new empty User Session contract.
- Generated clients are regenerated from the canonical Public OpenAPI document and
  are never edited manually.

## Phase Dependencies and Context Checkpoints

### Phase 1 — Domain foundation

Inputs: approved revision 3, current PostgreSQL model conventions, closed
Mailbox/Event registries, and the current AgentRun schema.

Outputs:

- one generated linear Alembic revision and revision marker;
- new Task model/repository contracts and schedule data types;
- nullable AgentRun cycle binding through persistence data contracts;
- closed trigger, continuation, and result payload readers plus all lowerers and
  public history/live projections; and
- migration, payload, projection, and absence evidence.

Checkpoint to Phase 2: every reader accepts the new persisted variants, no producer
emits them, and no product Task uses `scheduled_task_states`.

### Phase 2 — Dispatch and start admission

Inputs: Phase 1 schema, Task repository, AgentRun field, and closed protocol readers.

Outputs:

- canonical one-time/cron validation and cursor calculation;
- shared Task create/list/edit/delete service without API or Toolkit exposure;
- one bounded user-Task dispatcher registered in the existing Scheduler;
- due lease, missed-run coalescing, active/pending fences, cycle Toolkit State
  snapshot, idempotent trigger Mailbox item, and post-commit Session wake;
- pending-to-started Run binding transaction and deletion race behavior; and
- deterministic lease, DST, coalescing, wake-loss, FIFO, recovery, and race tests.

Checkpoint to Phase 3: Session-only cycles can be admitted and bound to Runs through
the existing worker pipeline, but no Agent-facing management or terminal tool exists.

### Phase 3 — ScheduledToolkit execution

Inputs: Phase 2 Task service, cycle admission, and Run binding.

Outputs:

- root-only auto-bound ScheduledToolkit and management tools;
- immutable managed Skill VFS projection under
  `azents://skills/scheduled/scheduled-task/SKILL.md`;
- cycle-specific dynamic guidance and deterministic idle continuation;
- sanitized active-cycle compaction-summary enrichment through the existing ordered
  hook pipeline;
- run-bound terminal tool, dedicated result Event, idempotent terminal transaction,
  one-time deletion, recurring pending/future advancement, and no-extra-turn Run
  completion; and
- Session-only Agent/tool, continuation, recovery, and terminal tests.

Checkpoint to Phase 4: the complete Session-only product path works without provider
presentation and no terminal history is stored in the Task product.

### Phase 4 — External Channel presentation and progress

Inputs: Phase 3 canonical Task/cycle/terminal boundaries and current External Channel
authorization and delivery primitives.

Outputs:

- post-create Slack and Discord registration presentations and edit/delete controls;
- idempotent provider interaction claim, Task reload, principal/Binding revalidation,
  and shared service mutation;
- Scheduled-owned Tracker desired/projection state and cycle-aware
  `channel_action continue`;
- rejection of `finish` and `ignore` for Scheduled cycles;
- one-attempt terminal publication, Slack thread broadcast, Discord native forwarding,
  and Tracker cleanup; and
- provider failure, ambiguity, coexistence, multipart ordering, and no-replay tests.

Checkpoint to Phase 5: channel-bound execution and provider presentation work while
Task, Session, and Binding lifecycle cleanup still uses only explicit Task deletion.

### Phase 5 — Session and Binding lifecycle

Inputs: Phase 4 Scheduled provider projections and Phase 3 terminal path.

Outputs:

- `session.scheduled-task` lifecycle participant with scoped row ownership;
- archive/purge ordering before External Channel Binding verification;
- Task, pending, admitted-cycle, trigger, and Scheduled Tracker cleanup;
- preservation of started cycles, Runs, continuation authority, and Session terminal
  results;
- Scheduled-only running archive and archived-continuation exception;
- integration in every Binding terminalization path with no transient-health cleanup;
  and
- archive, restore, purge, route, connection, uninstall, decommission, and no-
  interruption tests.

Checkpoint to Phase 6: backend lifecycle semantics are complete and all product
mutations can share one stable service boundary.

### Phase 6 — Public API and generated clients

Inputs: stable backend Task, execution, provider, and lifecycle services.

Outputs:

- `/scheduled-task/v1` list/create/get/replace/delete/current-cycle routes;
- exact Workspace/Agent/Session/Binding authorization and sanitized errors;
- canonical Public OpenAPI update;
- regenerated Python and TypeScript public clients; and
- route, service authorization, schema, OpenAPI drift, and generated-client tests.

Checkpoint to Phase 7: Web can consume one generated stable API contract with no raw
HTTP or hidden internal identifiers.

### Phase 7 — Web management interface

Inputs: Phase 6 generated TypeScript client and existing Agent/Session/Binding routes.

Outputs:

- dedicated Agent Scheduled Tasks route and navigation;
- container/component/page implementation with ADT state;
- list, create, detail, edit, delete, current progress, target labels, future
  eligibility, Session create/select, opaque Binding select, and Session navigation;
- no transcript, terminal history, pause, resume, rerun, or cancel-current-cycle
  controls;
- generated-client tRPC router and cache invalidation;
- localized copy, responsive UI, and colocated stories; and
- focused TypeScript and Storybook tests.

Checkpoint to Phase 8: all user-visible product surfaces exist and the remaining work
is deterministic integrated verification and documentation promotion.

### Phase 8 — Validation, Specs, and cleanup

Inputs: stable complete Phase 7 stack and fresh deterministic prerequisites.

Outputs:

- clock-controlled dispatcher, worker-drain, crash-point, lifecycle, and provider
  fake support;
- required API E2E and Web E2E across Session-only, Slack parent/thread, and Discord
  parent/thread scenarios;
- failure, recovery, no-replay, no-interruption, authorization, and exact-thread
  evidence;
- full authority, scope-drift, removal, and absence audit;
- Living Spec promotion and matching Requirements/Design `implemented` date after
  validation passes; and
- deletion of this plan and every Scheduled Tasks phase plan.

Checkpoint: all eight PRs exist, all required CI checks pass, and no PR is merged
without separate requester approval.

## Workstream Ownership

| Workstream | Owner | Primary paths | Interfaces produced or consumed |
| --- | --- | --- | --- |
| Shared authority, plans, migrations, integration | `/root` | snapshot docs, `docs/azents/plans/**`, shared enums/composition, migration generation and revision, cross-phase integration | approved authority, branch stack, common contracts, generated schema |
| Task persistence and Scheduler | `/root/scheduled-data-scheduler-scout` | `rdb/models/scheduled_task.py`, `repos/scheduled_task/**`, Scheduler dispatcher and focused tests | Task rows, schedule cursor, leases, dispatcher outcome |
| Mailbox, AgentRun, Toolkit, and engine execution | `/root/scheduled-toolkit-runtime-scout` | AgentRun persistence, Mailbox/Event contracts, worker admission, ScheduledToolkit, VFS, terminal execution and focused tests | cycle binding, typed inputs/results, Toolkit tools/hooks |
| External Channel and lifecycle | `/root/scheduled-channel-lifecycle-scout` | Scheduled provider projection/effects, Slack/Discord adapters and interactions, Session/Binding lifecycle and focused tests | exact Binding effects, Tracker, controls, cleanup |
| Public API, Web, and E2E surfaces | `/root/scheduled-api-web-e2e-scout` | Scheduled Public API, generated-client integration, azents-web feature/tRPC, deterministic E2E/testenv and focused tests | public contract, management UI, integrated evidence |
| Independent review | `/root/scheduled-stack-reviewer` | read-only phase diff | authority, security, lifecycle, migration, removal, and scope-drift report |

Shared files are assigned explicitly in each phase plan before implementation. No two
implementation owners edit the same file concurrently. The reviewer never edits.

## Removal Obligations

| Removal or preserved absence | Owning phase | Replacement or remaining authority | Absence verification |
| --- | --- | --- | --- |
| Historical owner-user/status/provider-coordinate `scheduled_tasks` shape | 1 | new M1 Task schema | migration/model assertions and source search for removed fields |
| Product use of `scheduled_task_states` | 1 | new `scheduled_tasks`; existing table remains maintenance-only | repository and Scheduler tests plus static import search |
| Historical `schedule_create`, `schedule_list`, and `schedule_delete` contracts | 3 | exact new management tools | tool catalog and repository search; no alias or fuzzy lookup |
| Session-per-occurrence execution | 2 | selected existing Session, FIFO Mailbox, AgentRun, cycle Toolkit State | E2E stable Session ID and static Session-creation path search |
| Reusing Channel Work state for Scheduled progress | 4 | Scheduled cycle-owned projection | coexistence tests and namespace/state-owner assertions |
| Missing Public API/generated client surface | 6 | versioned M11 API and generated clients | OpenAPI route and generated package assertions |
| Missing Web management surface | 7 | dedicated Agent feature | route/component/E2E assertions |
| Durable Scheduled provider delivery/replay | 4 | immediate process-local effects only | schema/source search and failure/no-replay tests |
| Legacy compatibility, duplicate scheduler, or permanent rollout flag | 8 | none | final route/tool/config/schema search |
| Temporary implementation and phase plans | 8 | approved Design and promoted Living Specs | final tree absence check |

## Validation Matrix

- Phase-focused Python: Ruff check, Ruff format check, `ty --error-on-warning`, and
  targeted pytest modules from the relevant Python project.
- Migration: generated linear revision, latest-head marker, upgrade/downgrade on
  empty/test databases, pytest-alembic, model constraints, and no historical backfill.
- Protocol: closed Mailbox/Event payload validation, every supported model lowerer,
  filters, transcript/history/live projections, and exhaustive-match type checks.
- Scheduler and execution: lease reclaim, DST, missed/coalesced occurrences, one active
  plus one pending, wake loss, FIFO ordering, deletion race, Run recovery, idle
  continuation, multiple-cycle compaction continuity during unrelated Runs,
  deterministic due-time tie ordering, stale-section replacement, lifecycle
  independence, sanitization, terminal idempotency, and no-extra-turn completion.
- External Channel: opaque Binding authorization, registration controls, Scheduled
  Tracker coexistence, progress fences, Slack broadcast, Discord forward, multipart
  order, provider failure/ambiguity, cleanup, and no replay.
- Lifecycle: Task deletion, Session archive/restore/purge, Binding/route/connection/App
  termination, Agent decommission, transient health preservation, started-cycle
  continuation, and unrelated archived-work rejection.
- Generated contracts: canonical OpenAPI dump plus generated Python and TypeScript
  clients and source-drift checks.
- Web: format, lint, typecheck, build, feature tests, stories, localization, responsive
  states, and browser E2E screenshots.
- Deterministic required E2E: Session-only and provider-fake Slack/Discord parent/thread
  scenarios with no external credential dependency or direct product DB writes.
- Optional live provider smoke tests may skip only when the declared credential
  prerequisite snapshot is absent; they never replace deterministic CI evidence.
- Final: full affected Python, TypeScript, testenv, docs, spec-review, removal, and
  stack CI checks.

## Prerequisites and Blockers

- PostgreSQL is required for migrations, leases, Task/cycle invariants, and lifecycle
  integration tests.
- Docker/Testcontainers and the local Runtime Provider are required for deterministic
  required E2E and migration integration.
- Redis may be present for existing wake routing but is never correctness authority.
- Mandatory CI uses Slack and Discord provider fakes; live credentials are optional.
- The current Chat API can create an empty Team Session and list authorized persistent
  root Sessions. The Web flow uses those existing contracts and does not introduce an
  empty User Session API.
- Current implementation gaps—the pending-to-activation Run boundary, terminal-tool
  Run-completion signal, scoped lifecycle row ownership, Slack broadcast, Discord
  forwarding, and Scheduled interaction dispatch—are bounded implementation work
  under approved M4, M5, M7, M8, M12, and M13.
- Any new durable authority, product state, compatibility fallback, destination
  fallback, interruption behavior, configuration mode, or user-visible contract
  returns to Requirements → ADR → Design. Current readiness review found no such
  blocker and `Design delta` remains `None`.

## Review and Stack Policy

The exact independent reviewer for every phase is
`/root/scheduled-stack-reviewer`. Review inputs are the confirmed Requirements,
accepted ADR-D1 through D7, approved Design revision 3 and M1–M15, current Living
Specs, the phase execution plan, focused evidence, and the stable phase diff.

Review priority is Requirements and Design authority, security/privacy, migration
safety, data loss, lifecycle non-interruption, source-of-truth duplication, removal
obligations, provider replay/fallback, generated-contract drift, and unauthorized
scope.

Each phase is committed and opened as a PR before the next phase starts. All eight
PRs are created before CI monitoring. Corrections to an earlier phase use the
repository stacked-PR workflow and rebase dependent branches. PRs are never merged
without explicit requester approval.
