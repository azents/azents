---
title: "Persistent Runtime System Tools Implementation Plan"
created: 2026-08-31
tags: [runtime, package-management, nix, kubernetes, docker, implementation]
---

# Persistent Runtime System Tools Implementation Plan

## Authority and Scope

- Requirements: [runtime-260831/REQ](../requirements/runtime-260831-persistent-system-tools.md)
- Decisions: [runtime-260831/ADR](../adr/runtime-260831-persistent-system-tools.md)
- Approved Design: [runtime-260831/DESIGN](../design/runtime-260831-persistent-system-tools.md), revision `1`, authority `M1`–`M10`
- Superseding addon policy Requirements: [nix-260831/REQ](../requirements/nix-260831-user-managed-runtime-tools.md)
- Superseding addon policy Decisions: [nix-260831/ADR](../adr/nix-260831-user-managed-runtime-tools.md)
- Approved addon policy Design: [nix-260831/DESIGN](../design/nix-260831-user-managed-runtime-tools.md), revision `1`, authority `M1`–`M5`
- Current Specs:
  - [Agent Runtime Persistence](../spec/flow/agent-runtime-persistence.md)
  - [Agent Runtime Control](../spec/flow/agent-runtime-control.md)
  - [Runtime Provider](../spec/domain/runtime-provider.md)
  - [Toolkit](../spec/domain/toolkit.md)
  - [E2E-Primary Test Strategy](../spec/flow/test-strategy-e2e-primary.md)
- Design delta: None.

## Objective

Ship the approved Nix-based persistent system-tool addon for bundled Kubernetes and
Docker Runtimes without adding Runtime capability, Profile, database, API, Admin,
or package-policy management authority.

## Delivery Stack

| Phase | Branch | Base | Deliverable | Approved mechanisms |
| --- | --- | --- | --- | --- |
| 1 | `feature/nix-runtime-tools-1-providers` | `main` | Approved snapshot docs, Kubernetes Nix PVC lifecycle, Helm deployment settings, Docker durable bind parity, Provider tests | `M4`, `M5`, `M6` |
| 2 | `feature/nix-runtime-tools-2-runner` | Phase 1 | Release-owned Nix seed/bootstrap, user-managed addon environment, native prompt, focused Runner/Server tests | `runtime-260831/M1`, `M7`, `M8`, `M9`; `nix-260831/M1`–`M5` |
| 3 | `feature/nix-runtime-tools-3-validation` | Phase 2 | Kubernetes-focused integration/E2E substrate, Docker parity integration, validation evidence and fixes | `M10` plus validation of `M1`–`M9` |
| 4 | `feature/nix-runtime-tools-4-specs` | Phase 3 | Living Spec promotion, implemented snapshot dates, plan cleanup | Verified `M1`–`M10` |

All planned PRs use the title prefix `runtime tools [n/4]:`.

## Phase Dependencies and Interfaces

- Phase 1 adds dormant Provider storage support and fixes the writable `/nix` mount
  contract while remaining compatible with the preceding Runner image.
- Phase 2 fixes the Runner seed manifest, bootstrap state machine, Nix environment,
  and prompt text. It consumes the Phase 1 mount contract and must not change
  Provider storage authority.
- Phase 3 consumes the released interfaces from Phases 1 and 2 and may fix defects
  without adding behavior absent from Design Authority.
- Phase 4 promotes verified behavior to Living Specs and removes all four feature
  plan documents.

## Ownership

- Implementation owner: `/root`
- Independent reviewer for every phase: `hardtack`
- No overlapping implementation owners or delegated subagents.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Runner bootstrap | Empty seed, existing-store reconcile, digest failure, interrupted retry, offline catalog, corrupt-store failure |
| Nix behavior | Native search/profile-add, conservative release defaults, Agent-overridable native configuration, persistent config/state/profile paths, GC root preservation |
| Runtime prompt | Exact 30-word guidance, Runtime-free/shell-disabled absence |
| Kubernetes Provider | Nix PVC ownership, create/observe/preserve/expand/reset/delete, Pod mount, partial retry, foreign-resource rejection |
| Docker Provider | Nix host directory ownership, bind, replacement persistence, reset/terminal deletion |
| Kubernetes product path | Install, execute, recreate, reset, no-network failure, prompt, Workspace separation |
| Docker parity | Bootstrap/install/replacement/reset integration without duplicate full E2E matrix |
| Quality | Ruff, format, `ty check --error-on-warning`, affected pytest suites, Helm render tests, docs validation |

## Runtime and Data Boundaries

- `/nix` is Provider-owned durable storage outside Agent Workspace.
- Nix store/profile state is physical Runtime state and is not persisted in
  PostgreSQL, Redis, Runtime configuration, Toolkit State, or Provider reports.
- Kubernetes storage capacity is bundled Provider deployment configuration.
- Docker storage uses the existing Provider host data root.
- Reset and terminal deletion are the only destructive boundaries.

## Removal and Replacement

- Replace fixed-image-only tool availability with persistent Nix-installed tools
  while retaining the preinstalled baseline.
- Replace generic package-installation prompt claims with the exact approved native
  Nix guidance.
- Extend Kubernetes and Docker Runtime resource sets with Nix storage without
  changing Profile or capability authority.
- Verify no Nix enablement field, capability, database state, API, generated client,
  package inventory UI, wrapper, daemon, or package-policy control plane is
  introduced.

## Rollout

1. Phase 1 Provider support ships before the Nix-enabled Runner becomes authoritative.
2. Phase 2 Runner and Server prompt ship together after Provider support.
3. Ordinary recreation adopts the Nix store while preserving Workspace storage.
4. After Kubernetes Nix PVC creation, Provider rollback is replaced by forward fix.

## Context Checkpoints

Every phase records completed mechanisms, changed interfaces, focused evidence,
remaining stack scope, removal evidence, and blockers in its phase plan before PR
creation.

## Blockers

- No product or Design blocker. `nix-260831/ADR-D1` resolves the Phase 2 feasibility
  finding by defining release settings as Agent-overridable defaults rather than an
  Azents-enforced package policy.
- Phase 3 must establish the currently missing Kubernetes Runtime E2E substrate.

## Plan Cleanup

Phase 4 removes this plan and every `nix-runtime-tools-phase-*.md` plan after
verified Spec promotion.
