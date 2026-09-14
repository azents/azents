---
title: "Runtime Web Heavy Transport Phase 4 Final Validation, Specs, and Cleanup"
created: 2026-09-14
updated: 2026-09-14
tags: [runtime-web, validation, specification, documentation, cleanup]
---

# Runtime Web Heavy Transport Phase 4 Final Validation, Specs, and Cleanup

## Phase Execution Plan

- Phase: `4/4 Final validation, Living Spec promotion, and plan cleanup`
- Branch/base: `feat/runtime-web-heavy-transport-4-specs-cleanup` → `feat/runtime-web-heavy-transport-3-clean-cutover`
- PR boundary: promote the validated replacement Runtime Web behavior into current Living Specs, mark the approved snapshot implemented, remove temporary implementation plans, and record final stack evidence without changing product behavior
- Inputs: Phase 3 commit `60d9121467d6165669dc14d58f0f22d94623de96`; stacked PRs `#1826`, `#1827`, and `#1830`; independent Phase 3 review PASS with `Design delta: None`; one-time heavy-load report dated `2026-09-14`; rebuilt-image lightweight Runtime Web E2E `4 passed`
- Deliverables: current Runtime Web Control/data-plane, persistence, and E2E strategy Specs; verified no-change findings for broader Agent, Conversation, Toolkit, execution-loop, and user-auth authority; matching `implemented: 2026-09-14` on Requirements and Design; removal of all `runtime-web-heavy-transport-*` implementation and phase plans; final absence and documentation evidence
- Non-goals: no new product behavior, protocol, schema, compatibility, fallback, replay, workload harness, heavy-load rerun, live deployment, Kubernetes write, operator cutover, PR merge, or Design revision
- Interfaces: current replacement `RuntimeWebGatewaySession.Connect`, `RuntimeWebControlSession.Relay`, and `RuntimeRunnerWebSession.Connect`; exact fingerprint and generation fencing; persistent local/one-hop relay data plane; Runtime-scoped capacity; no-replay drain; existing public authority and browser policy
- Approved Design mechanisms: `M10`, `M12`, `M13`, `M14`, and `M15`, with the implemented behavior of `M1` through `M9` promoted as current Spec
- Authority references: `runtimeweb-260914/REQ-1` through `REQ-14`; `runtimeweb-260914/ADR-D1` through `ADR-D9`; approved Design revision `1`; current Agent Runtime Control, Agent Runtime Persistence, E2E Primary Test Strategy, and unchanged Runtime Web authority Specs
- Design delta: `None`
- Removal obligations: remove the feature implementation plan and Phase 1 through Phase 4 execution plans after Spec promotion; retain the approved immutable Requirements, ADR, implemented Design, dated load-test report, code, tests, migrations, and current Specs
- Absence verification: repeat active source/config/protobuf/schema scans for every M14 legacy surface; verify no `runtime-web-heavy-transport-*` files remain under `docs/azents/plans/`; validate all Spec `code_paths`; confirm no heavy workload remains in pytest collection or CI

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Full-stack Spec impact audit | `/root` | `docs/azents/spec/**/*.md`, full stack diff from `origin/main` | Phase 3 validated implementation | exact impacted/no-change Spec classification | `/spec-review` method, code-path matching, implementation comparison |
| Living Spec promotion | `/root` | `agent-runtime-control.md`, `agent-runtime-persistence.md`, `test-strategy-e2e-primary.md`, and any materially matched current Spec | completed impact audit | current replacement transport, persistence, lifecycle, observability, and verification behavior | documentation validation, source and test cross-checks |
| Snapshot implementation and plan cleanup | `/root` | matching Requirements and Design frontmatter; `docs/azents/plans/runtime-web-heavy-transport-*` | validated Specs | immutable implemented snapshot and no temporary feature plans | snapshot validator, plan absence scan, docs index generation |
| Final integrated validation | `/root` | complete Phase 4 diff and unchanged Phase 3 implementation evidence | all documentation work complete | stable documentation-only final phase with reusable E2E/load evidence | docs checks, legacy absence scans, pre-commit, reviewer PASS, GitHub CI after all four PRs exist |

- Integration order: record this phase plan → audit the complete feature diff against current Specs → update only materially impacted Specs → reuse same-code final lightweight E2E and one-time heavy-load evidence → mark Requirements and Design implemented → remove all feature plans → run integrated documentation and absence validation → freeze diff → same-reviewer independent review → commit and open stacked PR → inspect the complete four-PR CI stack
- Independent review: `/root/runtime-web-heavy-reviewer` reviews the complete stable Phase 4 diff read-only against Requirements, accepted ADR, approved Design revision `1`, Spec authority, validation evidence, and cleanup obligations; `/root` owns all correction and targeted re-review
- Final validation: validate Spec bodies and `code_paths`; run snapshot/frontmatter and generated docs-index checks; repeat M14 active-surface, schema, protocol, setting, capability, and plan absence scans; verify Runtime Web E2E collection remains four lightweight tests; reuse the unchanged-code `4 passed in 162.21s` rebuilt-image E2E and `1 passed in 90.22s` dated heavy-load report; run `git diff --check` and changed-file pre-commit; inspect required GitHub CI only after PR `4/4` exists
- Scope-drift check: all current behavior is traceable to M1 through M15; no unauthorized mechanism or product contract is added; broader Specs change only when their current behavior text or `code_paths` materially requires it; heavy traffic remains one-time report evidence rather than recurring test collection
- Context checkpoint: Phase 3 replacement activation, removal, race corrections, complete validation, commit `60d912146`, and PR `#1830` are complete; Phase 4 owns only final current-Spec promotion, implemented dates, temporary-plan removal, final reviewer evidence, PR `4/4`, and full-stack CI observation; `Design delta: None`
