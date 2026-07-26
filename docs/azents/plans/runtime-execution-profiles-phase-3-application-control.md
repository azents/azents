---
title: "Runtime Execution Profiles Phase 3 Application and Control Execution Plan"
created: 2026-07-26
tags: [runtime, control, provider, runner, convergence, security]
---

# Phase Execution Plan

- Phase: `3 — Application, convergence, and Runtime Control evidence`
- Branch/base: `feature/runtime-execution-profiles-05-application-control` → `feature/runtime-execution-profiles-04-management-api-clients`
- PR boundary: Explicit Agent Apply, durable restrictive-only convergence, generation-fenced target/applied Runtime Policy Snapshot transitions, and Runtime Control/Provider/Runner execution-evidence contracts.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, the multi-phase plan, Phase 1 policy/snapshot domain from PR 3/11, and Phase 2 API intent surfaces from PR 4/11. Both predecessor PRs passed CI before this branch was created.
- Deliverables:
  - An explicit Agent Apply operation that validates current policy intent, atomically advances desired generation where required, and creates an immutable target snapshot without direct lifecycle side effects outside the established control path.
  - Durable convergence scheduling/scanning for Platform/Workspace restrictive changes only; expansion or Agent-intent changes remain pending until explicit Apply.
  - Exact target/applied evidence promotion fencing on Runtime, Provider binding, desired generation, snapshot identifier, policy digest, and module/source versions; retries of the same acknowledgement remain idempotent.
  - Runtime Control protobuf/shared-library, backend control validation/state sink, Provider adapters, and Runner evidence support for snapshot ID, digest, module versions, and desired generation.
  - Fail-closed treatment of missing, mismatched, stale, incompatible, or mixed-version policy evidence.
  - Focused backend, protocol, Runner, Provider, and convergence tests.
- Non-goals:
  - No Kubernetes Pod topology, NetworkPolicy/RBAC, storage, or Helm changes.
  - No gateway, Docker Engine, Runner Docker/Compose client behavior, engine capability enablement, or image build changes.
  - No new general Admin/Public management surface or hand-written UI. A narrow explicit Agent Apply action under the existing Agent owner/admin boundary is allowed because it is the production entry point for this phase's required Apply behavior; it must not broaden policy-management semantics.
  - No raw Provider configuration authority, credential sharing, Docker socket mounting, generic privileged toggle, live-cluster write, destructive reset, or workspace data deletion.
- Interfaces:
  - Lower-layer policy changes remain restrictive-only. Platform/Workspace tightening may auto-target through convergence; Agent Profile/override changes and authority expansion require explicit Apply.
  - A control acknowledgement can promote only the exact currently targeted snapshot whose Runtime ID, Provider binding, desired generation, execution digest, and required evidence match; a stale acknowledgement is never applied.
  - Provider compatibility is validated against provider-declared typed support and fails closed. Provider dynamic configuration and credentials are not product-policy input or response material.
  - Control and Runner authorization remains Runtime-bound and current-generation-bound; no wall-clock credential refresh bypass is introduced.
  - Stop/restart/recover/convergence preserve Agent Workspace data. Only the existing explicit reset path may destroy it.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Application, convergence, Control evidence, and protocol adapters | `/root/runtime-execution-implementer` | `python/apps/azents/src/azents/{services/runtime_execution_policy,runtime,services/agent_runtime,scheduler}/**` only where required; narrow existing Agent owner/admin action route/schema/test paths only for explicit Apply; `python/apps/azents/src/azents/runtime/control_protocol/**`; `python/apps/azents/src/azents/repos/{agent_runtime,runtime_provider_policy}/**` only for target/applied/convergence support; `proto/azents/**`; `python/libs/azents-runtime-control/**`; `python/apps/azents-runtime-runner/**`; `python/apps/azents-runtime-provider-{docker,kubernetes}/**`; generated protocol artifacts and associated tests | Phase 1 policy/snapshot invariants and Phase 2 intent API contracts | Apply/convergence behavior, exact evidence protocol, fail-closed adapters, tests | Backend, shared-library, Runner, Provider Ruff/format/Pyright/pytest; protocol generation/checks; narrow Apply OpenAPI/client regeneration if the existing action route contract changes; `git diff --check` |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-3-application-control.md`; localized integration/review fixes only after owner report | Implementer output | Complete phase contract, scope verification, PR creation | Plan/diff scope check, primary verification, independent review recheck |

- Integration order:
  1. Read existing lifecycle, desired-generation, snapshot, Runtime Control, Provider, and Runner contracts and their tests.
  2. Define Apply/convergence direction and target/applied evidence invariants in backend tests before altering dispatch.
  3. Extend protobuf/shared contracts and regenerate required artifacts before adapting backend, Providers, and Runner.
  4. Wire backend control validation and evidence promotion through existing control paths; enforce fail-closed mismatch behavior.
  5. Add explicit Apply and restrictive convergence behavior without changing reset/storage semantics.
  6. Run focused then all affected quality suites across backend, shared library, Runner, and both Providers.
  7. Continue the independent reviewer on the completed diff; apply accepted localized findings, re-run affected checks, and request reviewer recheck.

- Independent review: `/root/runtime-execution-reviewer` reviews against `runtime-260726/REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`, and `runtime-260726/ADR-D2`, `D4`, `D6`, `D7`, `D8`, `D10`, and `D11`. Required criteria: explicit Apply versus restrictive convergence direction, exact snapshot/generation/provider/evidence fencing, acknowledgement idempotency, fail-closed compatibility and mixed-version behavior, Runtime-bound authorization, no lifecycle/reset/workspace-loss regression, and no Phase 4/5/6 scope drift. Output is blocker/P1/P2 findings only.

- Final validation:
  - `git diff --check`
  - Backend, `azents-runtime-control`, Runner, Docker Provider, and Kubernetes Provider Ruff/format/Pyright/pytest suites.
  - Protocol generation/round-trip checks and generated-artifact drift checks.
  - Focused Apply/convergence/evidence tests for stale/missing/mismatched acknowledgement, current desired generation, retry idempotency, restrictive auto-target, expansion pending, and explicit Agent Apply.
  - Pre-commit on commit and relevant CI matrix.

- Scope-drift check: Compare the complete Phase 3 diff against `feature/runtime-execution-profiles-04-management-api-clients`. Reject Kubernetes Pod/NetworkPolicy/RBAC/storage/Helm changes, gateway/engine/Docker client/image behavior, management API/UI changes, raw Provider configuration/credential flow, live-cluster changes, and workspace-data destruction. Confirm every control promotion has exact Runtime/Provider/current target/generation/digest evidence fencing and every automatic action is restrictive-only.
