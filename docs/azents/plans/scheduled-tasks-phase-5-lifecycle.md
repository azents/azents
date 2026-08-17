---
title: "Scheduled Tasks Phase 5 Lifecycle Integration Plan"
created: 2026-08-16
tags: [scheduled-task, session, external-channel, lifecycle, purge]
---

# Phase Execution Plan

- Phase: `5/8 — Session and Binding lifecycle integration`
- Branch/base: `feature/scheduled-tasks-5-lifecycle` →
  `feature/scheduled-tasks-4-channel`
- PR boundary: Integrate Scheduled Task authority, pre-start work, started-cycle
  preservation, continuation admission, provider Tracker cleanup, and permanent
  purge into the existing Session and External Channel lifecycle systems without
  adding Public API, Web UI, E2E journeys, durable cleanup delivery, replay,
  fallback publication, or interruption behavior.
- Inputs: Phase 4 exact Binding registration/progress/terminal effects and
  Scheduled-owned Tracker projection; Phase 3 immutable admitted/started cycle
  state, run binding, idle continuation, and terminal transaction; current Session
  lifecycle registry/orchestrator, caller-owned archive transaction, archived
  retention purge phases, Agent decommission flow, and External Channel Binding,
  route, connection, participation, and App-uninstall terminalization paths;
  confirmed `scheduled-260816/REQ`, accepted `scheduled-260816/ADR-D3` through
  `ADR-D5`, and approved `scheduled-260816/DESIGN` revision `3`.
- Deliverables: Required `session.scheduled-task` participant ordered after
  `session.execution` and before `session.external-channel`; Session-tree archive
  cleanup of Task rows, pending occurrences, admitted cycle Toolkit State, trigger
  Mailbox input, and current Scheduled Tracker projections; preservation of
  started cycles, active AgentRuns, and their typed continuation authority;
  Scheduled-aware running archive eligibility; archived Session admission only for
  a continuation whose immutable started cycle proves pre-archive authority;
  Binding-targeted cleanup in every permanent terminalization path; transactional
  capture and post-commit one-attempt Tracker deletion; purge preparation that
  waits for preserved started cycles, restrictive cleanup, absence verification,
  and finalization recheck; restore validation that never recreates removed state;
  focused no-interruption, no-fallback, and transient-health-preservation tests.
- Non-goals: Public Scheduled Task API, OpenAPI or generated clients, Web routes or
  UI, testenv/E2E journeys, live provider credentials, new lifecycle framework,
  new Session status, Task restoration, cycle replay, provider cleanup outbox or
  retry worker, provider fallback, started Run interruption, terminal-result
  suppression, transient provider-health cleanup, Living Spec promotion,
  implementation dates, or plan cleanup.
- Interfaces: `ScheduledTaskLifecycleService` is a transaction-bound collaborator
  over the existing Task, Mailbox, cycle Toolkit State, AgentRun, and provider
  effect repositories; archive and Binding termination return immutable
  post-commit Tracker cleanup plans captured before Task/cycle/Binding authority is
  removed; started cycle identity is proven by `agent_runs.scheduled_task_cycle_id`
  plus `scheduled/cycle:{cycle_id}` phase `started`; lifecycle cleanup follows the
  existing Session-tree → Binding/Task/cycle ordering and the canonical Scheduled
  Mailbox → cycle → Task mutation ordering without locking Task first; archived
  admission accepts only `SCHEDULED_TASK_CONTINUATION` with a matching started
  cycle and rejects triggers and every unrelated input; purge participant methods
  use the existing prepare/cleanup/verify/finalize orchestration and never finalize
  while a started cycle or active Run survives.
- Approved Design mechanisms: `M4`, `M7`, `M12`
- Authority references: `scheduled-260816/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`,
  `REQ-9`, `REQ-10`, `REQ-14`, `REQ-15`, `REQ-17`;
  `scheduled-260816/ADR-D3`, D4, D5; approved Design revision `3`; current Session
  Lifecycle and External Channel Lifecycle Specs and their restrictive ownership,
  caller-owned transaction, post-commit effect, and purge-finalization contracts.
- Design delta: `None`
- Removal obligations: Remove Session- or Binding-owned Task scheduling authority,
  due leases, pending occurrences, admitted cycles, trigger Mailbox rows, and
  current Tracker projections at the approved lifecycle boundary. Preserve started
  cycles and Runs until normal terminalization. Do not add restoration, migration
  to another Binding, Session-only provider substitution, replay, outbox,
  interruption, duplicate lifecycle ownership, or transient-health cleanup.
- Absence verification: Registry tests prove Scheduled ordering before External
  Channel; archive/Binding tests prove no matching Task, admitted cycle, trigger,
  due lease, pending occurrence, or Tracker state survives while started state and
  Run remain; archived-admission tests prove only the exact typed continuation is
  accepted; purge prepare/verify/finalize tests prove no active started cycle and no
  Scheduled Task or `scheduled/cycle:*` row remains; static call-path tests/searches
  prove manual Binding disconnect, participation removal, route removal,
  connection disconnect, App uninstall, Session archive, and Agent decommission
  all invoke the collaborator while transient health updates do not; source/schema
  audit proves no cleanup ledger, retry worker, fallback Binding, or restore path.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan, lifecycle composition, and integration | `/root` | this phase plan; `services/session_lifecycle/registry.py`; shared DI/composition and final cross-boundary tests | every implementation workstream | deterministic participant ordering and one integrated transaction/effect boundary | registry ordering, dependency snapshot, diff/absence audit |
| Scheduled lifecycle repository and service | `/root` | new `services/scheduled_task/lifecycle.py` and focused tests; scoped additions to `repos/scheduled_task/repository.py`, `repos/scheduled_task_cycle/**`, and Mailbox/AgentRun repository helpers when required | Phase 2 canonical mutation lock order and Phase 4 Tracker snapshot | archive/Binding cleanup summaries and immutable post-commit Tracker deletion plans; restore and purge checks | admitted/started, Session tree, Binding target, Tracker, restore, purge unit/integration tests |
| Session archive and archived admission | `/root` | `services/chat/__init__.py`; `services/mailbox.py`; `worker/session/idle_continuation.py`; focused chat/mailbox/worker tests | Scheduled lifecycle collaborator and started-cycle proof | Scheduled-only running archive exception and exact archived continuation admission without reopening ordinary execution | mixed-run subtree, invalid binding, trigger rejection, unrelated continuation, terminal append tests |
| External Channel terminalization integration | `/root` | `repos/external_channel/work.py`, `repos/external_channel/lifecycle.py`, `repos/external_channel/management.py`; `services/external_channel/lifecycle.py`, `services/external_channel/management.py`; focused lifecycle/management tests | transaction-bound Scheduled cleanup and captured effect plans | collaborator invocation for Binding, participation, route, connection, uninstall, archive, and decommission paths; post-commit cleanup consumption | every terminal path, idempotency, provider authority loss, no fallback, transient health preservation |
| Archived purge integration | `/root` | `services/archived_session_purge.py` and focused tests | registered participant and Scheduled purge contracts | prepare wait, cleanup, verify, and finalization recheck before root deletion | active-cycle retry, empty-state verification, participant snapshot/version behavior |
| Independent review | `/root/scheduled-stack-reviewer` | read-only complete Phase 5 diff | stable integrated diff and focused evidence | authority, data-loss, lock-order, lifecycle, non-interruption, provider-effect, purge, removal, and scope-drift verdict | written blocker/no-blocker report with exact path evidence |

- Integration order: Add scoped Scheduled lifecycle queries and immutable cleanup
  contracts → register `session.scheduled-task` after execution and retarget External
  Channel dependency → integrate archive participant and Scheduled-aware active-run
  guard → admit only matching archived Scheduled continuations → invoke the same
  Binding collaborator from the common terminalization boundary → aggregate and
  execute Tracker cleanup plans after each caller commit → add purge
  prepare/cleanup/verify/finalize behavior → add restore non-recreation checks → run
  every terminal-path and lock-order test → absence/scope audit → independent review
  → corrections → final validation.
- Independent review: `/root/scheduled-stack-reviewer` reviews read-only against
  confirmed Requirements, accepted ADR-D3/D4/D5, approved Design M4/M7/M12,
  current Session and External Channel lifecycle Specs, this plan, the Phase 2
  lock-order contract, Phase 3 started-cycle/continuation/terminal contracts, Phase
  4 provider-effect contracts, focused evidence, and the stable diff. Review
  priority is pre-start versus started boundary correctness, mixed subtree archive
  rejection, exact archived continuation authority, no Run stop/interruption,
  transaction and lock ordering, complete permanent Binding terminalization
  coverage, provider target capture before authority loss, post-commit one-attempt
  cleanup, purge blocking and absence verification, no restore/replay/fallback, and
  exclusion of Phase 6+ surfaces.
- Final validation: Focused Scheduled service/cycle/terminal/channel lifecycle
  tests; Session lifecycle registry and orchestrator tests; Chat archive, Mailbox,
  idle continuation, External Channel lifecycle/management/repository, archived
  purge, and Agent decommission tests; affected backend suite; `uv run ruff check
  .`; `uv run ruff format --check .`; `uv run ty check --error-on-warning`; full
  `uv run pytest`; docs validation; full pre-commit; `git diff --check`.
- Scope-drift check: Confirm complete M4/M7/M12 coverage and no missing Task,
  admitted-cycle, trigger, pending, Tracker, archive admission, Binding path, or
  purge obligation. Confirm the diff adds no new product state, Session status,
  public route, OpenAPI/client, Web/E2E surface, provider ledger/outbox/retry,
  restore behavior, Task reassignment, fallback target, interruption, transient
  health cleanup, or later-phase documentation promotion.
- Context checkpoint: Phase starts from Phase 4 commit `70e6f2715`, which provides
  exact Binding registration, controls, Scheduled-owned Tracker progress, terminal
  publication, parent surfacing, and one-attempt terminal Tracker cleanup. Phase 4
  focused validation passed (`32` Scheduled work tests and an earlier `119`
  External Channel/action/adapter suite), with Ruff, formatting, ty, and diff checks
  passing on affected subsets. Phase 5 owns lifecycle integration only; Phase 6
  receives a stable backend Task service and lifecycle boundary for Public API use.
