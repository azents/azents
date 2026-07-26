---
title: "Runtime Execution Profiles Phase 1 Policy Domain Execution Plan"
created: 2026-07-26
tags: [runtime, provider, workspace, security, backend, database]
---

# Phase Execution Plan

- Phase: `1 — Policy domain, resolver, and safe migration`
- Branch/base: `feature/runtime-execution-profiles-03-policy-domain` → `feature/runtime-execution-profiles-02-implementation-plan`
- PR boundary: First-class execution-policy persistence and typed restrictive resolution, immutable target/applied Runtime Policy Snapshot support, metadata-only audit, and safe `system-standard` Agent migration.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, and `docs/azents/plans/runtime-execution-profiles-implementation-plan.md` from PR 2/11.
- Deliverables:
  - Azents-owned typed execution capability catalog with canonicalization, field validation, dependency checks, monotone merge, change-direction classification, and bounded reasons.
  - Current-state Platform policy, stable Profile, Workspace policy/allowance, Agent execution intent, and metadata-only audit persistence with expected-version semantics.
  - Resolver service that combines Platform → Workspace → Profile → Agent input against a bound Provider capability projection without using Provider dynamic configuration as product-policy authority.
  - Runtime Policy Snapshot extensions plus explicit target and applied attachment behavior sufficient for later Apply and convergence work, without dispatching lifecycle changes in this phase.
  - Additive generated Alembic migration that seeds `system-standard`, backfills Agent execution settings, and does not replace existing baseline-equivalent Runtimes.
  - Focused unit, repository, service, and migration coverage.
- Non-goals:
  - No Admin/Public management routes, OpenAPI/client generation, or frontend work.
  - No Agent Apply endpoint, scheduler/convergence scan, or Runtime lifecycle dispatch changes.
  - No protobuf or shared Runtime Control contract change.
  - No Kubernetes Pod/NetworkPolicy/RBAC/engine-storage topology change.
  - No gateway, Docker Engine, Runner Docker client, build/run/Compose behavior, or new execution capability advertisement.
  - No live cluster write action or persistent engine storage enablement.
- Interfaces:
  - Execution module schemas and canonical resolver output are application-owned and must not reuse Provider `optional_capabilities` or Provider dynamic field definitions as policy authority.
  - Mutable policy resources use `expected_version`; a stale mutation has no settings, audit, or partial side effect.
  - The resolver returns one structured result containing canonical effective modules, digest, source versions, governing layers, reductions, direction classification, and availability reason rather than parallel positional values.
  - `system-standard` has a stable reserved key, disabled optional container authority, and cannot be broadened, retired, or deleted through ordinary mutable Profile behavior.
  - Existing Provider contract/configuration revisions and Provider binding semantics remain intact. This phase must not alter durable Provider selection or fallback rules.
  - Snapshot history remains immutable. The new target/applied reference model must preserve existing snapshot rows and prevent a stale snapshot from becoming applied.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Policy domain and migration | `/root/runtime-execution-implementer` | `python/apps/azents/src/azents/core/runtime_execution_policy*`, `python/apps/azents/src/azents/rdb/models/runtime_execution_policy.py`, `python/apps/azents/src/azents/repos/runtime_execution_policy/**`, `python/apps/azents/src/azents/services/runtime_execution_policy/**`, `python/apps/azents/src/azents/rdb/models/{agent_runtime.py,runtime_provider_policy.py,agent.py}`, `python/apps/azents/src/azents/repos/{agent_runtime,runtime_provider_policy,agent}/**` only where required, `python/apps/azents/db-schemas/rdb/migrations/versions/*`, `python/apps/azents/db-schemas/rdb/revision`, associated tests | Approved core docs and this plan | Domain models, generated migration, resolver/service, snapshot attachment support, Standard backfill, tests | Backend Ruff/format/Pyright, targeted pytest, migration upgrade/invariant test, `git diff --check` |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-1-policy-domain.md`; localized integration/review fixes only after owner report | Implementer output | Complete phase contract, integrated diff, validation evidence, PR creation | Plan/diff scope check, primary verification, independent review recheck |

- Integration order:
  1. The implementation owner reads the applicable Python, migration, and repository conventions before edits.
  2. Define closed module/catalog data contracts and resolver tests before persistence wiring.
  3. Add current-state models/repositories and generated additive migration, including Standard seed/backfill.
  4. Extend snapshot target/applied attachment semantics and implement services under transactional locks.
  5. Add migration, repository, resolver, and service tests.
  6. Run focused checks, then primary-agent verification and scope review.
  7. Continue the independent reviewer on the completed diff; apply accepted localized findings, re-run affected checks, and request reviewer recheck.

- Independent review: `/root/runtime-execution-reviewer` reviews the completed phase diff against `runtime-260726/ADR-D1`, `D2`, `D4`, `D6`, `D10`, and `D11`. Required criteria: no Provider-defined policy authority, strict lower-layer non-expansion, atomic expected-version and audit behavior, immutable snapshot history, reserved Standard migration safety, no lifecycle capability grant, no changes outside phase boundary. Inputs are the approved core docs, this plan, primary verification output, and the final branch diff. Output is blocker/P1/P2 findings only.

- Final validation:
  - `git diff --check`
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - Focused pytest for new execution-policy, snapshot/repository, Agent migration, and affected selection/lifecycle behavior.
  - Representative Alembic upgrade from an existing-schema fixture or documented equivalent invariant test.
  - Pre-commit on commit, including docs snapshot/index validation.

- Scope-drift check: Compare `git diff feature/runtime-execution-profiles-02-implementation-plan...HEAD` against this plan. Reject API routes, OpenAPI/generated clients, TypeScript, protobuf, Kubernetes Provider/Helm, gateway/Runner image, Scheduler dispatch, and live cluster changes. Confirm every changed executable path is owned by the implementation workstream and every new behavior is covered by the listed focused validation.
