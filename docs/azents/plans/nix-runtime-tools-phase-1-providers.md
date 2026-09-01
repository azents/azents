---
title: "Persistent Runtime System Tools Phase 1 Provider Plan"
created: 2026-08-31
tags: [runtime, package-management, nix, kubernetes, docker, provider, implementation]
---

# Persistent Runtime System Tools Phase 1 Provider Plan

## Phase Execution Plan

- Phase: `1/4 — Provider-owned Nix storage`
- Branch/base: `feature/nix-runtime-tools-1-providers` → `main`
- PR boundary: Approved snapshot docs plus Kubernetes Nix PVC lifecycle, bundled Provider deployment settings, Docker durable bind parity, and focused tests
- Inputs: Confirmed `runtime-260831/REQ`, accepted `runtime-260831/ADR-D1`–`ADR-D5`, approved `runtime-260831/DESIGN` revision `1`
- Deliverables: Both bundled Providers create a writable persistent `/nix` mount, preserve it across ordinary lifecycle, and delete it only at reset or terminal deletion while remaining compatible with the preceding Runner image
- Non-goals: Runner seed/bootstrap, Nix CLI or prompt activation, Kubernetes E2E, Runtime capability/Profile/API/Admin configuration, source builds, custom package wrapper
- Interfaces: Writable `/nix` mount owned by Runner UID/GID 1000; Kubernetes deployment-owned Nix storage settings; Docker per-Runtime host directory
- Approved Design mechanisms: `M4`, `M5`, `M6`
- Authority references: `runtime-260831/REQ-2`, `REQ-3`, `REQ-5`, `REQ-8`; `runtime-260831/ADR-D2`, `ADR-D3`
- Design delta: `None`
- Removal obligations: Replace the generic unsupported package-installation path with the approved native Nix baseline while retaining preinstalled tools
- Absence verification: Searches and tests prove no Nix capability/Profile field, daemon, source-build path, Provider config, custom wrapper, or Workspace-backed store is introduced

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved docs and plans | `/root` | `docs/azents/{requirements,adr,design,plans}/runtime-260831-*`, `docs/azents/plans/nix-runtime-tools-*` | Approved Design | Tracked authority and execution baseline | Docs validator, diff review |
| Kubernetes ownership and lifecycle | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/**`, focused tests | Existing PVC lifecycle | Deterministic Nix PVC, `/nix` Pod mount, preserve/reset/delete behavior | Ruff, ty, provider pytest |
| Kubernetes deployment settings | `/root` | `infra/charts/azents/**` | Provider configuration interface | Required Nix store class/size env and Helm schema/rendering | Helm render tests, schema validation |
| Docker durable storage | `/root` | `python/apps/azents-runtime-provider-docker/src/**`, focused tests | Existing Runtime host root | Nix host directory and `/nix` bind with current lifecycle | Ruff, ty, provider pytest |

- Integration order: authority docs → Kubernetes owned resource/PVC → Pod mount and lifecycle → Helm settings → Docker directory/bind → integrated focused validation
- Independent review: `hardtack`; review `runtime-260831/REQ`, ADR decisions, Design `M4/M5/M6`, this plan, the complete phase diff, ownership fencing, destructive boundaries, absence of capability/Profile authority, and focused evidence
- Final validation: Kubernetes and Docker Provider Ruff/format/ty/pytest, Helm render tests, docs validation, `git diff --check`
- Scope-drift check: All approved Phase 1 mechanisms present; no Runner seed/bootstrap, prompt activation, E2E substrate, new product configuration, source builds, wrapper, compatibility fallback, or unrelated dependency updates
- Context checkpoint: Record Kubernetes PVC contract, Docker host path/bind, lifecycle evidence, Helm interface, remaining Runner mount assumptions, risks, and blockers before PR creation

## Context Checkpoint

- Status: Implementation complete and ready for Phase 1 PR review.
- Completed mechanisms: `M4`, `M5`, and `M6` are present with `Design delta: None`.
- Kubernetes interface: every Runtime owns a separately named `nix-store-pvc`, mounted read-write at `/nix` under the existing UID/GID 1000 Pod security context. Start, restart, stop, recovery, expansion, reset, terminal deletion, partial-resource recovery, and foreign-resource fencing are covered.
- Kubernetes deployment interface: Helm values `runtimeProviderKubernetes.nixStore.className` and `.size` render required Provider environment variables. StorageClass replacement requires explicit Runtime reset; capacity expansion is in-place and shrink is deferred until reset.
- Docker interface: `<host_data_root>/agent-runtimes/<runtime_id>/nix` is owned and prepared with the existing Runtime directory policy, mounted at `/nix`, retained through container replacement, and removed by reset or terminal deletion through existing Runtime-root cleanup.
- Compatibility evidence: the preceding Runner source does not reference `/nix`; Phase 1 adds only a dormant writable mount and no Nix command or prompt authority.
- Validation evidence:
  - Kubernetes Provider: Ruff, formatter, `ty check --error-on-warning`, and `186 passed` on the rebased diff.
  - Docker Provider: Ruff, formatter, `ty check --error-on-warning`, and `36 passed` on the rebased diff.
  - Helm: `24 passed` with Helm `v3.18.4` rendering through the containerized test wrapper.
  - Documentation: generated index check, snapshot/frontmatter validation, JSON schema syntax, and `git diff --check` passed.
- Scope and removal evidence: no Runtime capability/Profile/API/Admin field, database state, generated client, Workspace-backed store, Nix daemon, source-build path, package wrapper, Runner bootstrap, prompt, or E2E substrate was added.
- Review: implementation-owner review found no remaining correctness, security, data-integrity, recovery, or scope-drift issue. Exact independent reviewer `hardtack` remains assigned and must be requested on the Phase 1 PR.
- Remaining stack: Phase 2 consumes the `/nix` mount contract for release seed/bootstrap/environment/prompt; Phase 3 provides Kubernetes E2E and Docker parity integration; Phase 4 promotes Specs and removes plans.
- Risks: after Kubernetes Nix PVCs exist, rollback must retain a Nix-aware Provider so terminal cleanup authority is not orphaned. No Phase 1 blocker remains.
