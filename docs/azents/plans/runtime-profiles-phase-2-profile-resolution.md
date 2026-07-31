---
title: "Runtime Profiles Phase 2 Profile APIs and Resolution Plan"
created: 2026-07-30
tags: [runtime, provider, profile, backend, api, migration]
---

# Phase Execution Plan

- Phase: `2 — Profile APIs and resolution`
- Branch/base: `feature/runtime-profiles-04-profile-resolution` → `feature/runtime-profiles-03-domain-foundation`
- PR boundary: Provider infrastructure Profile APIs, Workspace Runtime Profile APIs/defaults, Agent single-Profile selection, deterministic desired configuration resolution, reconciliation fan-out, and one-way legacy backend cutover
- Inputs: completed Phase 1 typed domain, persistence, direct Provider advertisement authority, migration scaffolding, and PR #1043 review evidence
- Deliverables: Admin Pod/Container Profile CRUD; Public Workspace Runtime Profile CRUD/default/availability; nullable Agent `runtime_profile_id`; immutable ready/blocked desired revisions; durable source reconciliation with stale fencing; legacy data conversion and read cutover; synchronized OpenAPI and generated clients
- Non-goals: Provider command-envelope replacement, Kubernetes/Docker lowering, lifecycle command guards, bulk recreation execution, and new Profile management UI
- Interfaces: exact Provider/infrastructure/Workspace Profile references; optimistic versions; current Provider advertisement authority; no fallback or Provider substitution; Workspace-owned Agent selection

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Profile application services and APIs | `/root` | `services/runtime_profile_*`, `api/admin/runtime_provider/**`, new Public Runtime Profile API, `repos/runtime_profile/**` | Phase 1 models | Provider-scoped infrastructure and Workspace-scoped Runtime Profile CRUD/default/availability | authorization, ownership, optimistic concurrency, OpenAPI tests |
| Agent selection cutover | `/root` | Agent RDB/repository/service/Public API and Agent Runtime indexed bindings | Workspace Profile API | nullable `runtime_profile_id`, creation-time default selection, removal of active Provider/restriction mutations | Agent create/update/default/missing-Profile tests |
| Resolution and reconciliation | `/root` | Runtime Profile compatibility/resolution services, reconcile worker/repository, desired configuration attachment | exact selection and current capability | deterministic ready/blocked revisions and bounded durable fan-out with stale fencing | compatibility, retry, cursor, stale-task tests |
| Migration and generated contracts | `/root` | Alembic migration sequence, OpenAPI specs, Python/TypeScript generated clients | completed service/API cutover | one-way legacy conversion, read-disabled legacy paths, synchronized clients | PostgreSQL roundtrip/equivalence, generation checks |

- Integration order: Profile services/repository queries → Admin/Public APIs → Agent selection → deterministic resolver → reconcile fan-out → migration conversion/read cutover → generated clients
- Independent review: `hardtack`, focusing on authorization and exact ownership, optimistic stale fencing, migration equivalence/data retention, fail-closed availability, and absence of legacy fallback
- Final validation: backend Ruff/format/Pyright and focused affected Pytest; PostgreSQL migration roundtrip and conversion fixtures; OpenAPI dump/client generation; generated-client import/type checks; docs index and pre-commit
- Scope-drift check: no Provider protocol payload, Provider implementation lowering, command-guard/recreation execution, or Profile product UI changes
- Context checkpoint: record API/schema cutover, legacy references removed or intentionally retained for later protocol compatibility, reconciliation evidence, migration fan-out measurements, validation, reviewer result, and Phase 3 protocol inputs before PR creation
