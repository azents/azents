---
title: "Session Model Change Phase 4 Validation Specs and Cleanup Plan"
created: 2026-08-19
tags: [model, session, validation, e2e, specs, cleanup]
---

# Session Model Change Phase 4 Validation, Specs, and Cleanup Plan

## Phase Execution Plan

- Phase: `4 — Deterministic validation, Living Spec promotion, and plan cleanup`
- Branch/base: `feature/model-260819-4-validation-specs-cleanup` → `feature/model-260819-3-composer-server-profile`
- PR boundary: add deterministic backend/migration/E2E evidence for the complete Session model-profile feature, update current Living Specs, mark the approved Requirements and Design implemented only after validation and review, and remove all temporary `model-260819` implementation plans.
- Inputs: Phase 1 Session state/API/migration, Phase 2 admission/fresh-turn semantics, Phase 3 authoritative Composer behavior, approved `model-260819` Requirements/ADR/Design revision 2, and current Conversation/Agent/Execution Loop Specs.
- Deliverables: migration/backfill coverage; required public and web E2E coverage using authoritative API/provider evidence and explicit synchronization; complete removal-absence verification; updated Living Specs; matching `implemented: 2026-08-19` metadata after approval; no remaining `docs/azents/plans/model-260819-*` files in the final tree.
- Non-goals: new product behavior, new persisted authority, live deployment/cutover, live provider credentials, Kubernetes writes, compatibility readers, fallback behavior, or PR merge.
- Approved Design mechanisms: `M1`–`M11`.
- Authority references: `model-260819/REQ-1`–`REQ-9`; `model-260819/ADR-D1`–`ADR-D6`; `model-260819/DESIGN` revision 2.
- Design delta: `None`.
- Exact reviewer: `/root/model-260819-implementation-reviewer`.
- Removal obligations: verify no browser profile key/draft profile/local relay, no mailbox promotion applied-profile write, no fresh-boundary stale prepared/default fallback, and no temporary implementation plan remains after cleanup.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Migration and backend integration evidence | `/root/model-260819-validation-owner` | `python/apps/azents/migration_tests/`, focused backend tests | backfill/null/partial-state/applied-vs-prepared and full-path regression evidence | focused migration/backend pytest, Ruff, ty |
| Required deterministic E2E | `/root/model-260819-validation-owner` | `testenv/azents/e2e/src/tests/required/public/`, existing support helpers only when required | model-only PUT, explicit/implicit trigger, remap/drift/recovery evidence without fixed sleeps | targeted required E2E and support tests |
| Browser E2E | `/root/model-260819-validation-owner` | `testenv/azents/e2e/src/tests/web/public/` | authoritative baseline, pending/revert, model-only Apply, Stop coexistence, reload/no browser profile persistence | targeted web E2E with stable ARIA/test IDs |
| Living Specs and implementation metadata | `/root/model-260819-validation-owner` | `docs/azents/spec/domain/{conversation,agent,model-catalog}.md`, `docs/azents/spec/flow/agent-execution-loop.md`, Requirements/Design metadata | current behavior promotion and implemented snapshot marking after validation | spec review, snapshot/docs validation |
| Plan cleanup and final integration | `/root` | `docs/azents/plans/model-260819-*`, complete stack | remove all temporary plans and prove absence | `git ls-files`, pre-commit, final diff review |

- Integration order: migration/backend evidence → deterministic required E2E → browser E2E → Living Spec updates → independent review and corrections → implementation metadata → remove all temporary plans → final checks → PR creation.
- Synchronization: use authoritative Session/history state, provider request journals, explicit client-tool/model-call barriers, exact scheduled dispatch, and existing external-channel fake barriers. Fixed sleeps are prohibited for ordering.
- Fixture policy: credential-free deterministic providers and API/UI-created state; direct SQL only in migration tests; no new prerequisite snapshot unless an existing required fixture cannot express the approved behavior.
- Independent review criteria: full M1–M11 coverage, migration/data-loss safety, authorization, no fallback/alternate authority, explicit-versus-implicit ordering, recovery semantics, frontend authoritative convergence, removal absence, Living Spec accuracy, and no scope drift.
- Validation matrix: focused backend/migration pytest; required/public and web E2E; TypeScript and Python format/lint/typecheck/build; generated OpenAPI/client drift check; docs snapshot/index validation; `git diff --check`; source-absence searches.
- Scope checkpoint: any finding that changes product behavior or a material mechanism returns to feature design. Test/support/spec refinements within approved contracts remain implementation details. `Design delta: None`.
- Completion checkpoint: Phase 4 ends when the final stacked PR is open, the complete stack has independent approval, every planned validation is either passing or explicitly classified as an external/non-feature flake with evidence, current Specs match implementation, Requirements/Design are marked implemented, all temporary plans are removed, and then CI monitoring begins for the full stack.
