---
title: "Ephemeral Redis Coordination Authority Phase 3 Plan"
created: 2026-09-08
updated: 2026-09-08
tags: [runtime, redis, validation, e2e, documentation, plan]
---

# Ephemeral Redis Coordination Authority Phase 3 Plan

## Phase Execution Plan

- Phase: `3 — empty-store validation, Spec promotion, and cleanup`
- Branch/base: `feature/redis-ephemeral-3-validation-specs` → `feature/redis-ephemeral-2-runtime-cutover`
- PR boundary: Complete deterministic empty-Valkey recovery evidence, synchronize current authority documentation, mark the approved snapshot implemented, record final removal evidence, and remove temporary implementation plans.
- Inputs: Phase 1 PR #1710; Phase 2 PR #1727; confirmed `redis-260907/REQ`; accepted ADR-D1 through ADR-D4; approved Design revision 2; completed Phase 2 implementation and independent review.
- Deliverables: Required Docker Runtime Provider E2E that clears Valkey and proves higher Runner authority plus new work recovery; final focused empty-store and removal evidence; current Spec promotion; matching Requirements/Design implementation markers; removal of the feature implementation and phase plans.
- Non-goals: No live Home sync, Redis clear, Runtime restart, PR merge, or new authority mechanism; no preservation of in-flight volatile work; no compatibility reader or fallback.
- Interfaces: Phase 2 PostgreSQL generation authority, one-shot candidate promotion, v2 Redis schemas, public nullable string representation, and strict Home cutover contract are fixed.
- Approved Design mechanisms: `M1` through `M12`, with Phase 3 completing `M10` and final validation for all mechanisms.
- Authority references: `redis-260907/REQ-1` through `REQ-8`; `redis-260907/ADR-D1` through `ADR-D4`; `redis-260907/DESIGN` revision 2; current Living Specs; Redis optionality convention.
- Design delta: `None`
- Removal obligations: Remove stale Living Spec Redis-retained generation authority; complete absence evidence for counters, legacy namespaces, numeric generation readers, and reference Valkey persistence; remove all temporary Redis feature plans after validation and Spec promotion.
- Absence verification: Repository searches, required E2E reset evidence, existing migration/store/registration/string/deployment tests, generated-client inspection, current Spec diff, and plan-path absence.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Empty-Valkey E2E | `/root` | `testenv/azents/e2e/src/tests/required/public/` | Phase 2 runtime cutover | Running Runtime reconnects with a higher Runner generation after `FLUSHALL`; new workspace operation succeeds | Focused required E2E, ruff, ty |
| Recovery/removal audit | `/root` | affected tests and repository-wide searches | E2E and Phase 2 checks | Bounded evidence for fail-closed volatile loss, durable recovery, rate-limit semantics, and removed legacy authority | Existing focused suites plus absence commands |
| Spec promotion | `/root` | `docs/azents/spec/**`, snapshot Requirements/Design | Stable validation evidence | Current authority and empty-store outcomes; matching `implemented: 2026-09-08` markers | `/spec-review`, docs validation |
| Plan cleanup | `/root` | `docs/azents/plans/redis-ephemeral-coordination-authority-*` | Validation and Spec promotion | Temporary feature plans removed | Path absence and docs index validation |

- Integration order: tracked phase plan → E2E reset coverage → focused/full validation and removal audit → Living Spec promotion → implementation markers → delete all feature plans → independent review → commit and PR.
- Independent review: `redis-implementation-reviewer` performs a read-only final Phase 3 review against the approved snapshot, checking E2E correctness, no direct DB writes, documentation accuracy, implementation markers, absence evidence, and complete plan cleanup.
- Final validation: changed-file pre-commit; E2E ruff/format/ty; focused empty-Valkey E2E; backend migration/registration/store/string/deployment suites as needed; full backend pytest/typecheck when invalidated; generated client and TypeScript checks when affected; docs validation and repository absence searches.
- Scope-drift check: Phase 3 adds verification and current documentation only; any new material runtime state, recovery mode, compatibility path, deployment strategy, or authority source returns to Design. Design delta remains `None`.
- Context checkpoint: Record E2E environment/result, fixed defects, complete mechanism coverage, removed units and search evidence, promoted Specs, implementation dates, deleted plans, reviewer result, PR URL, and remaining live Home rollout action.
