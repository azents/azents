---
title: "Scheduled Task Domain Spec"
created: 2026-08-16
tags: [backend, engine, scheduler, toolkit, external-channel, api, frontend]
spec_type: domain
domain: scheduled-task
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/7686aeee9531_add_scheduled_tasks_domain_foundation.py
  - python/apps/azents/src/azents/api/public/scheduled_task/**
  - python/apps/azents/src/azents/api/testenv/scheduler/**
  - python/apps/azents/src/azents/engine/tools/scheduled.py
  - python/apps/azents/src/azents/rdb/models/scheduled_task.py
  - python/apps/azents/src/azents/repos/scheduled_task/**
  - python/apps/azents/src/azents/repos/scheduled_task_cycle/**
  - python/apps/azents/src/azents/resources/vfs/toolkits/scheduled/**
  - python/apps/azents/src/azents/scheduler/user_scheduled_task_dispatch.py
  - python/apps/azents/src/azents/services/scheduled_task/**
  - python/apps/azents/src/azents/services/external_channel/channel_action.py
  - python/apps/azents/src/azents/services/external_channel/discord_http.py
  - python/libs/azents-public-client/src/azentspublicclient/api/scheduled_task_v1_api.py
  - python/libs/azents-public-client/src/azentspublicclient/models/scheduled_task_*.py
  - typescript/apps/azents-web/src/features/chat/**
  - typescript/apps/azents-web/src/features/scheduled-tasks/**
  - typescript/apps/azents-web/src/features/agents/components/AgentSessionHeader.tsx
  - typescript/apps/azents-web/src/trpc/routers/scheduledTask.ts
  - typescript/apps/azents-web/src/app/(app)/w/[handle]/(agent)/agents/[agentId]/sessions/[sessionId]/**
  - testenv/azents/e2e/src/tests/required/public/test_scheduled_tasks.py
api_routes:
  - /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks
  - /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}
  - /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}/cycle
last_verified_at: 2026-08-21
spec_version: 8
---

# Scheduled Task Domain Spec

## Overview

A Scheduled Task is a durable, Session-owned instruction to perform work once at
an exact instant or repeatedly from a cron expression. It reuses the selected
Session, its accumulated context, the existing Scheduler role, FIFO Mailbox
admission, AgentRun execution, Toolkit State, and optional External Channel
Binding. It does not create a Session per occurrence and does not maintain a
separate terminal-history product.

The PostgreSQL `scheduled_tasks` row is the only durable scheduling authority for
user-defined work. The existing `scheduled_task_states` table remains exclusively
the current-state store for code-registered maintenance tasks.

## Durable Task Model

Each `scheduled_tasks` row stores:

- immutable Task ID plus Workspace, Agent, and Session ownership;
- optional exact External Channel `binding_id`;
- editable `title` and `objective`;
- one canonical schedule shape;
- `next_eligible_at`;
- one active-cycle fence and at most one coalesced pending occurrence;
- an expiring due-claim lease; and
- created and updated timestamps.

The canonical schedule shapes are:

- `once`: aware `scheduled_at`, no cron expression, and no timezone;
- `cron`: cron expression plus IANA timezone, and no `scheduled_at`.

Schedule, active-cycle, and pending-occurrence shapes are enforced both by service
validation and database constraints. One-time Tasks disappear after their cycle
terminalizes. Recurring Tasks advance their cursor and remain available for later
occurrences.

An active cycle is stored in Session-scoped Toolkit State, not in another product
table. Its immutable snapshot retains the Task, Session, optional Binding,
schedule, and `scheduled_for` values that were admitted. Mutable state records
`admitted` or `started`, current Run identity, progress title and ordered work
items, and current provider Tracker projection parts.

## Authority and Management

All management paths validate the current Workspace, Agent, root Session, and
optional Binding authority. Binding IDs are opaque exact identifiers; there is no
fuzzy lookup, fallback Binding, or parent/thread substitution.

The Public API supports:

- list Tasks for one Session or all authorized Sessions of an Agent;
- create a Task for an existing authorized Session;
- get one exact Task;
- replace future definition and target fields;
- permanently delete one Task; and
- read a sanitized current-cycle projection.

Task replacement removes an admitted pre-start cycle and its trigger before
replacing the definition. A one-time Task with a started cycle rejects replacement.
A recurring Task with a started cycle preserves that immutable cycle snapshot,
clears pending work, and replaces only the definition and schedule used by future
cycles. Management projections derive `idle`, `admitted`, `running`, or
`running_with_pending` execution state and return a canonical Session navigation
identity. Current-cycle responses omit internal cycle, Run, lease, and
provider-message identities.

Each concrete Session page exposes a Scheduled Tasks tab backed by generated
Public API client functions through tRPC. The tab lists only that Session's Tasks
and fixes create, edit, and connected-channel selection to the current Session.
It provides list/detail, create, replace, future-schedule cancellation, schedule
editing, optional connected-channel selection, and current progress. Cancellation
requires explicit confirmation and uses the existing Public API delete operation.
It does not expose transcript/history, pause, resume, rerun, or
cancel-current-cycle controls.

## Agent Toolkit and Skill

`ScheduledToolkit` is an unprefixed, root-only, automatically connected Toolkit.
It is not configured through a Workspace Toolkit row. Every eligible root Run
receives these management tools:

- `add_scheduled_task`
- `list_scheduled_tasks`
- `delete_scheduled_task`

`submit_scheduled_task_result` is exposed only when the current Run is bound to a
valid started Scheduled Task cycle. It accepts `finished` or `failed` and a
non-empty result. A Scheduled-bound `channel_action` may report progress only with
`continue`; terminal completion must use `submit_scheduled_task_result`.

The release-bundled `scheduled-task` Skill is projected from the immutable
`azents://` managed Skill VFS. It explains schedule interpretation, Session and
Binding selection, exact-ID management, autonomous continuation, and explicit
terminal result submission. Its creation contract states the mutually exclusive
field shapes explicitly: one-time work supplies aware `at` with `cron` and
`timezone` null, while recurring work supplies `cron` plus IANA `timezone` with
`at` null. The creation tool normalizes empty strings in `at`, `cron`, and
`timezone` to null before enforcing those canonical shapes. When requester
timezone context is reliably known, the Skill preserves the target instant's
local UTC offset in one-time `at` values, including duration-relative requests,
instead of normalizing equivalent input to `Z`.

Chat activity groups all four Scheduled tools under the Schedule category. Their
tool-call rows use dedicated summaries and bounded details for title, schedule,
Session-only versus channel-bound target, next run, objective, provider
registration, and terminal outcome instead of raw generic argument/result dumps.
Prompt text remains outside the collapsed summary.

## Due Dispatch and Start Admission

The existing Scheduler registry includes one code-owned dispatcher definition for
user Scheduled Tasks. Each pass:

1. claims at most a bounded batch of due Task rows with an expiring lease;
2. revalidates current Session, Agent, and optional Binding authority;
3. creates an immutable admitted cycle snapshot;
4. inserts one typed `scheduled_task_trigger` wake-producing Mailbox item;
5. advances or fences the Task schedule state in the same transaction; and
6. publishes the ordinary payload-free Session wake after commit.

An already-active recurring Task coalesces later due work into at most one
`pending_scheduled_for`. Invalid or removed authority deletes or skips future
scheduling work rather than choosing another target.

Mailbox promotion is the exact start boundary. Promotion changes the cycle from
`admitted` to `started`, binds the new AgentRun to that cycle, and appends a typed
`scheduled_task_trigger` Event. Deleting a Task or removing its owner before this
boundary removes the trigger and admitted cycle. After this boundary, Task
deletion does not interrupt the already-started AgentRun or its canonical Session
result.

## Continuation and Compaction

A successful Run that leaves a started cycle without a terminal result reaches the
normal Session idle-hook boundary. `ScheduledToolkit` returns one typed
`scheduled_task_continuation` input per current started cycle in deterministic
order. The worker atomically consumes the pending idle-continuation pointer,
enqueues the continuation Mailbox items, and keeps the Session running.

The continuation promotes to a dedicated Event and begins a fresh AgentRun still
bound to the same cycle. The Session and cycle identity remain stable across any
number of Runs.

Before continuity history is appended, the compaction summary hook replaces the
bounded Scheduled Task section with sanitized snapshots of every current started
cycle. Admitted and terminalized cycles are omitted. The hook reads existing
Toolkit State only and introduces no additional persistence authority.

## Terminal Result

`submit_scheduled_task_result` performs one idempotent canonical transaction:

1. lock and validate the current running AgentRun and started cycle;
2. append one `scheduled_task_result` Event using a cycle-derived external ID;
3. delete the cycle Toolkit State;
4. delete a completed one-time Task or release/advance a recurring Task;
5. store the terminal result identity and message on the AgentRun; and
6. commit before any provider effect.

The tool result terminalizes the current AgentRun without another model turn. The
Session history API retains the typed Scheduled Task Event payload. Web chat
projects trigger and continuation controls as dedicated collapsible Scheduled Task
messages: the collapsed row shows the Task title, while expanded content shows a
locale-aware human schedule and occurrence, canonical cron/UTC detail, and the
exact prompt. Legacy content that predates the structured runtime text remains
visible as a complete fallback.

`submit_scheduled_task_result` requires an explicit nullable `files` field. A
channel-bound cycle accepts the same absolute Runtime paths and authorized
`exchange://` URIs as `channel_action`, validates them against the cycle's exact
Binding before terminalization, and publishes the terminal message and files
through that same bound conversation. A Session-only cycle requires `files=null`.
The process-local file manifests are not added to the canonical terminal Event.

If a terminal call is recovered after the canonical Event already exists, the same
Event is returned and no provider effect or new file validation is replayed.

## External Channel Presentation

A Task may target one exact connected Slack or Discord Binding.

- Creation commits the Task before attempting one provider-native registration
  message. Slack retains native Edit and confirmed Cancel controls. Discord uses
  an Edit link to the exact Session Web tab and Task editor plus a Cancel button
  that first returns an ephemeral confirmation; only the signed confirmation
  control executes the mutation.
- Explicit Toolkit, Public API/Web, and provider-native control deletion commits
  before attempting one provider-native deletion notification in the exact bound
  conversation.
  Session-only deletion has no provider effect, and notification failure never
  rolls back the canonical deletion. Automatic one-time Task cleanup after
  terminal completion does not publish a deletion notice.
- Discord registration and deletion notifications omit duplicate standalone
  Scheduled Task status/title content before the embed. Multi-App Agent identity
  presentation remains available.
- A started cycle owns its own progress Tracker state. It reuses lower-level
  External Channel provider primitives but never reuses Channel Work state.
- Progress messages and Tracker updates are immediate one-attempt effects.
- Terminal result publication occurs only after the canonical Session result
  commits.
- Slack exact-thread terminal parts use reply broadcast for parent surfacing.
  Discord thread terminal parts are also forwarded to the parent channel in
  order.

Provider failure, ambiguity, process loss, or revoked Binding authority never rolls
back the canonical Session result and does not create an outbox, replay worker, or
fallback destination.

Provider mutation callbacks carry a bounded signed locator containing the exact
Task and Binding IDs. The callback revalidates current principal, interaction,
Task, Session, and Binding authority before mutation. Discord performs this
authorization both before showing its confirmation and before the confirmed
cancellation.

## Lifecycle

Explicit deletion permanently removes the Task and any pre-start trigger/admitted
cycle. A started cycle and its active Run remain independent and may still
terminalize in the Session.

Session archive removes all Task definitions and pre-start Scheduled work in the
archived tree. Archive is allowed with active Runs only when every such Run is a
preservable started Scheduled cycle; unrelated active work still blocks archive.
Archived Sessions accept only the internal continuation required to finish those
preserved cycles. Restore does not recreate deleted Tasks.

Binding disconnect, route removal, connection removal, and App uninstall remove
future Tasks and pre-start work for the affected Binding. A started cycle may
continue in the Session, but the disconnected Binding no longer authorizes
provider progress or terminal effects.

Permanent Session purge waits until preserved started cycles have finished, removes
residual Task, trigger, and cycle state, and verifies absence before root-tree
finalization. Agent and owner lifecycle cleanup use the same participant boundary.

## Event and Presentation Contracts

The closed Mailbox/Event unions include:

- `scheduled_task_trigger`
- `scheduled_task_continuation`
- `scheduled_task_result`

Trigger and continuation controls use dedicated payloads and model-input lowering.
Pending live projections identify them as internal Scheduled Task work rather than
editable user messages. Trigger and continuation content carries human-first
schedule labels, canonical secondary details, execution guidance, and the exact
prompt. The result payload contains only title, scheduled instant, terminal status,
and result text.

## Changelog

- **2026-08-21** (spec_version 8) — Made Scheduled Task creation normalize empty
  `at`, `cron`, and `timezone` strings to omitted values before canonical schedule
  validation.

- **2026-08-20** (spec_version 7) — Extended exact-Binding deletion notices to
  provider-native cancellation controls and required the Scheduled Task Skill to
  preserve a reliably known requester timezone offset in one-time `at` input,
  including duration-relative schedules.

- **2026-08-20** (spec_version 6) — Removed duplicate standalone Scheduled Task
  status/title content from Discord registration and deletion notifications while
  preserving Multi-App Agent identity presentation.

- **2026-08-20** (spec_version 5) — Added best-effort exact-Binding deletion
  notifications after explicit Toolkit and Public API/Web deletion commits.

- **2026-08-17** (spec_version 4) — Moved Web management into each concrete
  Session tab, fixed creation and editing to that Session, renamed destructive UI
  behavior to cancellation, and replaced Discord native editing with an exact Web
  edit link plus ephemeral confirmed cancellation.

- **2026-08-17** (spec_version 3) — Added terminal result file publication through
  the exact Scheduled cycle Binding, explicit Session-only file rejection, Runtime
  file-context injection, and same-conversation execution guidance.

- **2026-08-17** (spec_version 2) — Added collapsible title-first Web trigger and
  continuation presentation, human-first schedule labels, Schedule activity
  grouping, enriched Scheduled tool rows, and explicit Skill schedule-shape
  exclusivity.

## Verification

Required E2E uses the generated Python client and user-facing APIs. A
credential-free testenv-only Scheduler endpoint accepts one aware instant and runs
one bounded dispatcher pass. It is mounted only under explicit testenv enablement
and avoids wall-clock waits, direct product database mutation, and another E2E
service process. Two focused journeys verify:

- creation of one Session-only one-time Task followed by generated-client list,
  get, and delete readback; and
- a one-time Task due at the exact controlled dispatcher instant, including
  admission through the ordinary Worker path, durable typed result history, and
  automatic completed-Task deletion.

Backend contract tests own the combinatorial matrix: schedule and DST calculation,
canonical validation, constraints, leases, recurring cursors and coalescing,
authority revalidation, FIFO start admission, pre-start and post-start deletion
races, continuation, terminal idempotency, provider presentation and failure,
Slack and Discord exact-thread behavior, Binding controls, lifecycle cleanup,
compaction enrichment, closed event unions, and Public API semantics. Compaction
coverage includes repeated replacement of stale Scheduled sections, multiple
started cycles, unrelated current Runs, deterministic tie ordering, sanitization,
and omission of non-started or terminalized cycles from the current snapshot.

Frontend contract checks cover dedicated Session creation and selection, CRUD,
current-cycle progress, canonical Session navigation, responsive rendering, and
absence of history, pause, resume, rerun, or cancel-current-cycle controls without
adding a Scheduled Task browser E2E matrix.

## Removed Legacy

The current domain has no owner-user execution field, enabled/status flag,
provider-coordinate target, per-occurrence Session, Redis scheduling leader,
retry counter, legacy `schedule_create`/`schedule_list`/`schedule_delete` aliases,
compatibility mode, rollout flag, second scheduler, durable provider replay, or
Channel Work ownership.
