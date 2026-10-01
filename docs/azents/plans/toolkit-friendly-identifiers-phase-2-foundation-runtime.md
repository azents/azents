---
title: "Toolkit Friendly Identifiers Phase 2 Foundation Runtime"
created: 2026-10-01
updated: 2026-10-01
tags: [toolkit, backend, engine, events, testing]
---

# Toolkit Friendly Identifiers Phase 2 Foundation Runtime

## Phase Execution Plan

- Phase: `2/3 Foundation duplicate-safe runtime readers`
- Branch/base: `feature/toolkit-identifiers-2-foundation-runtime` → `feature/toolkit-identifiers-1-foundation-data`
- PR boundary: make persisted Agent Toolkit namespaces mandatory for runtime and every registered Toolkit source consumer while retaining all Foundation write restrictions
- Inputs: completed phase 1 namespace schema, backfill, allocator, and write-path population; confirmed `toolkit-261001/REQ`; accepted `toolkit-261001/ADR`; approved `toolkit-261001/DESIGN` revision 1; current Toolkit and execution Specs
- Deliverables: namespace-joined effective reads; distinct stored Slug and effective namespace in Engine bindings; effective-namespace final prefixes; ToolkitConfig Name and bounded safe identity in catalog source; duplicate-safe Tool Search, executor, hooks, durable source snapshots, and activity; invariant failure for missing namespace authority; historical event compatibility
- Non-goals: optional Name/Slug APIs, frontend placeholders, duplicate Slug writes, unique-index removal, conflict-error removal, Capability migration, current Spec promotion, live deployment, or merge
- Interfaces: ToolkitConfig ID remains Session lifecycle identity; persisted Slug remains management/API base alias; auto-bound Toolkit names remain unchanged; prepared Run catalogs remain immutable; current duplicate write guards and Slug indexes remain active
- Approved Design mechanisms: `M5, M6, M7`
- Authority references: `toolkit-261001/REQ-4`, `REQ-5`; `toolkit-261001/ADR-D2`, `ADR-D4`; approved Design M5, M6, M7; current Toolkit and agent-execution Specs
- Design delta: `None`
- Removal obligations: stored Slug as registered Toolkit final-prefix authority; registered Toolkit prefix parsing as source authority; duplicate-Slug assertion in effective runtime reads
- Absence verification: repository-wide searches for registered `binding.slug` prefixing and final-name source parsing; catalog/source tests; duplicate projection tests; current conflict paths and indexes remain present

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Effective namespace read | `/root` | `python/apps/azents/src/azents/repos/toolkit/**`, `repos/engine_read.py`, namespace repository/data | phase 1 tables | exactly one active namespace joined to every persisted relation; missing authority fails closed | repository integration and invariant tests |
| Engine binding contract | `/root` | `python/apps/azents/src/azents/engine/run/contracts.py`, `engine/run/resolve.py`, `worker/session/toolkit_scope.py`, callers/tests | effective read | stored Slug, namespace, ToolkitConfig Name, and source identity carried separately; config ID lifecycle key preserved | resolve, worker, Session lifecycle tests and typecheck |
| Catalog and Tool Search | `/root` | `engine/events/tools.py`, `engine/tooling/tool_search.py`, catalog/client projection tests | binding contract | namespace-prefixed final names, compact source-qualified descriptions, no silent duplicate overwrite | catalog, Tool Search, declaration-budget tests |
| Hooks, execution, and events | `/root` | `engine/hooks/**`, `engine/events/**`, worker executor and chat source projections | catalog source | one selected source for routing, hooks, durable snapshot, and activity; old snapshots remain readable | hook/event/executor/frontend parser tests as applicable |
| Foundation compatibility | `/root` | Toolkit operation/service tests and schema absence searches | integrated runtime | duplicate writes still rejected and unique indexes remain; no API/Web change | focused Toolkit tests, schema checks, OpenAPI no-diff |
| Integrated validation | `/root` | affected backend tests and phase plan | stable diff | M5/M6/M7 evidence and removal proof | Ruff, format, ty, focused/full affected pytest, pre-commit |

- Integration order: effective read and invariant → binding contract and all constructors → catalog prefix/source → Tool Search → hooks/events/executor/activity → removal searches and integrated tests → independent review
- Independent review: `/root/toolkit-identifiers-reviewer`; read-only review of the complete stable diff against M5, M6, M7, source/routing correctness, duplicate safety, historical event compatibility, retained Foundation restrictions, and unauthorized Capability behavior
- Final validation: root-owned Ruff, format check, `ty`, effective repository/resolve/catalog/Tool Search/hook/event/executor/worker tests, Toolkit Foundation tests, OpenAPI no-diff check, pre-commit, and repository-wide absence searches
- Scope-drift check: all registered runtime readers must use namespace authority; no lazy allocation, missing-state fallback, optional API input, frontend change, duplicate write acceptance, schema index removal, new runtime mode, or second source authority may appear
- Context checkpoint: effective reads now require one active namespace, a reconciliation
  migration closes the phase-1 rolling-writer gap, bindings distinguish effective
  namespace from stored Slug, catalog prefix/source/search/hooks/events/activity share
  the selected source, MCP identity is origin-only, historical Web snapshots remain
  readable, and duplicate final names fail before publication. Foundation conflict paths
  and Slug indexes remain. Evidence: Python Ruff/format/ty, 426 affected tests, migration
  graph/model/reconciliation tests, TypeScript parser tests, ESLint, Prettier, direct Web
  typecheck, and pre-commit pass. Independent review found stale rolling Slug mappings and
  long-Name qualifier truncation; both corrections passed re-review with no remaining
  findings. Remaining work is commit and PR creation.
