---
title: "Ephemeral Redis Coordination Authority Phase 2 Plan"
created: 2026-09-07
updated: 2026-09-08
tags: [runtime, redis, postgresql, migration, deployment, plan]
---

# Ephemeral Redis Coordination Authority Phase 2 Plan

## Phase Execution Plan

- Phase: `2 — coordinated Runtime allocator cutover`
- Branch/base: `feature/redis-ephemeral-2-runtime-cutover` → `feature/redis-ephemeral-1-authority-foundation`
- PR boundary: Activate durable generation authority and remove Redis generation issuance in one reviewable cutover: activation migration with seed/triggers/marker, one-shot candidate publication, Provider/Runner final acceptance, fresh Runtime coordination namespace, Home non-overlap rollout contract, and ephemeral reference Valkey.
- Inputs: Phase 1 durable authority foundation; confirmed `redis-260907/REQ`; accepted `ADR-D1` through `ADR-D4`; approved Design revision `2`; feature implementation plan.
- Deliverables: Activation Alembic migration; database-enforced future-subject rows; candidate/promotion coordination contract and implementations; DB-only registration coordinator; gRPC/control-server integration; canonical Redis/public connection-generation strings and generated clients; versioned Runtime/Transfer/Terminal schemas; legacy allocator and active namespace removal; Home cutover configuration/documentation; reference Valkey without persistence; focused unit/integration/deployment tests.
- Non-goals: No broad empty-store cross-capability E2E, Living Spec promotion, implemented date, final absence report, or plan cleanup; those remain Phase 3.
- Interfaces: `RuntimeCoordinationStore` stages and promotes caller-generated records but never allocates generations. Registration coordinators own three DB-only transactions separated by volatile store calls. Provider acceptance commits connection history and authorization evidence with accepted generation. Runner acceptance revalidates current Runtime credential authority. PostgreSQL/Python/protobuf use positive signed-`BIGINT` integers; Redis uses 19-digit strings; public/browser JSON uses unpadded strings; TypeScript uses opaque exact equality.
- Approved Design mechanisms: `M2` through `M9`, `M11`, integration portion of `M12`.
- Authority references: `redis-260907/REQ-1` through `REQ-8`; `redis-260907/ADR-D1` through `ADR-D4`; `redis-260907/DESIGN` revision `2`; Redis optionality convention.
- Design delta: `None`
- Removal obligations: Remove Redis `INCR`/`PERSIST` and in-memory generation counters; remove active reads/writes of legacy Runtime and numeric Transfer/Terminal schemas; remove store-owned registration allocation; remove numeric public/browser connection-generation fields; remove reference Valkey persistence; prevent mixed legacy/new Runtime Control activation; add no numeric compatibility reader/union, legacy reader/import/fallback, lazy row creation, timestamp classification, dual authority, or permanent `Recreate` strategy.
- Absence verification: Repository searches for legacy counter helpers, `INCR`/`PERSIST` registration, old active prefixes, numeric connection-generation decoders, generation fallback, and Valkey volume; contract tests prove no allocator state in Redis/memory and exact string boundaries; migration tests prove seed/trigger/marker integrity; generated-client and rendered deployment tests prove coordinated contract and rollout changes.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Activation migration | `/root` | `python/apps/azents/db-schemas/rdb/**`, migration tests | Phase 1 schema | Table-locked existing-subject seed, Provider/Runtime insert triggers, cutover marker, revision update | Migration upgrade/race/seed/trigger/marker tests |
| Coordination contract | `/root` | `python/apps/azents/src/azents/runtime/coordination/**`, shared connection-generation conversion module | External generation contract | Candidate data/status, stage/promote APIs, memory/Redis implementations, v2 namespace, fixed-width Redis strings, removed counters | Shared store contract, Redis/memory parity, reset and signed-BIGINT string-boundary tests |
| Registration orchestration | `/root` | `python/apps/azents/src/azents/services/runtime_connection_registration/**`, Provider control and Runner auth services/repos | Migration and coordination APIs | DB-only allocation/preflight/acceptance for Provider and Runner | Service transaction-boundary, race, authorization, atomic-history tests |
| Runtime integration | `/root` | Runtime control protocol gRPC servers, control server, related focused tests | Registration orchestration | `register_accepted` only after acceptance commit; relay/replacement/close behavior preserved | Provider/Runner gRPC and control tests, full typecheck |
| Deployment contract | `/root` | Home/Azents Helm deployment templates/values/docs, `docker-compose.azents.yaml`, deployment tests | Activation boundary | One-time scale-zero/HPA/PDB procedure, readiness marker wiring, ephemeral Valkey | Helm render tests, Compose config assertions |
| String-schema and removal audit | `/root` | affected Runtime/Transfer/Terminal/API/OpenAPI/TypeScript boundaries and tests only where connection generation flows | Coordination/runtime integration | No legacy authority path; exact Redis/public strings through `2^63-1`; generated clients and TypeScript use strings | Search evidence, generation fixtures, source generation, and focused boundary tests |

- Integration order: activation migration → coordination string contract → Provider/Runner registration orchestration → gRPC/control-server wiring → Transfer/Terminal/public generated contracts → deployment/Valkey contract → removal audit → focused/full validation.
- Independent review: `redis-implementation-reviewer` reviews the stable Phase 2 diff read-only against the approved snapshot and phase contract. Criteria: no external call inside DB transactions; trigger/seed/marker atomicity; concurrency and ambiguous Redis outcomes; Provider history atomicity; Runner authority; no legacy or dual authority; safe-integer enforcement; deployment rollback boundary; removal completeness. Output is prioritized findings or explicit approval.
- Final validation: `git diff --check`; pre-commit; Ruff format/check; full Azents typecheck; focused migration, repository, coordination-store, registration-service, Provider/Runner gRPC, Helm, and Compose tests; repository absence searches.
- Scope-drift check: Every mechanism maps to `M2-M9`, `M11`, or Phase 2 integration evidence for `M12`; no durable operation/Transfer/Terminal authority, JSON string migration, permanent rollout mode, compatibility reader, live cluster write, Spec promotion, or implemented marker is permitted.
- Context checkpoint: Record activation revision and trigger names, changed coordination/registration interfaces, test commands/results, removal evidence, deployment contract, review outcome, remaining Phase 3 E2E/Specs, risks, and blockers before commit and PR creation.
