---
title: "Batched External Channel Ingress Phase 1 Runtime Plan"
created: 2026-08-10
tags: [runtime, scheduler, external-channel, infra]
---

# Phase Execution Plan

- Phase: `1/4 — Common Job Runtime and lifecycle`
- Branch/base: `feature/channel-batched-ingress-1-runtime` → `origin/main`
- PR boundary: Add the common process-local Job Runtime, AppContext shutdown ordering,
  global backend selection, Scheduler adapter, and shared non-reload devserver context.
- Inputs: Confirmed `channel-260810/REQ`, accepted `channel-260810/ADR-D1` and
  `channel-260810/ADR-D2`, approved `channel-260810/DESIGN` revision `1`.
- Deliverables: A bounded Local Runtime with typed handler dispatch and execution-key
  coalescing; AppContext pre-close drain; Scheduler execution through the Runtime;
  unavailable Temporal startup failure; shared process context packaging; focused tests.
- Non-goals: External Channel queue tables/admission/drain, mailbox schema or
  `prompt_role` migration, provider-policy changes, testenv ingress APIs, E2E product
  journeys, Living Spec promotion.
- Interfaces: Closed handler registry; JSON-safe request payload; stable execution key;
  absolute deadline; typed structured outcome; task-local `di.Container.copy()`;
  `get_job_runtime()` stored through `AppContext.get_variable()`; one global backend
  selector with `local` and reserved `temporal` values. Scheduler payloads contain only
  task key, claim timestamp, lease owner, and manual-trigger state. Scheduler execution
  keys identify one claim using task key, lease owner, and claim timestamp. Registered
  handlers propagate `asyncio.CancelledError`; Local cancellation grace is shorter than
  the existing 30-second Scheduler lease margin. Externally owned FastAPI lifespans
  initialize app-specific services but never enter or close the shared AppContext or
  root DI container.
- Approved Design mechanisms: `M2`, `M3`, `M9`
- Authority references: `channel-260810/ADR-D1`, `channel-260810/ADR-D2`,
  `channel-260810/REQ-2`, `REQ-3`, `REQ-6`, `REQ-8`, and the unchanged Periodic
  Execution Living Spec for Scheduler state/lease ownership.
- Design delta: `None`
- Removal obligations: Scheduler-only `TaskExecutor` and `LocalTaskExecutor` execution
  boundary; independent AppContext creation by co-located non-reload devserver FastAPI
  apps and Worker/Scheduler container.
- Absence verification: Static search finds neither executor class nor a direct
  Scheduler call to a registered task handler; `scheduler/executor.py` contains only the
  common Runtime handler adapter. Lifecycle tests prove one AppContext/Runtime identity
  for co-located roles.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime contracts and Local backend | `/root` | `python/apps/azents/src/azents/job_runtime/**` and focused tests | approved `M2`, `M3`, `M9` | handler registry, requests, handles, outcomes, concurrency, deadlines, task registry | targeted pytest, Ruff, ty |
| AppContext and DI lifecycle | `/root` | `azents/utils/appctx.py`, `azents/app.py`, app/devserver tests | Runtime teardown contract | pre-close callbacks, shared externally owned app context, task-local container factory | lifecycle and singleton tests |
| Scheduler adapter | `/root` | `azents/scheduler/**` | Runtime contracts | JSON-safe per-claim request, registered Scheduler handler, awaited outcome, unchanged DB state and retry behavior | payload, coalescing, timeout/lease-margin, and service tests |
| Config and packaging | `/root` | `azents/core/config.py`, CLI entrypoints, `infra/charts/azents/**`, relevant ArgoCD manifests/tests | backend enum and runtime dependency | one rendered selector, Local default, Temporal startup rejection | config tests, Helm render tests |
| Independent review | `/root/channel-ingress-reviewer` | read-only phase diff | stable implementation and focused evidence | authority/security/lifecycle/scope report | written review findings |

- Integration order: Runtime types/registry → Local backend tests → AppContext pre-close
  and DI factory → Scheduler adapter → config/startup selection → devserver/Helm
  packaging → focused validation → independent review → corrections → final validation.
- Independent review: `/root/channel-ingress-reviewer` reviews read-only against
  Requirements, ADR-D1/D2, Design `M2`/`M3`/`M9`, Periodic Execution Spec, this plan,
  and the stable diff. It reports only material authority, security/data-loss,
  lifecycle, configuration, interface, and scope-drift findings.
- Final validation: `uv run ruff check` and `uv run ruff format --check` for affected
  Python paths; `uv run ty check --error-on-warning`; targeted AppContext, Job Runtime,
  Scheduler payload/per-claim/cancellation, config, app/devserver ownership tests;
  affected Helm render tests; docs snapshot validation; `git diff --check`.
- Scope-drift check: Confirm all `M2`/`M3`/`M9` behavior is present; no durable generic
  queue, Temporal implementation, ingress behavior, mailbox contract, compatibility
  fallback, new Deployment, or per-handler backend routing is added.
- Context checkpoint: Phase starts from `c444feaea` with the approved snapshot documents
  uncommitted. Provisional Discord callback/SDK changes are preserved in stash
  `wip/channel-ingress-provisional-discord-before-phase1` and are outside this phase.
  Phase 2 begins only after this PR is open and records the stable Runtime interfaces and
  validation evidence.
