---
title: "Runtime Execution Profiles Phase 7 Validation Execution Plan"
created: 2026-07-26
tags: [runtime, execution-policy, validation, e2e, testenv, kubernetes]
---

# Phase Execution Plan

- Phase: `7 — E2E/testenv validation and evidence`
- Branch/base: `feature/runtime-execution-profiles-09-validation` → `feature/runtime-execution-profiles-08-product-ui`
- PR boundary: Deterministic API, Runtime, gateway, resource-model, and Web Surface evidence; the minimal API-managed E2E support required for that evidence; a validation report that records exact commands, environment constraints, results, defects fixed, and a strict Requirements/Design comparison.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, implementation plan, Phases 1 through 6, and `testenv/azents/AGENTS.md`.
- Discovery: `/root/runtime-execution-implementer` completed read-only inventory on 2026-07-26. The existing local E2E fixture uses the Docker Runtime Provider and does not advertise execution-policy authority. The Kubernetes Provider advertises `execution_policy_v1`, `runtime_network_policy`, and `engine_storage_ephemeral`, but the server capability gate is currently `privileged_engine=False`; persistent engine storage is not advertised.

## Deliverables

- A deterministic Public/Admin API E2E suite for Runtime Execution Profile hierarchy, Profile and override selection, availability, explicit Apply, restrictive convergence projection, auditability, and bounded public status.
- A Web Surface E2E suite that verifies server-authoritative configured, pending, applied, unavailable, and divergent rendering without client-side policy inference.
- Focused execution of existing backend/control, gateway, Kubernetes resource-model, and Docker Runtime Provider regression suites.
- A qualified Kubernetes live-E2E scaffold or test only when it consumes a secret-safe prerequisite snapshot and explicitly gates itself on advertised qualified capability.
- A tracked validation report with commands, environment metadata, deterministic results, qualified-live availability/result, failures/fixes, Requirements/Design comparison, and explicit evidence limits.

## Non-goals

- No new policy semantics, Provider capability enablement, generic infrastructure controls, credential handling, or product-surface expansion.
- No direct product database writes, static fixture setup that bypasses Public/Admin APIs, secret capture, bearer-token capture, Kubernetes ServiceAccount-token capture, or Docker request-body capture.
- No claim that build, container-run, Compose, privileged-engine containment, CNI enforcement, persistent engine storage, or Kubernetes credential/socket isolation has been enabled or qualified from a local deterministic run.
- No conversion of unavailable capability into a fallback or weaker Runtime configuration.

## Validation matrix

| Requirement | Deterministic evidence in this phase | Existing supporting evidence | Qualified-live condition/evidence |
| --- | --- | --- | --- |
| REQ-1 hierarchy | Public/Admin API rejects expanding Platform, Workspace, or Agent intent and returns bounded conflict/governing-layer state. | Core resolver and Admin/Public route tests. | Verify a tightening changes actual Runtime topology only on a qualified Provider. |
| REQ-2 profiles and overrides | Profile discovery, Workspace allowance, restrictive Agent override persistence, and unavailable selection behavior through APIs. | Policy service and route tests. | Not required for the policy/API contract. |
| REQ-3 typed modules | Unknown modules, versions, unsupported authority, and raw Provider fields are rejected. | Core resolver tests. | Not required. |
| REQ-4 fail-closed Provider compatibility | A Provider lacking authority-bearing capability leaves the Profile unavailable and cannot apply/provision a weakened Runtime. | Application-service capability tests. | If capability is advertised, verify real provisioning rejects unsupported enforcement. |
| REQ-5 nested-container modules | Verify `privileged_engine=False` prevents positive image-build, container-run, and Compose enablement or presentation. | Gateway per-module authorization and disabled-route suites. | Build-only success; run/Compose denial; Development Profile success only on a qualified cluster. |
| REQ-6 containment | Run deterministic gateway negative and Kubernetes resource-model suites; retain fail-closed unavailable state. | Host/device/namespace/network/resource escape and fixed-topology tests. | CNI egress, socket/token/credential isolation, and resource-exhaustion inspection. |
| REQ-7 storage lifecycle | Assert ephemeral-only capability and persistent unavailability; verify safe public capacity/storage projection. | Stop/restart/reset/delete and workspace-PVC preservation tests. | Engine-state lifecycle plus Workspace preservation; persistent storage only in separately qualified bounded-storage environment. |
| REQ-8 Apply and convergence | Save does not advance Runtime target; Apply creates exactly the next target; pending/applied and restrictive `wait` states are observable. | Application service status/convergence tests. | Runtime replacement, Workspace checksum preservation, and failure fencing. |
| REQ-9 explainability and audit | Assert governing layer/reasons and configured/pending/applied/unavailable/divergent projection; audit is metadata-only and secret-safe. | Admin/Public audit route tests. | Compare Provider evidence metadata with expected digest without collecting secrets. |
| REQ-10 trust boundaries | Run private-socket, state-sink, snapshot-evidence, and unavailable-capability suites. | Gateway private socket and exact evidence tests. | Inspect Pod/container mounts, env, ServiceAccount token absence, sockets, and host-socket denial. |

## Workstreams and ownership

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deterministic API/runtime E2E | `/root/runtime-execution-implementer` | `testenv/azents/e2e/src/tests/azents/public/test_runtime_execution_policy.py`; narrowly required shared E2E helpers | Phases 1–6 API and Runtime contracts | API-managed fixture setup and lifecycle/fail-closed E2E evidence | Focused E2E, then required deterministic E2E lane |
| Web Surface E2E | `/root/runtime-execution-implementer` | `testenv/azents/e2e/src/tests/azents/public/test_runtime_execution_policy_web.py` | Phase 6 product UI | Server-authoritative status/required-action rendering evidence | Focused Web Surface E2E, then Web Surface lane |
| Qualified-live gating | `/root/runtime-execution-implementer` | `testenv/azents/e2e/src/tests/azents/public/test_runtime_execution_policy_kubernetes_live.py`; prerequisite support only if indispensable | Secret-safe qualified Kubernetes snapshot | Explicit skip for unadvertised capability; fail on advertised-but-unenforced capability | Focused live test only when prerequisites exist |
| Evidence/report integration | `/root` | This plan and the Phase 7 validation report | Owner results | Scope verification, evidence recording, independent review, commit, and PR | Plan/diff check and final validation |

## E2E fixture and helper rules

- Create Workspaces, Agents, policies, Profiles, and intent only through existing Admin/Public APIs. Do not seed policy state directly in the product database.
- Reuse `admin_api_client`, `public_api_client`, `system_bootstrap_evidence`, server URL fixtures, `authenticate_user`, `model_selection_from_first_candidate`, and `unique` where suitable.
- Keep any new helpers narrow: Workspace/Agent creation, Standard Profile lookup, expected-version policy replacement, bounded status waiting, and safe-projection field exclusion.
- E2E evidence must not serialize credentials, bearer tokens, ServiceAccount tokens, secret values, Docker request bodies, raw Kubernetes manifests containing sensitive values, socket paths, or Provider implementation-sensitive diagnostics.
- A qualified-live test consumes a prerequisite snapshot; it never invokes prerequisite doctor/setup inside the test. Missing or unadvertised capability is a skip only for that qualified-live coverage. An advertised capability with absent or failed enforcement is a test failure.

## Integration order

1. Add the deterministic API E2E using API-managed Workspace, Agent, Profile, and policy setup.
2. Cover fail-closed Provider compatibility, explicit Apply versus save, restrictive convergence projection, hierarchy/explainability, audit safety, storage availability, and secret-safe response fields.
3. Add Web Surface coverage for server-returned configured/pending/applied/unavailable/divergent and required-action states.
4. Add qualified-live test gating only if it can consume a secret-safe prerequisite snapshot without direct database setup or secret logging.
5. Run focused suites; repair only defects directly exposed by validation and add regression coverage.
6. Run planned deterministic, Web Surface, backend/control, gateway, Kubernetes resource-model, and Docker Runtime Provider regression commands.
7. Record precise results and evidence limits in the validation report. Do not mark Requirements/Design implemented in this phase.

## Planned commands

```bash
cd python/apps/azents
uv run pytest -q \
  src/azents/core/runtime_execution_policy_test.py \
  src/azents/services/runtime_execution_policy/service_test.py \
  src/azents/services/runtime_execution_policy/application_service_test.py \
  src/azents/api/admin/runtime_execution/v1/route_test.py \
  src/azents/api/public/runtime_execution/v1/route_test.py \
  src/azents/api/public/agent_runtime/v1/data_test.py \
  src/azents/repos/runtime_provider_policy/execution_snapshot_test.py \
  src/azents/runtime/control_protocol/grpc/state_sinks_test.py

cd python/apps/azents-container-policy-gateway
uv run pytest -q tests

cd python/apps/azents-runtime-provider-kubernetes
uv run pytest -q tests/test_provider.py tests/test_kubernetes_http.py tests/test_main_settings.py

cd testenv/azents/e2e
uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src
uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src
uv run pytest -vv -m "runtime_provider and not live_external" ./src
```

Run a qualified Kubernetes command only after its fixture/prerequisite snapshot establishes the advertised capability and safe evidence collection. Do not treat a missing local Docker daemon, missing qualified cluster, absent snapshot, or unadvertised `privileged_engine`/persistent storage as an enablement success.

## Independent review

`/root/runtime-execution-reviewer` performs a read-only review focused only on Requirements/Design mismatch; accidental direct database setup; capability advertisement or fallback errors; Apply/convergence/reset semantics; test secret leakage; unbounded test evidence; UI lifecycle inference; false qualified-live claims; and material convention violations. Batch required findings once; request targeted re-review only for high-risk corrections.

## Final validation and scope-drift check

- Run affected focused tests before broader planned lanes.
- Run deterministic E2E, Web Surface E2E, and Docker Runtime Provider regression separately; report unavailable prerequisites rather than masking them.
- Run backend/control, gateway, and Kubernetes resource-model evidence suites.
- Run formatting/lint/type checks required by each changed project, `git diff --check`, and pre-commit on commit.
- Compare the complete diff against `feature/runtime-execution-profiles-08-product-ui`. Reject new product behavior, raw Kubernetes/Provider controls, direct database setup, capability enablement, credentials/secrets in evidence, generic privileged controls, production resource mutation, unrelated refactors, or claims that qualified Kubernetes enforcement passed without actual qualified-live evidence.
- Do not monitor CI until every PR in the 11-PR stack exists.
