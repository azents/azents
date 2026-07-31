---
title: "Runtime Profiles Phase 1 Domain Foundation Plan"
created: 2026-07-30
tags: [runtime, provider, profile, backend, database, frontend, testenv]
---

# Phase Execution Plan

- Phase: `1 — Domain foundation`
- Branch/base: `feature/runtime-profiles-03-domain-foundation` → `feature/runtime-profiles-02-implementation-plan`
- PR boundary: Provider capability auto-authority, typed Profile contracts, persistence foundations, migration scaffolding, and direct acceptance-removal integration
- Inputs: approved `runtime-260730/REQ`, ADR, Design, and implementation plan
- Deliverables: typed domain models; Provider-scoped infrastructure/Profile persistence; Runtime configuration/reconciliation/recreation persistence; direct capability advertisement behavior; synchronized OpenAPI/generated clients; mechanical Admin capability and E2E fixture alignment; focused migrations and tests
- Non-goals: Public/Admin Profile CRUD, final Agent cutover, Provider command envelope, new Profile product UI
- Interfaces: schema families and ownership boundaries fixed by `runtime-260730/ADR`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Typed contracts | `/root` | `core/runtime_*profile*`, contract models | ADR | canonical Profile/capability models | focused Pytest |
| Persistence | `/root` | RDB models, repos, migration | typed contracts | durable Profile/config/task/operation foundations | migration/repo tests |
| Capability lifecycle | `/root` | contract service/repo/API, OpenAPI/clients, existing Admin capability view, E2E Provider fixture | current auth | valid advertisement becomes current immediately without acceptance UI or provisioning action | service/control, client, targeted TypeScript tests |
| Integration | `/root` | shared enums/data/tests | all above | stable phase diff | Ruff, Pyright, Pytest |

- Integration order: typed contracts → persistence/migration → capability lifecycle → generated clients and direct consumers → tests
- Independent review: `hardtack`, focusing on trust boundary, data retention, FK safety, and absence of stale accepted authority
- Final validation: backend Ruff, Pyright, focused/full affected Pytest, migration tests, OpenAPI/client generation, targeted TypeScript quality checks, docs validation
- Scope-drift check: no Profile CRUD, new Profile product UI, or Provider protocol payload changes beyond capability authority
- Context checkpoint: record schema/API changes, migration head, validation, remaining phase-2 cutover work, and stack risks before PR creation
