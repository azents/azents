---
title: "Runtime Execution Profiles Phase 4 Kubernetes Enforcement Execution Plan"
created: 2026-07-26
tags: [runtime, kubernetes, network-policy, helm, security]
---

# Phase Execution Plan

- Phase: `4 — Kubernetes enforcement resource model`
- Branch/base: `feature/runtime-execution-profiles-06-kubernetes-enforcement` → `feature/runtime-execution-profiles-05-application-control`
- PR boundary: Kubernetes Provider resource-model enforcement for the exact Phase 3 policy envelope, fixed multi-container Runtime topology, Runtime-specific NetworkPolicy ownership, scoped RBAC/Helm support, and separate ephemeral engine-storage lifecycle support.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, multi-phase plan, and CI-unmonitored predecessor PRs through Phase 3. Phase 3 provides current generation-fenced evidence and fail-closed policy envelopes.
- Deliverables:
  - Provider-owned Runner, unprivileged policy gateway, and fixed privileged engine Pod topology with fixed security contexts, commands, sockets, volumes, and policy-derived resources.
  - Runtime-specific NetworkPolicies that bind to Provider-owned Runtime labels and prevent Profile-managed Pods from inheriting broad public egress.
  - Narrow RBAC and Helm templates/values required for policy-owned resources, with no secret literals and existingSecret references only.
  - Separate bounded ephemeral engine storage representation and lifecycle. Persistent engine storage remains unavailable unless a later Provider capability and bound storage proof explicitly qualify it.
  - Resource parsing/reuse/observation tests and Helm render/lint regression coverage.
- Non-goals:
  - No gateway Docker API authorization implementation, gateway or engine image implementation, Runner Docker/Compose client implementation, or verified build/run/Compose behavior. This phase owns only fixed resource topology and configuration references for those later behaviors.
  - No hostPath, host Docker socket, ServiceAccount token projection into Runtime Pods, raw Pod manifest/patch input, generic privileged option, raw Kubernetes customization, or live-cluster write.
  - No Admin/Public management API or UI work.
  - No persistent engine storage enablement, including on home.
- Interfaces:
  - Kubernetes Provider consumes the exact Phase 3 policy envelope and fails closed before resource mutation when required policy evidence is missing or incompatible.
  - Pod topology is an implementation-owned fixed mapping from typed policy modules; users cannot supply images, container security contexts, mounts, capabilities, host namespaces, ServiceAccounts, or arbitrary Pod fields.
  - Existing Agent Workspace PVC data remains preserved across stop/restart/recover/convergence. Engine ephemeral storage is separate and not reused as Agent Workspace storage.
  - NetworkPolicy ownership is additive and selector-scoped; the broad Runtime egress policy must exclude policy-managed Pods before restrictive policies apply.
  - Helm credentials are references only; no literals, projected token content, or secret values enter chart defaults, templates, rendered test fixtures, logs, or docs.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Kubernetes Provider enforcement and Helm | `/root/runtime-execution-implementer` | `python/apps/azents-runtime-provider-kubernetes/**`; `infra/charts/azents/**` only for runtime Provider RBAC/Helm/NetworkPolicy/value/render seams; provider contract paths only where exact typed capability declaration is required; associated tests | Phase 3 exact application evidence | Fixed policy-driven resource topology, scoped NetworkPolicy/RBAC/Helm, ephemeral engine storage contract, tests | Provider Ruff/format/Pyright/pytest; Helm lint/template/render; `git diff --check` |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-4-kubernetes-enforcement.md`; localized integration/review fixes only after owner report | Implementer output | Scope verification and PR creation | Plan/diff scope check, primary verification |

- Integration order:
  1. Read current Provider resource models, Pod reuse/observation paths, Helm templates, RBAC, and NetworkPolicy selectors.
  2. Define policy-derived resource topology and separate storage contracts with parser/serializer/reuse tests.
  3. Narrow broad egress selection before adding Runtime-specific policy resources.
  4. Add scoped RBAC/Helm templates and render regressions.
  5. Verify Agent Workspace PVC preservation and engine ephemeral storage separation.
  6. Run Provider and Helm quality suites; conduct focused review only for Requirements/Design mismatch, security risk, or major convention violation.

- Independent review: `/root/runtime-execution-reviewer` reviews only concrete Requirements/ADR/Design mismatch, security risk, or major convention violation. Primary criteria: fixed and non-user-controllable privilege; Runner sees only the gateway socket; engine sees only its private socket and engine storage; no host socket/hostPath/projected token/raw Pod escape; fail-closed evidence; NetworkPolicy selector isolation; narrow RBAC; no secret literals; Workspace PVC preservation; persistent engine storage remains disabled. Ignore style or minor consistency except at most two checks.

- Final validation:
  - `git diff --check`
  - Kubernetes Provider Ruff/format/Pyright/pytest.
  - Helm lint/template/render regressions for image references, RBAC, NetworkPolicy selectors, secret-reference-only configuration, and no hostPath/host socket/token mount.
  - Storage/reuse tests proving Agent Workspace PVC preservation and separate bounded ephemeral engine storage.
  - Pre-commit on commit. Do not monitor CI until the full PR stack exists.

- Scope-drift check: Compare the complete Phase 4 diff against `feature/runtime-execution-profiles-05-application-control`. Reject user-controlled gateway/engine images or privilege, host sockets/hostPath, Runtime ServiceAccount tokens, gateway authorization or Docker client behavior, API/UI, raw infrastructure customization, live-cluster actions, persistent engine storage, secret literals, and unrelated Provider changes. Confirm every policy-managed Pod resource derives only from typed policy and current exact evidence.
