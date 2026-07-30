---
title: "Runtime Profiles Phase 3 Provider Protocol and Lowering Plan"
created: 2026-07-30
tags: [runtime, provider, protocol, kubernetes, docker]
---

# Phase Execution Plan

- Phase: `3 — Provider protocol and implementations`
- Branch/base: `feature/runtime-profiles-05-provider-protocol` → `feature/runtime-profiles-04-profile-resolution`
- PR boundary: backward-incompatible Runtime configuration protocol cutover, exact Provider/Runner evidence, Kubernetes Pod Profile lowering, and Docker Container Profile lowering
- Inputs: Phase 2 exact Workspace-owned Profile resolution, immutable ready/blocked Runtime configuration revisions, desired/applied revision bindings, and PR #1044 validation evidence
- Deliverables: protobuf and shared-control Runtime configuration envelope; backend dispatch from the exact ready desired revision; Provider and Runner revision/digest/generation evidence; Kubernetes Pod/PVC/NetworkPolicy lowering; Docker enforceable resource/network lowering; regenerated protobuf modules and focused integration tests
- Non-goals: lifecycle API command guards, automatic or bulk recreation orchestration, scoped recreation progress, product UI, integrated testenv journeys, and spec promotion
- Interfaces: replace `RuntimeExecutionPolicyEnvelope`/`RuntimeExecutionPolicyEvidence` with `RuntimeConfigurationEnvelope`/`RuntimeConfigurationEvidence`; evidence is exact `revision_id`, SHA-256 `digest`, and `desired_generation`; the envelope carries canonical schema-version-1 resolved configuration JSON; Provider and Runner reports must return the same evidence; no legacy parser, compatibility adapter, or fallback remains

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared protocol and control contracts | `/root` | `proto/azents/runtime_control/v1/runtime_{provider,runner}_control.proto`, `python/libs/azents-runtime-control/**` | Phase 2 revision document shape | generated protobuf, typed envelope/parser, exact Provider and Runner evidence | shared-library Ruff, Pyright, unit and gRPC serialization tests |
| Backend dispatch and evidence persistence | `/root` | `python/apps/azents/src/azents/runtime/control_protocol/**`, Runtime configuration repository integration | shared envelope | dispatch from one ready desired revision and persist matching Provider/Runner evidence without legacy policy snapshots | backend focused protocol, state-sink, reconciler, and composition tests |
| Kubernetes lowering | `/root` | `python/apps/azents-runtime-provider-kubernetes/**` | shared parser and typed Kubernetes Profile | per-command Runner/DinD resources, PVC class/capacity, network policy, service account, scheduling, and evidence rendering while preserving Provider-global security/connectivity and PVC lifecycle | rendered Pod/PVC/NetworkPolicy, reuse, observation, reset, terminal-delete, and unsupported-contract tests |
| Docker lowering | `/root` | `python/apps/azents-runtime-provider-docker/**` | shared parser and typed Docker Profile | per-command enforceable CPU/memory and Provider-managed network with host-directory lifecycle preserved and unsupported Kubernetes modules rejected | container-spec, reuse, observation, lifecycle, and unsupported-contract tests |

- Integration order: define shared envelope/evidence and regenerate protobuf → cut backend dispatch/report parsing to desired configuration revisions → update Runner evidence flow → update Kubernetes adapter/lowerer → update Docker adapter/lowerer → run cross-provider protocol integration checks
- Independent review: `hardtack`, focusing on exact revision ownership and stale fencing, removal of legacy execution-policy authority, secret-free envelopes/evidence, Provider-global versus per-command authority, Kubernetes PVC/network safety, and Docker capability honesty
- Final validation: protobuf regeneration reproducibility; Ruff/format/Pyright/Pytest for `azents-runtime-control`, Kubernetes Provider, Docker Provider, and affected backend protocol suites; full backend and repository pre-commit after integration
- Scope-drift check: no lifecycle endpoint semantics, recreation operation execution, frontend/API client work, testenv fixture expansion, spec promotion, or compatibility fallback
- Context checkpoint: record final protobuf fields, canonical configuration parser contract, backend desired-revision dispatch evidence, rendered Provider resources, Provider/Runner acknowledgement behavior, validation and reviewer evidence, and Phase 4 lifecycle/recreation inputs before PR creation
