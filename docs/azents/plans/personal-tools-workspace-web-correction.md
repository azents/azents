---
title: "Personal Tools Workspace Web Correction and Acceptance"
created: 2026-10-17
tags: [toolkit, frontend, implementation, security, testing]
---

# Phase Execution Plan

- Phase: corrected Web and assembled acceptance (4/4).
- Branch/base: `fix/personal-tools-workspace-web-261017` on corrected runtime `52a6e212f`; new managed worktree preserves the old global-scope dirty Web draft.
- PR boundary: Workspace-scoped personal management, independent per-Toolkit Agent allowance from both entry points, existing Provider forms/callbacks, product-quality desktop/mobile UI and deterministic assembled API/Worker/Web acceptance. No merge/deployment.
- Inputs: approved Requirements/ADR/Design revision2 M1–M11; foundation e9baabe99, management ba16e7114 and runtime52a6e212f validated/reviewed and pushed to existing PRs2316–2318. Runtime root fullbackend12979passed/3skip; supplemental28passed; fixed reviewer no findings.
- Deliverables: explicit required Workspace personal owner routes/cache keys/tRPC/generated API calls; same-Workspace Toolkit-specific All/Selected editing; current Agent/composer navigation; common Provider/settings parity; redacted drafts and exact callback resume safety; polished real component states and final product acceptance evidence.
- Non-goals: cross-Workspace search/groups, account-global connections, new Runtime/credential authority, feature flags/versions/fallback, persistent mobile Session header entry, merge/deploy/live Provider interoperability claim.
- Interfaces: personal owner union includes required Workspace handle and no owning Agent/arbitrary User; route uses current real Workspace with server reauthorization. All personal queries/mutations/callback cache/resume/navigation include exact Workspace. Agent-side edits the same per-Toolkit policy. Existing shared/Agent branch semantics and generated client source remain unchanged.
- Approved Design mechanisms: M9/M11, consuming corrected M1–M8/M10.
- Authority: personaltools-261017/REQ1–9, retained ADRD1–D3 and Workspace clarification, Designr2 sections4/5/8–10; frontend conventions/current Specs.
- Design delta: None. Requester-authorized presentation correction: consolidate Workspace, Agent and Personal connection lists into shared `ToolkitCollection`/`ToolkitCard` rendering based on the established Workspace design; keep scope-specific I/O, permissions and actions in adapters. Reuse the existing AgentAvatar with ordinary-access profile metadata in eligible-Agent choices. This is local UI reuse without new ownership, persistence or Provider mechanisms.
- Additional acceptance: all three ownership lists invoke the same shared presentation, existing forms/Provider setup remain shared, and new component stories plus all affected ownership stories/E2E prove responsive and interaction parity. Prior text-only Agent and personal-specific row renders are superseded.
- Requester-approved final selection presentation: reuse Chat's selected-row background and right-centered blue check instead of a native checkbox square; render actual AgentAvatar/profile information, retain multi-select keyboard semantics, and keep Save/Cancel visible. Desktop/mobile component renders were approved without further design changes.
- Removal obligations: old draft account-global personal routes/links/caches/resumes and cross-Workspace eligible-Agent grouping/search; old global tests/fixtures must be replaced by scoped acceptance, not retained as current proof. Preserve old draft source separately, not old behavior in product.
- Absence verification: no account-global personal URL/API/client usage, sameUser A/B navigation/cache/callback isolation, no Workspace grouping/search, policy deltas preserve filtered-out same-Workspace Agents, no shared-manager/AgentAdmin requirement for own personal policy.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Scoped frontend contract | /root | Web shared Toolkit scope/types/wizards; tRPC personal/toolkit/Google/GitHub; callbacks/resume | exact Workspace owner/caches/Provider navigation | generated client types, strict input/scope/resume tests and sameUserA/B rejection |
| Management and policy UI | /root | Web personal-tools and Agent/composer/sidebar entries, locales, stories | Toolkit list/create/edit/access and exactAgent per-Toolkit policy, clear desktop/mobile states | component stories/play, visual capture with actual theme/fonts, keyboard/error/draft/overflow cases |
| Assembled acceptance | /root | testenv required API/Worker/Web fixtures/E2E and specs | deterministic fakeProvider end-to-end crossWorkspace/withdrawal/parity evidence | root local authoritative QA, existing regression+exactSHA CI |
| Documentation/promotion | /root | current Specs, approved snapshots when fully verified, temporary plans | truthful complete behavior/evidence and plan cleanup | docs catalog, fixed review, hooks/PR/checks |

- Integration order: transfer only Web draft source as reference → replace scope/routes/cache/Provider boundaries → sameWorkspace management/policy/navigation → type/unit/component/build checks → faithful desktop/mobile render and UX correction → assembled E2E → stable fixed review/root fixes → Specs promotion/plan cleanup → commit/PR and all stack exactSHA CI.
- Independent reviewer: `/root/personal-tools-reviewer`, read-only stable complete phase; root owns all changes and integrated validation.
- Final validation: TypeScript format/lint/typecheck/unit/component/build; deterministic API/Worker/Web E2E with real routes/ownership/Provider fixtures, crossUser/crossWorkspace/current withdrawal/recovery, browser callback and draft behavior; root backend regression only if implementation touched; docs/diff/hooks and exactSHA CI for whole stack.
- Visual contract: actual component renders via current app/Storybook theme, Geist fonts, explicit native desktop/mobile viewport, no fabricated HTML. Improve hierarchy/spacing/compact rows/action affordances and verify final images; old criticized global-scope screenshots are not accepted evidence.
- Scope drift: no added material mechanism. Route spelling/helper layout are implementation details. Preserve credentials redaction, metadata-only Google saves, uncertain outcome inspection without automatic replay, shared Runtime visibility and remote token limitations.
- Context checkpoint (automated acceptance): old draft worktree2 remains unmodified. Corrected Web typecheck, lint and production build pass; full Web suite742 passes with no failures/skips. Root assembled API/Worker/Runtime plus Personal/Agent/Workspace Web E2E4 pass in134.64s. Same independent reviewer cleared all3 earlier findings and reported no remaining actionable findings or material Design drift. Desktop/mobile real-component renders and final full-row selection were requester-approved. Complete story matrix rerun, commit hooks, Web PR and exact-head CI bookkeeping remain delivery gates. Authenticated copied-environment browser/Runtime stop-start QA remains a separate missing-login prerequisite and is not claimed complete; no live Provider acceptance, merge or deployment.
