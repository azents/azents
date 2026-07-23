---
title: "Bound Runtime Control Connections Phase 1 Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, provider, security, database]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `1 — Authentication binding foundation`
- Branch/base: `feature/runtime-control-auth-03-bindings` → `feature/runtime-control-auth-02-plan`
- PR boundary: Durable Provider authentication bindings, migration/backfill, binding-backed Provider Control persistence, and typed bootstrap binding reconciliation
- Inputs: [runtimeauth-260723/REQ](../requirements/runtimeauth-260723-bound-runtime-control-connections.md), [runtimeauth-260723/ADR](../adr/runtimeauth-260723-bound-runtime-control-connections.md), [runtimeauth-260723/DESIGN](runtimeauth-260723-bound-runtime-control-connections.md), and the [multi-phase implementation plan](runtimeauth-260723-bound-runtime-control-connections-implementation-plan.md)
- Deliverables: Binding lifecycle and audit domain; non-null binding references from grants, credentials, and connections; forward migration and historical backfill; bootstrap ownership, conflict, and withdrawal reconciliation; Phase 1 tests
- Non-goals: Verifier registry, Kubernetes TokenReview calls or dependency injection, explicit gRPC authentication-method dispatch, Provider client token rotation, Runtime Runner authentication, Admin API or UI, Helm, Home, validation, and spec promotion
- Interfaces: `binding_id` is authoritative; grants, credentials, and connections reference it; connection authentication method and subject are immutable audit snapshots; bootstrap declarations own Kubernetes ServiceAccount binding configuration

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Binding domain and schema | `phase1-binding-domain` implementation subagent | `python/apps/azents/src/azents/core/enums.py`; `python/apps/azents/src/azents/rdb/models/runtime_provider_{binding,control}.py`; `python/apps/azents/src/azents/repos/runtime_provider_binding/**`; `python/apps/azents/db-schemas/rdb/**` | Frozen binding authority contract | Durable binding aggregate, audit projection, references, constraints, and historical backfill | Ruff; full Backend Pyright; binding repository tests; Alembic one-head and migration SQL |
| Bootstrap reconciliation | `phase1-bootstrap-binding` implementation subagent | `python/apps/azents/src/azents/repos/runtime_provider/repository.py`; `python/apps/azents/src/azents/services/runtime_provider_bootstrap/**` | Binding repository contract | Typed authentication declaration and source-owned binding create, reconcile, conflict, and withdrawal behavior | Ruff; full Backend Pyright; bootstrap parser and service tests |
| Control persistence and service | `phase1-control-binding` implementation subagent | `python/apps/azents/src/azents/repos/runtime_provider_control/**`; `python/apps/azents/src/azents/services/runtime_provider_control/{data.py,service.py,service_test.py}` | Binding data and repository contracts | Issued-token grant, credential, authentication, and connection lifecycle attached to one active binding without Phase 2 verifier dispatch | Ruff; full Backend Pyright; control repository and service tests |
| Integration | Root agent | This plan, staging boundaries, shared dependency fixes, commit, and PR | All workstreams | Scope-clean Phase 1 commit and stacked PR | Full final validation and scope-drift audit |

- Integration order: Freeze the binding contract; run bootstrap and control workstreams in parallel; integrate and validate at the root.
- Final validation: `uv run ruff check .`; `uv run ruff format --check .`; `uv run pyright`; focused binding, bootstrap, and control repository/service tests; `uv run alembic -c db-schemas/rdb/alembic.ini heads`; targeted offline migration SQL from the previous head.
- Scope-drift check: Compare staged paths and behavior against this plan. Move Provider app/client changes, gRPC method dispatch, TokenReview verification or DI, Runner authentication, Admin surfaces, Helm, Home, validation, and spec-promotion work to their later phase branches before commit.

## Fixed Phase 1 Contracts

- Every durable authentication binding has one Provider, explicit method, normalized subject, lifecycle state, owner, optional bootstrap declaration, method configuration, optimistic admin version, health timestamps, and revocation metadata.
- Enrollment grants and issued credentials reference a non-null binding. A grant exchange cannot change its binding.
- Provider Control connections reference a non-null binding and retain authentication method and subject snapshots for audit consistency.
- Provider identity is resolved from the binding. A denormalized Provider ID may only be checked for consistency.
- Bootstrap reconciliation may create and manage only bootstrap-owned bindings declared by its authoritative source.
- Kubernetes ServiceAccount configuration uses `namespace`, `service_account_name`, and the exact audience `azents-runtime-control`. Token verification remains Phase 2.
- Historical issued-token rows are backfilled to an issued-token binding without changing existing Provider IDs.

## Completion Gate

Phase 1 is complete only when:

1. The staged diff contains no Phase 2 or later paths or behavior.
2. The migration has one head and renders the new schema/backfill from the previous head.
3. Binding, bootstrap, and Provider Control repository/service tests pass.
4. Backend Ruff and full Pyright pass.
5. The Phase 1 commit and stacked PR are created before Phase 2 implementation resumes.
