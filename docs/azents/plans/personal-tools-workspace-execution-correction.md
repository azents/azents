---
title: "Personal Tools Workspace Execution Correction"
created: 2026-10-17
tags: [toolkit, backend, security, runtime, implementation]
---

# Phase Execution Plan

- Phase: correction of existing execution Phase 3 after management PR #2317 correction ba16e7114.
- Branch/base: `fix/personal-tools-workspace-execution-261017` on corrected management ba16e7114 plus original runtime phase rebased as fd35cafa1. Separate managed worktree preserves old dirty Web draft.
- PR boundary: update existing PR #2318 with corrected source projection/admission/refresh/publication/Runtime export; no merge/deployment/live Provider claim.
- Inputs: confirmed Requirements, ADR and approved Design revision 2 M1–M11; required User+Workspace ownership and scoped management/Provider contracts; fixed management review completed and backend12901/migration50 passed.
- Deliverables: only same-Workspace personal candidates, canonical User-root plus execution Workspace capability, current exact parent/grant/Agent access at protected effects and later export; deterministic same-User A/B denial and withdrawal/recovery tests.
- Non-goals: Web activation/redesign, new Runtime, remote token recall, synthetic Workspace/global credential binding, fallback, flags or permission versions.
- Interfaces: typed personal target binds canonical root/User/Workspace/Toolkit/existing revision; generic execution remains Userless. Provider and Runtime gaps repeat exact current admission; completed DB operations contain no external I/O. Existing shared/Agent sources and callback contracts remain unchanged.
- Approved Design mechanisms: M5/M6/M7/M8/M11 consuming corrected M1–M4/M10.
- Authority: personaltools-261017/REQ-1/2/4/5/6/7/8/9, retained ADR D1–D3 plus Workspace clarification; Design r2 sections3/5–7/10, current Toolkit/Conversation/Google/MCP Specs.
- Design delta: None.
- Removal obligations: User-only candidate/source/current-parent/refresh/export predicates and scope-less source targets; obsolete global runtime assertions. Replace with explicit canonical Workspace, not post-display filtering or compatibility inference.
- Absence verification: same User in A/B cannot discover/call/refresh/publish/export A in B; foreign-Agent policy/source denied; no shared fallback, ambient viewer/sender authority, or copied grant. Existing namespace and lifecycle semantics preserved.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Canonical source | /root | core personal runtime; repos toolkit runtime; engine/worker source context and Toolkit state | required canonical Workspace capabilities and candidates | root lineage/Team/continuation/current-access and same-User A/B tests |
| Protected effects | /root | engine tooling admission, registered Providers; Google/GitHub/MCP repos/services | exact current scope before effects/after credential gaps/publication/export | deterministic Provider barriers, grant CAS, withdrawn/recovered source tests |
| Evidence and Specs | /root | corrected/current runtime Specs and phase plans | reachable scoped behavior and root validation | focused/full backend, migrations, Ruff/ty/docs/diff/hooks, exact-SHA CI |

- Integration order: inspect old runtime interfaces → required scope type/candidate/parent admission → current grant/discovery/refresh/publication/export propagation → deterministic A/B and withdrawal tests → root integrated validation → same fixed reviewer → root fixes/review → commit/update existing PR.
- Independent reviewer: `/root/personal-tools-reviewer`, read-only complete stable integrated phase; root owns all fixes and tests.
- Final validation: focused cross-layer/runtime/Provider suites, full backend, migration regression if affected, Ruff check/format, ty, docs/diff/hooks and exact new head CI. Final assembled API/Worker/Web E2E follows corrected Web phase.
- Scope drift: no additional material mechanism or authority; already-admitted effects may finish and previously exported processes/tokens may persist. Withdrawal stops subsequent managed admissions, not remote effects.
## Integrated checkpoint

- Management ba16e7114 is pushed to #2317 with root backend12901/migration50 and fixed review complete. Foundation e9baabe99 CI is complete with no failures. Management exact-SHA CI remains separately monitored.
- Runtime rebase preserved corrected management; conflicts kept corrected plan/Toolkit scope rather than reviving global runtime descriptions. Personal candidates, parent locks, reads and Selected membership now require exact User plus canonical executing Workspace. Existing captured targets already carried Workspace and retain it through Provider/current-grant/publication/export admission.
- Root focused runtime/Provider suite: 78 passed. Supplemental canonical lineage/final-catalog/Runtime export suite: 28 passed, including same-User A/B substitution denial, absent foreign namespace, independent membership withdrawal/recovery, and pre-effect denial. Ruff check/format, full ty, docs catalog and diff checks passed.
- The fixed reviewer `/root/personal-tools-reviewer` reviewed the complete integrated runtime phase against corrected management and identified no actionable findings or material Design drift. Review was read-only and does not substitute for root validation.
- Root full-backend validation: **12979 passed, 3 existing skips, 9 warnings in 399.88 seconds**. A supplementary test-only dispatch/export case added after the full run began is independently covered by the passing 28-test suite; production source remained unchanged. Hooks, commit, existing PR #2318 update and exact-head CI follow this stable checkpoint.
- Old global phase3 evidence is historical only. No corrected Web, assembled acceptance, live Provider interoperability, merge, deployment or production migration is claimed. Design delta: None.
