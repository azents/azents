---
title: "Optional Managed Runtime Phase 5 Removal Coordinator"
created: 2026-08-10
tags: [agent, runtime, removal, session, scheduler, backend]
---
# Phase Execution Plan

- Phase: `5 — Durable Runtime removal coordinator`
- Branch/base: `azents/runtime-optional-capability-5-removal` →
  `azents/runtime-optional-capability-4-runtime-transitions`
- PR boundary: Add the internal irreversible removal confirmation, privacy-safe
  impact inventory, PostgreSQL-leased coordinator, Agent-wide work interruption,
  bounded Runtime-owned product cleanup, exact physical-deletion wait, and final
  `removing → none` transition. Public routes and read models remain Phase 6.
- Inputs: Phase 4 commit `e7e147ff2`; confirmed `runtime-260803/REQ`; accepted
  `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`, and `ADR-D5`; approved
  `runtime-260803/DESIGN` revision 3; Phase 1 removal-operation persistence; Phase 2
  capability work fence; Phase 3 Session binding/resource admission; Phase 4 exact
  terminal acknowledgement and reconnect-safe deletion dispatch.
- Deliverables:
  - One internal final-confirmation transition locks the Agent, validates exact
    capability/Profile versions and privacy-safe aggregate impact, clears Profile
    selection, disables shell, commits capability `removing`, advances optimistic
    versions, and creates or replays the Agent's single durable removal operation.
  - A content-free inventory covers every Team and private User root tree and
    records only aggregate active root, subagent, Run, and queued Runtime-action
    counts. It never exposes Session identifiers, titles, owners, paths, or content.
  - A scheduler-owned PostgreSQL-leased coordinator advances fencing,
    interruption, product cleanup, physical deletion, and finalization idempotently;
    Redis/broker signals are best-effort wake-ups only.
  - Interruption records durable stop fences for every Agent Session tree,
    terminalizes queued Runtime-dependent work, and waits until active Runs and
    admitted Runtime operations are absent before cleanup.
  - Bounded cleanup invalidates every retained `pending` or `bound` root context
    with removal-operation evidence, terminalizes abandoned archive cleanup,
    removes Session Project/worktree metadata and path claims, clears Agent
    automatic/default/preset/catalog Project state, and removes Runtime-only Skill,
    instruction, action, and credential projections while preserving retained
    Agent, conversation, Memory, remote Toolkit, external-channel, attachment,
    ModelFile, Artifact, Goal, Todo, ownership, and pin state.
  - Physical deletion records either an exact Provider terminal-delete generation
    or a locked `no_physical_binding` acknowledgement, then waits for exact current
    acknowledgement without treating disconnection as absence.
  - Finalization re-locks Agent, operation, Runtime, and cleanup evidence; requires
    complete binding invalidation and physical authority; commits capability
    `none`, keeps Profile null and shell disabled, advances capability version, and
    completes the operation without deleting the Agent or retained Sessions.
- Non-goals: Public preview/confirm/progress routes, unified public Runtime read
  model, OpenAPI/generated clients, Web confirmation/progress UI, Provider protocol
  changes, E2E rollout, Living Spec promotion, Agent decommission behavior changes,
  deletion of retained conversations or remote Toolkit state, cancellation, or
  rollback from `removing`.
- Interfaces:
  - Confirmation returns the durable removal operation and privacy-safe aggregate
    impact. Same Agent/idempotency/request evidence replays; another request cannot
    create a competing active operation.
  - Coordinator stage and retry metadata remain projections of durable operation
    state, not independent authorities. Lease loss stops mutation and retries from
    PostgreSQL.
  - Cleanup pages use a monotonic root-context cursor and cumulative counts. No
    pre-removal `pending` or `bound` context may remain before finalization.
  - Physical deletion uses Phase 4 repository transitions and exact desired
    generation. The coordinator never writes terminal acknowledgement fields
    directly.
  - Existing Agent decommission remains a distinct whole-Agent lifecycle and is not
    reused as authority to delete retained state.
- Approved Design mechanisms: `M2`, `M7`, `M9`, `M11`, `M14`, `M15`.
- Authority references: `runtime-260803/REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`;
  `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`, `ADR-D5`; approved Design
  revision 3; current Agent, Conversation, Workspace, Agent Runtime Control,
  Persistence, and execution-loop Specs.
- Design delta: `None`
- Removal obligations:
  - Remove Runtime-owned Session Project registrations, managed worktree metadata,
    and path claims while retaining Session trees and transcripts.
  - Clear Agent automatic/default/preset/catalog Runtime-path projections.
  - Remove Runtime-only filesystem Skill/instruction, pending action, and credential
    projections without deleting managed VFS or remote Toolkit state.
  - Replace detail-bearing Agent-wide removal inventory with content-free aggregate
    authority.
- Absence verification:
  - Repository queries prove zero retained Runtime-owned Project/worktree/path-claim,
    pending Runtime-action, and Runtime-only projection rows after cleanup.
  - Every pre-removal root context is `none` or `invalidated`; no `pending` or
    `bound` row remains and invalidated rows never reopen after re-add.
  - Public/API paths contain no Phase 5 action or progress contract.
  - Searches find no direct terminal acknowledgement writes outside the owning
    AgentRuntime repository and no Agent deletion in Runtime removal finalization.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Confirmation and privacy-safe impact | `root` | `services/agent_runtime_removal/`, `repos/agent_runtime_removal/`, focused Agent/Session/Run/action repositories | Phase 1 operation model, Phase 2 capability CAS | irreversible `managed → removing` transition, exact replay, content-free counts | stale version, competing request, privacy, transaction rollback tests |
| Agent-wide interruption | `root` | focused methods in `repos/agent_session/`, `repos/agent_execution/`, action-execution repositories, broker wake integration | committed removing fence | durable stop requests and zero-active-work gate across all root trees | Team/User tree, active Run/subagent, queued action, retry/Redis-absence tests |
| Bounded product cleanup | `root` | new focused removal cleanup repository/service plus Session context, Project/worktree/path-claim, Agent Project, Toolkit-state surfaces | interruption complete | cursor-based invalidation and Runtime-owned state deletion preserving retained state | paging/idempotency, archive-pending, zero-retained-state, preservation tests |
| Physical deletion and finalization | `root` | removal coordinator, Agent/Runtime/removal repositories, scheduler registry | cleanup proof, Phase 4 terminal transitions | exact delete target/ack wait and `removing → none` completion | no Runtime, no physical binding, Provider ack, disconnect/retry, lease-loss tests |
| Integration and phase documentation | `root` | scheduler registry/config, phase plan, focused integration tests | all workstreams | stable Phase 5 checkpoint | Ruff, format, ty, focused/full pytest, pre-commit, absence searches |

- Integration order: privacy-safe inventory and confirmation fence → interruption
  primitives → bounded cleanup and cursor proof → physical deletion ownership →
  finalization → scheduler registration and integration tests.
- Independent review: `hardtack` performs one read-only review against M2/M7/M9/
  M11/M14/M15, focusing on irreversibility, exact version/idempotency locks,
  private-Session metadata absence, complete Agent-wide interruption, preserved
  state, cleanup cursor monotonicity, exact terminal authority, lease safety, and
  absence of Agent deletion. Security, privacy, data-loss, persistence, or interface
  corrections require targeted re-review by the same reviewer.
- Final validation:
  - Focused Agent, Session tree, Run/action, removal repository/service/coordinator,
    Project/worktree, Toolkit-state, terminal-delete, and scheduler tests.
  - `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run ty check --error-on-warning`, and full `uv run pytest -q` in
    `python/apps/azents`.
  - Repository pre-commit, `git diff --check`, privacy/retained-state assertions,
    and direct-write/Agent-delete/public-surface absence searches.
- Scope-drift check: Every behavior maps to M2/M7/M9/M11/M14/M15. This phase must
  not publish API/client/Web contracts, change Agent decommission semantics, delete
  retained product state, add cancellation/rollback, depend on Redis correctness,
  infer deletion from disconnect, or introduce a second cleanup/acknowledgement
  authority.
- Context checkpoint: Phase 4 provides exact add/rearm and terminal Control
  transitions. Phase 5 owns the irreversible internal removal lifecycle and leaves
  a durable completed operation plus retained terminal logical Runtime for Phase 6
  read/action projection. Phase 6 remains responsible for public authorization,
  preview/confirm/progress contracts, OpenAPI, and generated clients.
