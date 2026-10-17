---
title: "Personal Tools Workspace Foundation Correction"
created: 2026-10-17
tags: [toolkit, backend, security, implementation]
---

# Phase Execution Plan

- Phase: foundation correction of existing unmerged Phase 1.
- Branch/base: `fix/personal-tools-workspace-foundation-261017` → `e5add532e987645bc5228a833a4e43f25da55f45`.
- PR boundary: correct the existing foundation layer; keep current dirty Web integration isolated and preserved. Integrate the corrected foundation into the existing feature stack before correcting management, execution and Web. No merge or deployment.
- Inputs: confirmed Workspace-bound Requirements, appended ADR clarification, approved Design revision 2 M1-M11. The requester instructed immediate correction after the r2 brief.
- Deliverables: User owner requires a real Workspace; scoped personal CRUD/policy repository contracts; membership constrained to the parent's Workspace; corrected unmerged forward migration; same-User A/B denial and policy isolation tests.
- Non-goals: management/provider API and client correction, execution admission, or Web redesign in this foundation boundary; these follow the corrected foundation.
- Interfaces: every personal repository operation requires owner User and Workspace; dependent membership copies constrained parent owner/scope; shared ownership contracts unchanged.
- Approved Design mechanisms: M1/M2/M10/M11, foundation interfaces consumed by M3-M9.
- Authority references: personaltools-261017/REQ-1/2/4/7/8; ADR retained canonical identity and policy plus scope clarification; Design r2 sections 2-4,8-10.
- Design delta: None.
- Removal obligations: null-Workspace personal owner, User-only parent predicates, cross-Workspace All snapshot and obsolete global tests; replace with explicit scoped boundaries, not fallbacks.
- Absence verification: invalid/missing owner scope rejected; same User's other-Workspace get/list/write/Agent mutation denied; database rejects cross-Workspace membership; no shared/Agent behavior delta.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Ownership/schema | /root | core/toolkit_ownership, rdb/models/toolkit and agent, existing feature migration | mandatory real Workspace and constrained membership | owner decoding, migration/schema integrity |
| Repository contracts | /root | repos/toolkit/personal and tests | owner+Workspace CRUD/locks/policy, ordinary membership and scoped All snapshot | real PostgreSQL A/B, concurrency, atomic rollback, shared regression |
| Documentation/integration | /root | this plan, approved snapshot, relevant Toolkit Spec | coherent phase evidence and next-layer contracts | docs catalog, diff checks, no final implemented date |

- Integration order: ownership/schema → repository/operations → regression tests → integrated checks → fixed reviewer → root corrections → correction commit and phase PR/update before later-layer correction.
- Independent reviewer: `/root/personal-tools-reviewer`, read-only; root requests stable integrated review and applies findings.
- Final validation: root Ruff format/check, configured typechecker, ownership/personal/shared repository tests, migration tests and docs/diff/hooks; phase CI and later complete assembled API/Worker/Web matrix.
- Scope-drift check: scope is User inside Workspace, per Toolkit policy; no global binding, new Provider platform, fallback, versioning or Runtime.
- Context checkpoint: current Web worktree remains dirty and untouched; this branch starts exactly at committed Phase 1 to keep correction reviewable. Prior global test successes do not prove corrected acceptance.

## Integrated Correction Checkpoint

- Personal owner DTO and parent storage require the real Workspace. Repository/operation signatures
  require owner User plus Workspace for create/list/get/lock/update/delete/read-access/mutation. The
  current active User and ordinary Workspace membership are checked, without shared-manager privilege.
- First restriction snapshots only eligible Agents in that Workspace. Per-Toolkit policies and
  sorted atomic batch locks remain unchanged. Parent/owner/Workspace and Agent/Workspace composite
  foreign keys reject cross-Workspace dependent rows in either direction.
- The unmerged forward migration keeps existing Workspace non-null, preserves shared/Agent IDs and
  grants, adds required composite supporting keys and matches model metadata. No data rehome or
  revision-marker-only workaround was used.
- Root verified full Ruff check/format and configured type checking; focused ownership/shared/personal
  repository regression: 43 passed; complete migration suite: 48 passed, including model/DDL alignment.
  Same-owner A/B lookup/write denial, foreign-Workspace Agent deltas, atomic cross-Workspace batch
  rollback, independent Toolkit policies, ordinary access loss and scoped deletion are covered.
- Root full backend regression passed: 12,798 passed, three existing skips, nine warnings in 362.71s.
  Public/admin OpenAPI dump completed with no generated schema delta at this foundation boundary.
  The fixed read-only reviewer `/root/personal-tools-reviewer` reviewed the complete integrated
  foundation against the pre-feature baseline under Design r2 and reported no actionable findings
  or material drift. No source correction or re-review was required.
  Management/API/Provider, runtime and Web corrections are still later layers, not completed by these
  foundational test results. No product E2E, merge or deployment is claimed.
