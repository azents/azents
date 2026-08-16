---
title: "Scheduled Tasks Phase 4 Channel Presentation Plan"
created: 2026-08-16
tags: [scheduled-task, external-channel, slack, discord, tracker]
---

# Phase Execution Plan

- Phase: `4/8 — External Channel presentation and progress`
- Branch/base: `feature/scheduled-tasks-4-channel` →
  `feature/scheduled-tasks-3-toolkit`
- PR boundary: Add one-attempt External Channel registration, Scheduled-owned
  progress projection, and terminal publication after the Phase 3 canonical
  Session result boundary, without adding lifecycle cleanup, Public API, Web UI,
  E2E journeys, durable delivery, or replay.
- Inputs: Phase 3 root-only ScheduledToolkit, immutable started-cycle snapshots,
  run-bound terminal transaction and crash fence, exact opaque Binding storage,
  current External Channel access, provider effect, interaction admission,
  delivery, splitting, file transfer, Slack Block Kit, Discord Embed, and Channel
  Work Tracker primitives; confirmed `scheduled-260816/REQ`, accepted
  `scheduled-260816/ADR-D5` through `ADR-D7`, and approved
  `scheduled-260816/DESIGN` revision `3`.
- Deliverables: Post-create Slack/Discord registration presentation with Edit and
  Delete controls; idempotently claimed provider interactions that reload the
  exact Task and revalidate principal, Binding, Session, Agent, connection, and
  mutation authority; Scheduled-owned Tracker desired/projection state; cycle-
  aware `channel_action continue` with exact Binding and Scheduled-state updates;
  rejection of `finish` and `ignore`; terminal result publication after canonical
  commit; Slack exact-thread `reply_broadcast=true`; Discord exact-thread native
  forwarding; ordered immediate outcomes; unconditional one-attempt Tracker
  cleanup; provider failure and no-replay tests.
- Non-goals: Session archive or purge integration, Binding/route/connection/App
  termination cleanup, Agent decommission cleanup, archived-Session admission,
  Public API routes, OpenAPI or generated clients, Web UI, testenv/E2E journeys,
  live provider credentials, Living Spec promotion, implementation dates, or plan
  cleanup.
- Interfaces: Task and cycle state remain canonical before provider I/O;
  `ScheduledTaskTerminalOutcome` captures a process-local effect bundle from the
  locked cycle snapshot before cycle deletion and returns no effect retry plan for
  recovered `created=False` outcomes; Scheduled Tracker state remains in the
  `scheduled` cycle namespace and never reuses Channel Work identity or CAS;
  `channel_action` resolves Scheduled context from the current AgentRun cycle
  binding and permits only `continue` on the exact cycle Binding; provider effects
  reload and revalidate current opaque Binding authority; provider outcomes are
  immediate and non-durable; terminal provider parts execute only after the
  canonical Session Event transaction commits.
- Approved Design mechanisms: `M6`, `M8`, `M12`
- Authority references: `scheduled-260816/REQ-5`, `REQ-8`, `REQ-9`, `REQ-10`,
  `REQ-11`, `REQ-12`, `REQ-14`, `REQ-16`; `scheduled-260816/ADR-D5`, D6, D7;
  approved Design revision `3`; current External Channel authorization,
  interaction admission, provider effect, splitting, file-transfer, and SDK
  boundaries.
- Design delta: `None`
- Removal obligations: Do not add a Task or Tracker terminal history, provider
  delivery ledger, outbox, replay worker, compensation, fallback Binding,
  provider-coordinate duplication, Channel Work state reuse, Task revision token,
  legacy Scheduled tool alias, or provider-native identifier reconstruction.
- Absence verification: Static searches and schema tests find no new provider
  ledger/outbox/replay/config or fallback destination; state and coexistence tests
  prove Scheduled and Channel Work identities/revisions remain independent;
  interaction payload tests prove bounded action identity, Task ID, and Binding
  context only; recovery tests prove `created=False` performs no provider or
  Tracker effect; diff audit confirms no lifecycle, API, Web, generated-client, or
  E2E path is added.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and integration | `/root` | this phase plan; shared composition under `engine/tools/deps.py`, `worker/deps.py`, `worker/run/executor.py`; final cross-boundary tests | every implementation workstream | one ordered provider-effect integration with no later-phase surface | diff audit, composition tests, full affected suite |
| Cycle projection and terminal effect snapshot | `/root/phase4-cycle-effects` | `repos/scheduled_task_cycle/data.py`, `repos/scheduled_task_cycle/__init__.py`, repository tests; `services/scheduled_task/terminal.py` and tests | Phase 3 cycle/terminal contract | Scheduled desired revision and per-part projection status/message identity; pre-delete terminal effect bundle; recovered no-effect outcome | CAS/version, coexistence, deletion-after-start, canonical-order, duplicate recovery tests |
| Scheduled provider effects and registration | `/root` | new provider-neutral modules under `services/scheduled_task/**`; targeted reuse in `services/external_channel/provider_effect.py`, access/presentation helpers, and focused tests | exact Binding revalidation and cycle projection contract | registration plan/outcome, bounded Slack/Discord controls, immediate provider execution with no rollback/replay | parent/thread, stale Task, disconnected/wrong Session, unauthorized, ambiguity, failure/no-replay tests |
| Cycle-aware progress routing | `/root` | `engine/tools/external_channel.py` and tests; `services/external_channel/channel_action.py` or a Scheduled collaborator; Scheduled cycle repository/service tests | current Run cycle binding and exact Binding authority | `continue` publishes interim text/files and replaces Scheduled progress; `finish`/`ignore` rejection; Scheduled-only CAS settlement | exact Binding, mode rejection, files, desired revision, Work coexistence tests |
| Provider interaction controls | `/root` | `services/external_channel/interaction.py`, `slack_http.py`, `slack_events.py`, Discord HTTP/control modules and focused tests | registration presentation and shared Task mutation service | idempotent claim, exact Task reload, actor/Binding authority revalidation, Edit/Delete acknowledgement | duplicate/stale/deleted/disconnected/unauthorized/modal/component tests |
| Terminal effect orchestration | `/root` | `engine/tools/scheduled.py`; new Scheduled provider-effect service and focused tests | new canonical terminal commit, captured effect bundle, and provider adapter primitives | ordered post-commit terminal execution, unconditional Tracker delete, sanitized immediate outcomes | ordering, multipart, per-part failure/unknown, Tracker cleanup, crash/no-replay tests |
| Slack and Discord adapter primitives | `/root/phase4-provider-adapters` | `services/external_channel/slack_events.py`, Slack SDK boundary and tests; `discord_sdk.py`, `discord_delivery.py` and tests | current provider delivery contracts | opt-in Slack thread broadcast and typed Discord native create-then-forward operation | default compatibility, nonce/deadline/error classification, ordering and focused SDK/delivery tests |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 4 diff | stable integrated diff and focused evidence | authority, authorization, effect ordering, privacy, replay, provider SDK, removal, and scope-drift verdict | written blocker/no-blocker report with exact evidence |

- Integration order: Extend Scheduled cycle projection and terminal effect snapshot
  contracts → implement exact Binding reload/revalidation and provider-neutral
  registration/effect execution → add Scheduled Tracker creation and CAS settlement
  → route `channel_action continue` to Scheduled state and reject terminal modes →
  add idempotently claimed Slack/Discord controls → add post-commit terminal part
  publication → add Slack broadcast and Discord native forward → attempt Tracker
  deletion regardless of publication outcome → run coexistence/failure/no-replay
  tests → scope and absence audit → independent review → corrections → final
  validation.
- Independent review: `/root/scheduled-stack-reviewer` reviews read-only against
  confirmed Requirements, accepted ADR-D5/D6/D7, approved Design M6/M8/M12,
  current External Channel Specs, this plan, Phase 3 canonical result contracts,
  focused evidence, and the stable diff. Review priority is exact Binding and
  principal authority, provider interaction idempotency, Scheduled-versus-Work
  state separation, transaction/effect ordering, no replay or fallback, provider
  payload privacy, Slack/Discord exact-thread behavior, Tracker cleanup despite
  publication failure, and exclusion of Phase 5+ work.
- Final validation: Focused Scheduled cycle/terminal/provider-effect/Toolkit tests;
  External Channel action/access/interaction/presentation/Slack/Discord SDK and
  delivery tests; changed-file integration suite; `uv run ruff check .`; `uv run
  ruff format --check .`; `uv run ty check --error-on-warning`; full `uv run
  pytest`; canonical OpenAPI stability; docs validation; full pre-commit; `git diff
  --check`.
- Scope-drift check: Confirm complete M6/M8/M12 coverage and no missing
  registration, exact Binding, Scheduled Tracker, continue-only progress,
  canonical-before-provider, ordered terminal parts, Slack broadcast, Discord
  forward, cleanup, or no-replay boundary. Confirm the diff adds no Session or
  Binding lifecycle participant, archived-Session exception, API route, generated
  client, Web feature, E2E fixture, provider ledger/outbox/replay, fallback target,
  second Session, Channel Work reuse, or Task-owned terminal history.
- Context checkpoint: Phase starts from Phase 3 commit `bd7127a5d`, whose full
  backend suite (`4,428 passed`), affected suite (`269 passed`), full Ruff,
  formatter, ty, pre-commit, independent review, and PR `#1294` are complete.
  Phase 3 provides the canonical terminal Event and no-extra-turn boundary but
  intentionally has no provider effects. Phase 5 receives stable provider
  presentation/projection contracts and remains solely responsible for lifecycle
  cleanup and started-cycle preservation across archive or Binding termination.
