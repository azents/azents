---
title: "Hierarchical Runtime Network Restriction Phase 2 Control Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, protocol, persistence]
---

# Phase Execution Plan

- Phase: `2/8 — Runtime Control v3 and diagnostics persistence`
- Branch/base: `feature/network-restriction-2-control` →
  `feature/network-restriction-1-contracts` at `3523d2538`
- PR boundary: Add Kubernetes Provider protocol v3 aggregate network-enforcement
  evidence and generation-scoped operational-diagnostics persistence without
  implementing strict Kubernetes resources, lifecycle enforcement, Helm
  attestations, or product API/UI projections.
- Inputs: Completed Phase 1 canonical effective Profile v3, mode-aware Provider
  compatibility, and application-impact classification; current protocol-v2
  Provider registration, Runtime configuration evidence, correlated `OBSERVE`
  completion, and one-shot fenced repair path.
- Deliverables: Protocol-v3 registration admission; bounded warning-only
  operational-diagnostics payload on registration and heartbeat; generated protobuf
  Python artifacts; aggregate `network_enforcement` observation model and
  protocol-version-aware report admission; current-observe repair and applied
  promotion fencing; nullable connection diagnostics JSONB and checked-at fields;
  generation-fenced repository/service snapshot replacement; safe internal Admin
  projection data; focused protocol, persistence, migration, reconciliation,
  validation, and redaction tests.
- Non-goals: Kubernetes Service/ConfigMap/Secret/Pod transport, CA generation,
  proxy/addon image, Runner trust bootstrap, strict Runtime resource lifecycle,
  mandatory Service observation, Helm settings/RBAC, operator attestation inputs,
  Admin/Public routes or OpenAPI, generated API clients, TypeScript/web surfaces,
  E2E, Living Spec promotion, removal of all protocol-v2 execution, or live
  infrastructure changes.
- Interfaces: Kubernetes Provider protocol versions v2 and v3 are explicitly
  admitted during the staged rollout. V2 reports may carry only the legacy
  actionable `network_policy` reconciliation shape; v3 reports may carry only one
  aggregate `network_enforcement` observation. The aggregate status is `in_sync` or
  `drifted`, has one bounded first-repair reason and safe bounded scalar metadata,
  and never exposes Kubernetes object inventory, names, ClusterIPs, policy bodies,
  credentials, certificates, or private material. Operational diagnostics are a
  bounded warning list with stable code, warning severity, and safe scalar metadata,
  plus a checked-at timestamp. Registration supplies the initial nullable snapshot;
  heartbeat may atomically replace it only for the authenticated active connection
  generation. Diagnostics do not enter the capability contract or digest, do not
  enqueue Profile reconciliation, do not suppress capabilities, do not promote
  applied state, and are never copied from an older connection generation. Runtime
  Control preserves existing exact configuration sequence, digest, desired
  generation, Provider generation, lifecycle state, and correlated request fences
  for applied promotion and repair.
- Approved Design mechanisms: `M8`, `M9`, `M10`
- Authority references: `network-260812/REQ-6`, `REQ-9`, `REQ-10`, `REQ-11`;
  `network-260812/ADR-D7`; approved Design Provider Capability and Deployment
  Configuration, Desired/Applied/Reconciliation Evidence, Failure/Retry/Recovery,
  Persistence/Migration/Rollout/Rollback, and Security sections; current Runtime
  Provider, Runtime Control, and Runtime Persistence Specs.
- Design delta: `None`
- Removal obligations: Replace protocol v2 as the only admitted Kubernetes Provider
  protocol and narrow `network_policy` as the only representable actionable
  observation with an explicitly separated v3 aggregate contract. Retain the active
  v2 path only for the approved staged rollout; Phase 4 owns final removal of active
  v2 actionable reconciliation. Replace connection projections without diagnostics
  with nullable generation-scoped snapshot fields while retaining valid legacy rows.
- Absence verification: Protocol conversion and Control admission tests reject v2
  aggregate evidence, v3 `network_policy` evidence, mixed/duplicate aggregate kinds,
  stale generations, uncorrelated reports, and unsafe/oversized metadata. Capability
  proposal/digest tests and searches prove diagnostics are absent from capability
  authority. Persistence tests prove a new generation starts without an older
  snapshot, stale/disconnected generations cannot replace diagnostics, and nullable
  legacy rows remain valid. Reconciler tests prove warnings and non-OBSERVE reports
  cannot trigger repair or applied promotion.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared protocol contracts | `/root` | `proto/azents/runtime_control/v1/runtime_provider_control.proto`, `python/libs/azents-runtime-control/src/azents_runtime_control/provider.py`, `grpc_provider_client.py`, focused library tests | approved M8/M10 payload boundaries | v3 diagnostics and aggregate evidence types, bounded validation, bidirectional protobuf conversion | proto generation, library Ruff/format/ty, targeted pytest |
| Control admission and reconciliation | `/root` | `python/apps/azents/src/azents/runtime/control_protocol/data.py`, `grpc/provider_server.py`, `reconciler.py`, focused tests | shared v2/v3 types and existing M9 fences | protocol-aware registration/report validation, aggregate current-OBSERVE repair, unchanged exact applied evidence authority | backend Ruff/format/ty, targeted gRPC/reconciler pytest |
| Connection diagnostics persistence | `/root` | `python/apps/azents/src/azents/rdb/models/runtime_provider_control.py`, `repos/runtime_provider_control/**`, `services/runtime_provider_control/**`, dependency wiring and focused tests | bounded diagnostics model and authenticated generation | nullable replaceable active-generation snapshot and safe internal projection | repository/service pytest, stale/disconnect/redaction tests, backend ty |
| Expand migration | `/root` | `python/apps/azents/db-schemas/rdb/migrations/versions/*`, `python/apps/azents/db-schemas/rdb/revision` | model fields and configured PostgreSQL environment | Alembic-generated linear nullable JSONB/checked-at revision with reviewed upgrade/downgrade | Alembic heads/current, migration upgrade/downgrade, revision alignment |
| Generated protobuf artifacts | `/root` | `python/libs/azents-runtime-control/src/azents_runtime_control/proto/runtime_provider_control_pb2*` | source `.proto` changes | source-generated Python and typing artifacts only | `uv run python scripts/generate_proto.py`, clean regeneration diff |
| Documentation | `/root` | this phase plan and active implementation plan only | approved Design revision 1 | tracked execution scope and checkpoint | docs validators, `git diff --check` |
| Independent review | `/root/network-260812-reviewer` | read-only Phase 2 diff | stable implementation and focused evidence | authority, protocol separation, evidence fencing, migration, redaction, and scope report | written review findings |

- Integration order: bounded shared diagnostics/evidence dataclasses → protobuf source
  and generated artifacts → protocol-version-aware gRPC conversion/admission →
  aggregate current-OBSERVE reconciler handling → connection model/repository/service
  snapshot persistence → Alembic-generated expand migration → focused validation →
  independent review → required corrections → final validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against the
  confirmed Requirements, ADR-D7, approved Design `M8`/`M9`/`M10`, current Specs,
  this plan, focused evidence, and the stable Phase 2 diff. It reports only material
  findings concerning protocol v2/v3 confusion, capability-authority drift,
  generation/sequence/digest/request fencing, unsafe diagnostics, migration
  correctness, unauthorized persistent state, removal boundaries, and scope drift.
- Final validation: run `uv run python scripts/generate_proto.py`, Ruff format/check,
  configured `ty check --error-on-warning`, and full tests in
  `python/libs/azents-runtime-control`; run affected backend Ruff format/check,
  configured `ty check --error-on-warning`, focused Provider gRPC, reconciler,
  connection repository/service, contract, and migration tests, then the full backend
  suite; verify `uv run alembic -c db-schemas/rdb/alembic.ini heads`, configured
  `current`, upgrade, and downgrade; run documentation validators, static absence and
  authority searches, clean protobuf regeneration, and `git diff --check`.
- Scope-drift check: Confirm complete M8/M9/M10 behavior and staged v2/v3 separation.
  Confirm no strict Kubernetes resources or lifecycle, capability attestation input,
  capability/digest changes caused by diagnostics, new network inventory/history or
  repair queue, direct fallback, autonomous generation change, Admin/Public API,
  OpenAPI/client/UI/E2E/Spec behavior, or live infrastructure mutation is added.
- Context checkpoint: Phase starts from Phase 1 commit `3523d2538`. Current Control
  admits only Kubernetes protocol v2 and the shared report model permits the single
  actionable `network_policy` kind. Existing repair already requires a correlated
  current `OBSERVE` completion and reuses generation, desired-generation,
  configuration-sequence/digest, lifecycle, and one-shot update fences. The durable
  connection row has no diagnostic snapshot. Alembic head is `3d9280a9ce92`; schema
  generation requires repository database settings that are not currently available
  through the default shell environment. Implementation must resolve that environment
  before generating the migration and must use `alembic revision --autogenerate`,
  never a hand-written revision. Remaining phases own Provider resources/lifecycle,
  Helm packaging, product projections, validation/Specs, and plan cleanup.

## Completion Checkpoint

- Completed behavior: Kubernetes Provider protocols v2 and v3 coexist at Control
  admission. V2 retains legacy `network_policy` reconciliation; v3 accepts exactly
  one aggregate `network_enforcement` observation and permits Provider configuration
  acknowledgement only for `in_sync`. Missing or drifted v3 evidence remains
  lifecycle/reconciliation input but cannot promote applied configuration or clear
  configuration-provider failures. Non-Kubernetes Providers cannot submit these
  diagnostics or reconciliation payloads.
- Diagnostics: Registration creates the required v3 warning snapshot and heartbeat
  may replace it only on the active authenticated generation. Warning metadata uses
  warning-code-specific keys and finite safe values, with strict digest, count,
  resource-kind, and verb validation. Persisted JSONB is revalidated on decode. An
  internal Admin projection returns only current generation, protocol version, and
  validated diagnostics; reconnect and disconnect make older snapshots unavailable.
- Persistence and migration: Alembic-generated revision `6e0b87045f7c` adds nullable
  JSONB and checked-at columns after `3d9280a9ce92`. Isolated PostgreSQL 17 upgrade,
  downgrade, and re-upgrade passed; Alembic current/head and the revision pointer all
  equal `6e0b87045f7c`.
- Independent review: `/root/network-260812-reviewer` reported one Critical and three
  Warnings. All were corrected and targeted re-review approved the stable diff with
  no remaining Critical or Warning findings.
- Validation: runtime-control Ruff/format/type and 117 tests passed; Kubernetes
  Provider Ruff/format/type and 94 tests passed; Docker Provider Ruff/format/type and
  34 tests passed; backend Ruff/format/type and 4,292 tests passed with five existing
  dependency deprecation warnings. Protobuf regeneration was byte-stable, the docs
  index check and `git diff --check` passed.
- Authority and drift: M8/M9/M10 are complete for this phase. `Design delta: None`.
  Protocol-v2 execution remains intentionally active for staged rollout; strict
  Kubernetes resources/lifecycle, Helm attestations, product API/UI surfaces, E2E,
  Living Spec promotion, and final v2 removal remain assigned to later phases.
