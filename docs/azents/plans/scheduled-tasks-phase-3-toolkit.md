---
title: "Scheduled Tasks Phase 3 Toolkit Execution Plan"
created: 2026-08-16
tags: [scheduled-task, toolkit, engine, compaction, continuation, vfs]
---

# Phase Execution Plan

- Phase: `3/8 — ScheduledToolkit execution`
- Branch/base: `feature/scheduled-tasks-3-toolkit` →
  `feature/scheduled-tasks-2-dispatch`
- PR boundary: Complete the Session-only Scheduled Task product path from Agent
  management through autonomous continuation and canonical terminal result, without
  provider presentation, lifecycle cleanup, Public API, Web UI, or E2E work.
- Inputs: Phase 2 Task service, due admission, schema-version-1 cycle Toolkit State,
  typed trigger/continuation/result protocol variants, immutable AgentRun cycle
  binding, confirmed `scheduled-260816/REQ`, accepted
  `scheduled-260816/ADR-D1` through `ADR-D7`, and approved
  `scheduled-260816/DESIGN` revision `3`.
- Deliverables: Root-only unprefixed auto-bound ScheduledToolkit; Agent management
  tools; required managed Scheduled Skill VFS release; active-cycle-only dynamic
  guidance; deterministic typed idle continuation; sanitized ordered compaction
  summary enrichment; run-bound terminal result tool; idempotent canonical result
  Event and Task/cycle transaction; one-time deletion, recurring advancement, and
  engine-recognized no-extra-turn completion; focused Session-only integration,
  recovery, and terminal tests.
- Non-goals: Slack or Discord registration, Tracker creation or progress projection,
  channel terminal publication or parent surfacing, provider credentials or replay,
  Session or Binding lifecycle participants, archived-Session continuation changes,
  Public API routes, generated clients, Web management UI, testenv/E2E journeys,
  Living Spec promotion, `implemented` dates, or plan cleanup.
- Interfaces: `ScheduledToolkitProvider` is root-only, unprefixed, auto-bound,
  independent of ToolkitConfig and credentials, and session-lifecycle stable;
  management tools derive Workspace, Agent, and Session from runtime context;
  `submit_scheduled_task_result` is exposed only for the AgentRun's current valid
  started cycle and accepts no identity; typed Scheduled continuation preserves the
  existing cycle binding; the existing ordered compaction hook evolves the canonical
  summary from a non-locking snapshot of current `started` cycles; the canonical
  result Event and cycle/Task transition commit before Run completion; persisted
  AgentRun VFS projection remains immutable recovery authority.
- Approved Design mechanisms: `M3`, `M5`, `M9`, `M10`, `M13`, `M15`
- Authority references: `scheduled-260816/REQ-2`, `REQ-5`, `REQ-6`, `REQ-7`,
  `REQ-8`, `REQ-13`, `REQ-14`, `REQ-17`, `REQ-18`;
  `scheduled-260816/ADR-D2`, D3, D4, D5, D7; approved Design revision `3`;
  current Toolkit lifecycle, runtime hook, Event, VFS projection, and AgentRun
  recovery contracts.
- Design delta: `None`
- Removal obligations: Replace the historical `schedule_create`, `schedule_list`,
  and `schedule_delete` contract with exactly `add_scheduled_task`,
  `list_scheduled_tasks`, and `delete_scheduled_task`; do not add aliases, fuzzy
  lookup, upsert, ToolkitConfig attachment, a second compaction ledger, terminal
  Task history, provider fallback, or another execution Session.
- Absence verification: Tool catalog tests assert only the approved names; static
  source searches find no historical aliases or compatibility wrappers; terminal
  tests prove completed cycle Toolkit State is removed and no terminal result is
  stored in Task rows; compaction tests prove no Scheduled ledger or mutation is
  introduced; root/subagent and VFS tests prove no DB attachment or credential is
  required and no subagent source is projected.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and integration | `/root` | this phase plan; shared composition in `engine/run/resolve.py`, `engine/tools/deps.py`, `worker/deps.py`, `worker/run/executor.py`, and focused composition tests | all implementation workstreams | one ordered root-only binding, source revision, lifecycle-stable composition, and scope audit | resolve, worker composition, executor, diff, and import tests |
| Toolkit, management, guidance, and continuation | `/root` | new `engine/tools/scheduled.py` and tests; `services/scheduled_task/**`; `repos/scheduled_task/**`; `repos/scheduled_task_cycle/**`; `engine/hooks/types.py`; `worker/session/idle_continuation.py` and focused tests | Phase 2 service and cycle repository | exact management tools, active-cycle terminal tool, dynamic guidance, deterministic typed continuations, Task state projections | focused Toolkit, service, repository, hook, idle, deletion-race, and recovery pytest |
| Managed Skill VFS projection | `/root` | `resources/vfs/toolkits/scheduled/**`; `services/vfs.py` and tests; provider release declarations | ScheduledToolkit provider identity | required `azents://skills/scheduled/scheduled-task/SKILL.md` projection for eligible root previews and Runs with immutable content hash | package-resource, projection ordering, root/subagent eligibility, persisted Run projection tests |
| Compaction continuity | `/root` | Scheduled Toolkit hook/rendering; `repos/scheduled_task_cycle/**`; focused compaction and engine-adapter tests | started-cycle query and ordered hook pipeline | replacement of prior Scheduled snapshot with bounded sanitized entries ordered by `scheduled_for`, cycle ID | admitted/terminal exclusion, multi-cycle ordering, sanitization, unrelated-Run, repeated-compaction tests |
| Terminal result and no-extra-turn completion | `/root` | new terminal service under `services/scheduled_task/**`; `engine/events/**`; `engine/run/**`; `worker/run/**`; existing result Event projection contracts and focused tests | AgentRun cycle binding, client tool identity, closed result Event variant | deterministic Event crash fence, idempotent terminal transaction, cycle removal, one-time deletion, recurring advancement, recovered outcome, run completion without another model turn | transaction, crash-boundary, duplicate-call, deletion-after-start, recurring pending/future, execution-loop, live/history tests |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 3 diff | stable integrated diff and focused evidence | authority, atomicity, recovery, privacy, compaction, continuation, VFS, terminal engine, removal, and scope-drift verdict | written blocker/no-blocker report with exact evidence |

- Integration order: Extend cycle and Task repository terminal/query contracts → add
  terminal service and engine-recognized terminal tool outcome → implement
  ScheduledToolkit management and run-bound execution surface → extend typed idle
  continuation admission → add active-cycle dynamic guidance → add ordered sanitized
  compaction enrichment → add required Scheduled VFS source → compose the provider
  into root Run resolution and recovery → run cross-boundary Session-only tests →
  scope and absence audit → independent review → corrections → final validation.
- Independent review: `/root/scheduled-stack-reviewer` reviews read-only against
  confirmed Requirements, accepted ADR-D2/D3/D4/D5/D7, approved Design
  M3/M5/M9/M10/M13/M15, current Specs, this plan, Phase 2 contracts, focused
  evidence, and the stable diff. Review priority is root-only exposure, exact
  identity derivation, terminal transaction ordering and idempotency, no-extra-turn
  engine behavior, deletion races, recurring cursor release, continuation recovery,
  compaction ordering/sanitization/non-mutation, immutable VFS authority, historical
  alias absence, and later-phase exclusion.
- Final validation: Focused Scheduled Toolkit/service/repository/hook/VFS/idle/
  execution/worker tests; changed-file integration suite; `uv run ruff check .`;
  `uv run ruff format --check .`; `uv run ty check --error-on-warning`; full
  `uv run pytest`; canonical OpenAPI stability; docs validation; full pre-commit;
  `git diff --check`.
- Scope-drift check: Confirm complete M3/M5/M9/M10/M13/M15 coverage and no missing
  root, continuation, compaction, terminal, Event, VFS, or recovery boundary.
  Confirm the diff adds no provider presentation or effects, Tracker behavior,
  lifecycle participant, archived-Session exception, API route, generated client,
  Web feature, E2E fixture, compatibility tool, durable provider replay, second
  Session, second compaction authority, or Task-owned terminal history.
- Context checkpoint: Phase starts from Phase 2 tip `e19713356`, whose backend full
  suite (`4,405 passed`), changed-file integration suite (`372 passed`), Ruff,
  formatter, ty, full pre-commit, and independent review passed. Phase 2 PR `#1293`
  is open against Phase 1 with reviewer `hardtack`. The preserved Scheduled Skill
  VFS files are intentionally untracked at phase start and become owned by this
  phase. Phase 4 receives the canonical Session-only management, continuation,
  compaction, terminal, and Run-completion interfaces but remains solely responsible
  for provider presentation and progress.
