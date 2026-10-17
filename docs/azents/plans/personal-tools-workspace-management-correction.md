---
title: "Personal Tools Workspace Management Correction"
created: 2026-10-17
tags: [toolkit, backend, security, oauth, implementation]
---

# Phase Execution Plan

- Phase: correction of existing management Phase 2, after foundation correction e9baabe99 was pushed to PR #2316.
- Branch/base: `fix/personal-tools-workspace-management-261017` on corrected foundation e9baabe99 plus the rebased original Phase 2 commit. Rebase used scripts/rebase-stacked-prs.sh and resolved only master-plan/current-Spec/personal-helper overlap, retaining corrected scope and Phase 2 core exception factoring.
- PR boundary: update existing PR #2317 after integrated correction; no merge/deployment. Preserve old dirty Web draft and corrected foundation worktree.
- Inputs: confirmed Requirements, ADR scope clarification, approved Design revision 2 M1-M11; corrected required owner+Workspace repository interfaces.
- Deliverables: canonical authenticated manager includes required Workspace; scoped personal CRUD/access/test/MCP/GitHub/Google APIs and Provider attempts/callbacks/current grants; generated clients; exact same-User A/B authorization coverage.
- Non-goals: runtime-phase activation or Web redesign in this layer; no reduced Provider catalog, scope-less compatibility endpoint or synthesized Workspace.
- Interfaces: personal public routes use explicit /toolkit/v1/workspaces/{handle}/personal-... context resolved under current User/Auth Session. User owner/Provider subject carries canonical Workspace. External I/O remains outside completed DB scopes, with current re-admission before durable effects.
- Approved Design mechanisms: M3/M4/M10/M11 consuming corrected M1/M2; retained M7 parity.
- Authority: personaltools-261017/REQ-1/2/4/5/6/7/8/9, retained D1-D3 and Workspace clarification, Design r2 sections 3-5/8-10.
- Design delta: None.
- Removal obligations: User-only management subjects and parent lookups; personal targets requiring null Workspace; account-global route/callback return; obsolete personal-global assertions. Preserve existing shared/Agent callback formats and supported Provider actions.
- Absence verification: no personal route without required Workspace; missing/foreign scope rejected before external work; same User A/B parent/setup/exchange/outcome denial; generated public contract matches source; shared/Agent regression unchanged.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Manager and Provider subjects | /root | core personal/owner/Google/GitHub types, matching model constraints and existing unmerged phase migration | explicit owner+Workspace targets | typed decode/admission tests, migration/model alignment |
| Management and Provider admission | /root | repos toolkit management/oauth/GitHub/Google; services and public personal route modules | exact scope CRUD/policy/test/setup/refresh/publication | real database and deterministic fake external-gap tests, shared regression |
| Generated interfaces | /root | public OpenAPI and generated Python/TypeScript clients | required scoped routes/owner DTOs | source regeneration, client/schema checks |
| Documentation/evidence | /root | current relevant Specs and phase plans | reachable corrected behavior | root quality, docs/diff/hooks |

- Integration order: subjects/owner decode → repository manager admission/scoped calls → Provider target schema and grants → required Workspace route context/callback destinations → generated clients → root full/focused checks → stable fixed review → root fixes → existing PR update/exact-SHA CI.
- Independent reviewer: `/root/personal-tools-reviewer`, read-only after root stable integrated validation; root owns all fixes/checks.
- Final validation: full Ruff/typecheck/affected backend regression, Provider/migration/API/strict foreign-scope tests, generated client consistency, docs/hooks and CI; assembled API/Worker/Web acceptance follows complete corrected stack.
- Scope drift: no global personal binding, fallback, new credential authority/Runtime/version feature or remote revocation promise. Ordinary personal management needs current Workspace access, not shared manager/AgentAdmin.
## Integrated validation checkpoint

- Foundation PR #2316 remains at e9baabe99 with its completed validation and fixed review.
- Personal managers, owner decoding, Google/GitHub subjects, Provider persistence and MCP/Platform state now require the real Workspace. Personal HTTP families use `/toolkit/v1/workspaces/{handle}/...` and ordinary current membership, preserving shared/Agent contracts.
- Same-User A/B denial covers management reads/deletes/policy mutation, MCP callback rejection before token exchange, GitHub attempts and HTTP access observation before Provider I/O, and Google attempt/publication/saved grant/outcome/disconnect boundaries.
- Root broad focused API/service/personal-repository/owner suite: 459 passed. Migration suite: 50 passed. Ruff check, Ruff format, ty, documentation catalog and diff checks passed.
- Public OpenAPI and Python/TypeScript clients regenerated from source; TypeScript public-client typecheck passed and Python client template suite passed 16 tests.
- First full backend run exposed three stale account-global HTTP fixtures; root corrected their paths and WorkspaceMember dependency and verified them in the focused suite. Final whole-backend validation after all review corrections: **12901 passed, 3 existing skips, 9 warnings in 375.66 seconds**. Root retained the failed/reproduction logs separately and does not describe those runs as clean.
- Fixed read-only review found one concrete persistence regression: the GitHub creation unique subject index omitted owner discrimination, so shared/personal pending attempts in the same login/Workspace collided. Root reproduced the PostgreSQL UniqueViolation with a new coexistence test before correcting the model and preserving unmerged migration to key by Auth Session/Workspace/Agent/owner kind/owner User. Both creation orders, exact-target replacement and sibling-independent cancellation are covered. Current Google/MCP Specs were also synchronized with required Workspace paths/state/membership.
- Root affected GitHub creation/shared/personal suite: 18 passed; complete post-fix migration suite: 50 passed. The same fixed reviewer cleared both findings in targeted read-only re-review with no additional actionable findings. Root's final post-correction full-backend run passed as above. This stable reviewed and validated phase is ready for commit and update of existing PR #2317; its new head CI remains a separate requirement.
- Corrected foundation PR #2316 exact e9baabe99 CI has no failed or unfinished checks; this does not stand in for the corrected management head's future CI.
- Design delta: None. No personal Runtime/Web activation, live Provider acceptance, merge, deployment or production migration is claimed.
