---
title: "Bound Runtime Control Connections Spec Promotion Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, authentication, documentation]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Spec Promotion Execution Plan

## Phase Execution Plan

- Phase: `9 — Spec promotion`
- Branch/base: `feature/runtime-control-auth-09-spec-promotion` → `feature/runtime-control-auth-08-validation`
- PR boundary: Promote the validated Azents Runtime Provider authentication domain and Runtime Control flow into current living specs
- Inputs: Completed implementation phases, validation report, zero remaining blocker/P1/P2 findings, and explicit pending Home/live prerequisites
- Deliverables: Current Runtime Provider domain spec; current Runtime Control flow spec; accurate `code_paths`, `last_verified_at`, and spec-version history; spec-review evidence
- Non-goals: Requirements or Design `implemented` markers, ADR edits, Home changes, live deployment, cleanup-plan deletion, code refactors, new behavior, and claims that pending external prerequisites passed
- Interfaces: Living specs describe the merged behavioral target of PRs 3/10 through 7/10, including durable bindings, explicit Provider methods, TokenReview, Runtime-bound Runner credentials, Admin lifecycle, secret-free Helm, and deterministic PVC preservation

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Provider domain spec | spec-provider | `docs/azents/spec/domain/runtime-provider.md` | Validation report and Phases 1, 2, 4, 5 | Binding aggregate, Admin lifecycle, connection authority, workload identity, deployment boundary | Spec/code comparison and docs validation |
| Runtime Control flow spec | spec-control | `docs/azents/spec/flow/agent-runtime-control.md` | Validation report and Phases 2, 3, 5 | Explicit Provider auth, Runner-bound credentials, expiry/revocation, Helm/RBAC, PVC-preserving rollout | Spec/code comparison and docs validation |
| Integration | root | Both specs and this phase evidence | Both workstreams | Consistent terminology, cross-links, version history, final spec-review result | Docs hooks, `git diff --check`, independent review |

- Dependency order: Run `/spec-review` against the complete implementation diff; update the two independently owned specs; integrate terminology and cross-links; validate code paths and current behavior; run docs hooks and independent review.
- Integration order: Provider domain → Runtime Control flow → shared terminology and version history → spec-review confirmation.
- Final validation: Documentation frontmatter/index checks, snapshot validator, `git diff --check`, full changed-spec readback, and independent blocker/P1/P2 review.
- Scope-drift check: Compare `feature/runtime-control-auth-08-validation...HEAD` with this plan. Only this plan and current living specs may change. Requirements, ADR, primary Design, Home, code, generated clients, and cleanup documents must remain untouched.

## Implemented-Marker Boundary

The `runtimeauth-260723` Requirements and primary Design do not receive `implemented: 2026-07-23` in this PR. Home compatible-snapshot changes and approved live Runtime PVC/TokenReview validation are explicit acceptance criteria and remain pending. The markers may be added only after those criteria are actually completed.

## Completion Gate

1. Both affected specs describe the validated current Azents behavior and no legacy shared-token or Provider credential-bootstrap contract remains.
2. Provider binding lifecycle, ownership, audit, health, and Admin management are represented without secret plaintext.
3. Provider and Runner identity authority, failure modes, revocation/expiry, and connection retention are explicit.
4. Helm workload identity, TokenReview RBAC, TLS, Provider RBAC, and PVC-preservation boundaries are current.
5. `code_paths`, `last_verified_at`, `spec_version`, and version history are updated consistently.
6. Spec-review reports no remaining spec impact for the implementation stack.
7. An independent reviewer reports no blocker/P1/P2 finding.
8. The spec-promotion PR is created before any cleanup or Home snapshot work begins.
