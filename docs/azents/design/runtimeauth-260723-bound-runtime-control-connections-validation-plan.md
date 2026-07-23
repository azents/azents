---
title: "Bound Runtime Control Connections Validation Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, authentication, validation, security]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Validation Execution Plan

## Phase Execution Plan

- Phase: `8 — Validation`
- Branch/base: `feature/runtime-control-auth-08-validation` → `feature/runtime-control-auth-07-helm-workload-identity`
- PR boundary: Cross-stack validation evidence and only the minimal test or implementation corrections discovered by that validation
- Inputs: Completed binding foundation, explicit Provider authentication, Runtime-bound Runner authentication, Admin lifecycle, and Helm workload-identity PRs
- Deliverables: Reproducible validation report; migration-head and schema evidence; full backend/shared runtime/provider/runner/chart/Admin Web validation; security-invariant scans; Requirements/ADR/Design comparison; CI results for the complete implementation stack; explicit live-Kubernetes prerequisite status
- Non-goals: Living spec promotion, implemented dates, implementation-plan cleanup, Home snapshot changes, live deployment, Kubernetes writes, Runtime PVC replacement, new product behavior, and unrelated refactors
- Interfaces: Authentication methods, binding identity, exact `azents-runtime-control` audience, Runner desired-generation authority, Admin secret redaction, chart ServiceAccount identity, and stable Runtime PVC identity are frozen by the implemented phases

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Backend and migration | validation-backend | `python/apps/azents/**` (read-only unless a validation defect is found) | Phases 1–4 | Migration head, full Pyright/tests, focused auth/bootstrap/Admin evidence | Ruff/format check, Pyright, pytest, migration checks |
| Runtime clients and providers | validation-runtime | `python/libs/azents-runtime-control/**`, `python/apps/azents-runtime-runner/**`, `python/apps/azents-runtime-provider-{docker,kubernetes}/**` (read-only unless a validation defect is found) | Phases 2–5 | Full runtime library/app results and credential-boundary scans | Ruff/format check, Pyright, pytest |
| Admin Web and generated clients | validation-admin-web | `typescript/**` (read-only unless a validation defect is found) | Phase 4 | Format/lint/typecheck/build and generated-client drift evidence | pnpm workspace checks |
| Helm and security invariants | validation-helm | `infra/charts/azents/**` (read-only unless a validation defect is found) | Phase 5 | Lint/render/schema and negative privilege/storage/legacy-secret evidence | Helm lint, chart pytest, rendered manifest inspection |
| Integration and evidence | root | `docs/azents/design/runtimeauth-260723-bound-runtime-control-connections-validation-report.md` | All workstreams and PR CI | Consolidated commands, results, skips, spec-drift table, and completion decision | Diff review, docs hooks, independent review |

- Dependency order: Run deterministic local workstreams in parallel; collect PR #824 and stack CI after all implementation PRs exist; compare evidence against Requirements/ADR/Design; write the report; fix only validated defects; rerun affected and final gates.
- Integration order: Runtime/backend/chart/Admin results → CI evidence → security and scope scans → Requirements/ADR/Design comparison → validation report → independent review.
- Final validation: Full project-specific Ruff/format/Pyright/pytest checks; TypeScript format/lint/typecheck/build; Helm lint/render tests; migration head and revision checks; generated-client drift checks; `git diff --check`; stack PR CI; secret/privilege/PVC invariant scans.
- Scope-drift check: Compare `feature/runtime-control-auth-07-helm-workload-identity...HEAD` with this plan. The PR may contain the plan, validation report, and minimal defect fixes only. It must not update living specs, implemented dates, cleanup documents, Home, or Kubernetes resources.

## Live Kubernetes Boundary

Live TokenReview and non-destructive deployment/PVC validation require an approved writable Kubernetes environment. The connected Home cluster remains read-only for this phase unless the requester explicitly authorizes the concrete deployment operation. Absence of approval is recorded as an unmet external prerequisite, not converted into a simulated pass.

## Completion Gate

Validation is complete only when:

1. Deterministic local checks and GitHub CI pass for every affected stack project.
2. Migration revision metadata resolves to one current head without editing an executed migration.
3. Provider, Runner, Admin, and Helm negative security invariants are evidenced without credential plaintext.
4. Existing Runtime PVC preservation is proven by deterministic code/tests; live PVC UID/PV/sentinel evidence is either collected with approval or explicitly marked blocked by the external prerequisite.
5. Every Requirements and accepted ADR contract is mapped to implementation and evidence, with no unresolved implementation defect.
6. An independent reviewer reports no blocker/P1/P2 findings in the validation diff and evidence.
7. The validation PR is created before spec-promotion work begins.
