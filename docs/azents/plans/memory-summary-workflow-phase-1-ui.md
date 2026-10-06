---
title: "Memory Summary Workflow Phase 1: Settings UI"
created: 2026-10-06
tags: [memory, implementation, frontend, api]
---

# Phase Execution Plan

- Phase: `1/3 - settings UI and public read contracts`.
- Branch/base: `feature/memory-summary-workflow-261006` -> `main` (`b5e819ac`).
- PR boundary: all four UI requests, Saved cursor paging/current-summary read, generated clients and tests, approved snapshot and implementation plan.
- Inputs: confirmed snapshot `memory-261006`, existing current publication storage and historical cursor list.
- Deliverables: responsive explanation, actual Saved infinite query, integrated Historical overview, one-level per-session details and scroll pagination without Load more.
- Non-goals: common Session migration, new Memory host, new document versions/ledger, source manifest removal before its phase, production ops.
- Interfaces: Saved list requires explicit nullable cursor and limit internally and returns items/next_cursor; current-summary read returns selected exact Team/current-User current Markdown/timestamp or no document, without generation side effect. Public scopes/errors/CRUD remain.
- Approved mechanisms: `M11, M12`.
- Authority: `memory-261006/REQ-15..18`, `memory-261006/ADR-D6`, `memory-261006/DESIGN`.
- Design delta: `None`.
- Removal obligations: single full Saved list UI query/map and implicit 100-row corpus cap; Historical Load more; top-level session list; narrow header column.
- Absence verification: browser/story tests plus paged API tests (>100 rows), no Load more, overview does not eagerly display source list.

| Workstream | Owner | Paths | Dependency/output | Validation |
| --- | --- | --- | --- | --- |
| Public API/repository | /root | memory UI operations/service/data, agent public route/data, current-summary settings read | cursor and current summary contracts | root integrated Pytest/Ruff/typecheck |
| Frontend container/component/stories/tRPC | /root/memory-ui-implementer | agents memory feature, tRPC agent router, locale memorySettings keys | generated client contract after root regeneration | focused frontend checks, root integrated browser/story tests |
| Generated clients/specs | /root | generated OpenAPI client areas | updated source API | generator, diff/regeneration checks |
| Documentation/integration | /root | new snapshot/plans, memory Living Spec | approved changes/phase evidence | catalog validate and independent review |

Integration order: source public contracts -> regeneration -> frontend integration -> root checks -> freeze complete diff -> reviewer -> corrections/affected checks -> commit/push/PR. No next implementation phase before this PR exists.

- Independent reviewer: `/root/memory-feature-reviewer`, read-only, root requests integrated stable review.
- Final validation: root-owned API/repository tests, Ruff/typecheck, frontend format/lint/typecheck/build and Storybook/browser interaction as available. Record actual prerequisite absence; do not claim tests not run.
- Scope drift: preserve Saved CRUD, personal scope binding, disabled human inspection and source link semantics; no new generation/role/version/queue behavior.
- Context checkpoint: phase 1 implementation integrated. Root validation: backend full `ty check --error-on-warning`, focused Ruff/format, 63 API/PostgreSQL/service/repository tests; web format/lint/typecheck and 372 tests; web production build; generated Python-client 12 template tests; static Storybook 22 real Chromium play assertions via named local agent-browser; docs catalog/diff checks all passed. Browser container sandbox/resource launch failures were test harness observations, not product failures; rerun each story in a fresh named browser after build completion passed. Cross-deployment/live provider E2E remains part of final feature validation, not claimed run here. Phase 2 scouts confirmed same-ID Run/Event feasible, canonical DTO split and active-primary uniqueness preservation necessary; those paths are not implemented in phase 1. Stable complete diff is ready for the single independent reviewer.
