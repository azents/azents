---
title: "Reliable Runtime Lifecycle Phase 1 Execution Plan"
created: 2026-08-25
updated: 2026-08-25
tags: [runtime, lifecycle, implementation, plan, provider]
---

# Reliable Runtime Lifecycle Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `1/2 Control and Provider convergence`
- Branch/base: `feat/runtime-reliable-lifecycle` → `origin/main`
- PR boundary: Durable Restart handoff, bounded Provider Restart deletion, and
  Recreation full-availability completion without public API changes
- Inputs: Confirmed `runtime-260825/REQ`, accepted `runtime-260825/ADR`, approved
  `runtime-260825/DESIGN` revision `1`
- Deliverables: Same-generation Restart-to-Start handoff, delete-only Restart in
  both Providers, full-availability Recreation success, focused tests
- Non-goals: Public lifecycle presentation, generated clients, frontend UI, E2E
  product flow, Spec promotion, or relational/protobuf migration
- Interfaces: Existing Provider completion report and current
  `agent_runtimes`/configuration columns; no new wire or persistence fields
- Approved Design mechanisms: `M2`, `M3`, `M4`, `M7`, `M9`
- Authority references: `runtime-260825/REQ-3`, `REQ-4`, `REQ-5`, `REQ-7`,
  `REQ-8`, `REQ-9`; `runtime-260825/ADR-D2` through `ADR-D5`;
  current Agent Runtime Control Spec
- Design delta: `None`
- Removal obligations: Provider-local delete-and-create Restart; Recreation
  success on configuration metadata alone
- Absence verification: Provider tests record deletion with no replacement
  creation during Restart; Recreation tests prove unready Provider/Runner cannot
  complete an item

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Restart handoff | `/root` | `python/apps/azents/src/azents/repos/agent_runtime/**`, `python/apps/azents/src/azents/runtime/control_protocol/grpc/**` | Existing correlated completion | Atomic same-generation Start rearm | Repository and gRPC bridge tests |
| Recreation completion | `/root` | `python/apps/azents/src/azents/services/runtime_recreation/**` | Restart handoff semantics | Full-availability item success | Recreation service tests |
| Docker Restart | `/root` | `python/apps/azents-runtime-provider-docker/**` | Existing lifecycle interface | Delete-only container Restart | Provider unit tests and quality |
| Kubernetes Restart | `/root` | `python/apps/azents-runtime-provider-kubernetes/**` | Existing ownership/deletion helpers | Delete-only execution-resource Restart | Provider unit tests and quality |
| Documentation baseline | `/root` | `docs/azents/requirements/**`, `docs/azents/adr/**`, `docs/azents/design/**`, `docs/azents/plans/**` | Approved Design | Reviewable authority and execution record | Snapshot/frontmatter validation |

- Integration order: repository handoff → gRPC correlated completion → Provider
  delete-only behavior → Recreation completion predicate → focused tests
- Independent review: `runtime-lifecycle-reviewer`; read-only review for authority,
  stale completion safety, Provider consistency, Workspace preservation, and Design
  coverage; inputs are snapshot trio, this plan, current Specs, and phase diff;
  output is prioritized findings
- Final validation: focused backend repository/gRPC/Recreation pytest; Docker and
  Kubernetes Provider ruff, typecheck, and pytest; pre-commit on changed files
- Scope-drift check: all phase behavior maps to `M2`, `M3`, `M4`, `M7`, or `M9`;
  no public schema, UI, migration, protocol field, fallback mode, or destructive
  recovery is added
- Context checkpoint: Phase begins from `origin/main` at `2b4b1d8ae`; current
  Provider lifecycle completion and connection-epoch fixes are already merged;
  remaining risk is asynchronous Kubernetes deletion before Start recreation

## Phase Checkpoint

- Completed behavior: Restart completion atomically rearms Start in the same
  desired generation; a lost completion makes the idempotent Restart eligible for
  bounded redispatch; duplicate, stale-Provider, superseded-generation, and
  cross-Runtime completions cannot mutate a current Runtime.
- Provider boundary: Docker validates stable Runtime ownership before delete-only
  Restart and preserves its Workspace root; Kubernetes validates execution
  ownership, requests Pod and execution-resource deletion, and preserves PVC and
  CA resources.
- Recreation boundary: a running item completes only after exact configuration,
  current connected Provider `RUNNING` evidence, and current Runner `READY`
  evidence with an authoritative Workspace path.
- Removal evidence: Docker and Kubernetes Restart tests show no replacement
  creation during the command; Recreation tests hold the concurrency slot while
  Provider or Runner availability is incomplete.
- Independent review: `runtime-lifecycle-reviewer` found one P1 request-to-Runtime
  completion-correlation gap. The correction stores dispatched command identity,
  validates completion and report Runtime IDs plus Restart desired generation
  before persistence, and passed targeted re-review with no remaining material
  findings.
- Validation evidence: backend focused suite `110 passed`; Docker Provider suite
  `26 passed`; Kubernetes Provider suite `85 passed`; Ruff formatting/checks,
  whole-subproject `ty --error-on-warning`, and `git diff --check` passed.
- Scope drift: all implementation remains within `M2`, `M3`, `M4`, `M7`, and
  `M9`; no public schema, migration, protocol field, fallback authority, or
  destructive recovery path was added.
- Design delta: `None`.
- Remaining work: open the Phase 1 PR, then begin Phase 2 API projection,
  generated clients, frontend, E2E, Living Spec promotion, and snapshot
  implementation marking on a dependent branch.
