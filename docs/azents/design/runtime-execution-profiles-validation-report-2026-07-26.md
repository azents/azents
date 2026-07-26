---
title: "Runtime Execution Profiles Phase 7 Validation Report"
created: 2026-07-26
tags: [runtime, execution-policy, validation, e2e, testenv, kubernetes, security]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: runtime-260726
migration_source: "docs/azents/design/runtime-260726-hierarchical-execution-profiles.md"
---

# Runtime Execution Profiles — Phase 7 Validation Report

## Scope and evidence policy

This report records Phase 7 validation for [`runtime-260726/REQ`](../requirements/runtime-260726-hierarchical-execution-profiles.md) through the Phase 7 execution plan. It covers the stack through Phase 6 and does not mark the Requirements or Design implemented, promote living specs, enable additional Provider capability, or claim qualified Kubernetes enforcement.

Evidence is classified as follows:

- **Executed** — command ran in this worktree and reached its test assertions.
- **Static/collection** — format, lint, type, collection, or source-level evidence that did not execute a Docker-backed product journey.
- **Unavailable** — an attempted command was blocked by a documented prerequisite before product assertions; it is not classified as a product assertion failure.
- **Not attempted** — deliberately withheld because a required qualification contract was absent. It is not evidence of enablement.

All new E2E state setup uses supported Admin/Public APIs. It performs no direct product database writes. Response safety checks reject credential-, token-, authorization-, socket-, manifest-, Provider-config-, ServiceAccount-, and Workspace-path-bearing keys, and reject both the request bearer token and deterministic LLM credential sentinel before assertions can render a response value. Unexpected HTTP-status errors retain only method, URL path without query, and observed/expected status codes.

## Environment and capability boundary

- Worktree: `/workspace/agent/.azents/worktrees/lucky-social-fat/azents`
- Validation branch: `feature/runtime-execution-profiles-09-validation`
- Implementation base: `feature/runtime-execution-profiles-08-product-ui`
- Date: 2026-07-26
- Local Docker prerequisite: **unavailable**. `test -S /var/run/docker.sock` exited `1`; Testcontainers failed creating `container_network()` with `docker.errors.DockerException` caused by `FileNotFoundError(2, "No such file or directory")`.
- Docker Runtime Provider capability does not establish execution-policy authority in this fixture.
- Current server capability gate remains `privileged_engine=False`; the bounded safe projection exposes `image_build=false`, `container_run=false`, `compose=false`, `storage_modes=["none"]`, and `network_modes=["none"]`.
- Persistent engine storage remains unavailable. No local or live evidence enables it.
- No qualified Kubernetes prerequisite snapshot was available. The existing snapshot schema cannot distinguish an unadvertised capability from an advertised-but-unenforced privileged-engine, CNI, isolation, or storage capability. A qualified-live E2E was therefore **not attempted** rather than made skip-permissive.
- CI was intentionally not inspected or monitored in this phase. The delivery rule is to create all 11 stacked PRs before monitoring CI.

## Changes validated

Phase 7 adds the following E2E evidence surfaces:

- `testenv/azents/e2e/src/support/runtime_execution_policy.py` — narrow API-managed Workspace, LLM integration, and Agent setup using the logical Docker Provider ID; no direct database access.
- `testenv/azents/e2e/src/tests/azents/public/test_runtime_execution_policy.py` — capability fail-closed behavior, typed policy rejection, Profile allowance, hierarchy reduction/expansion rejection, explicit Apply, applied/configured/pending projection, idempotent Apply, automatic restrictive convergence, audit metadata, and secret-safe public projection checks.
- `testenv/azents/e2e/src/tests/azents/public/test_runtime_execution_policy_web.py` — an actual server-backed `Configured` / `Apply configured policy` Web rendering, plus bounded server-shaped presentation coverage for pending, applied, unavailable, and divergent statuses without client-side digest or Provider inference.

The Runtime Provider E2E starts with the Workspace restriction and Profile allowance already configured. It then performs exactly one intended Workspace tightening from CPU `1000` to `250` after an applied target. Without a second Agent Apply it checks a new target generation, `pending/wait`, an effective Workspace-governed CPU ceiling, same Runtime ID, `restart` lifecycle command, null reset final state, distinct target digest, and `automatic_restriction` audit evidence. It does not claim Workspace checksum preservation because that needs qualified live Runtime evidence.

## Commands and results

| Command | Result | Evidence |
| --- | --- | --- |
| `cd python/apps/azents && uv run pytest -q src/azents/core/runtime_execution_policy_test.py src/azents/services/runtime_execution_policy/service_test.py src/azents/services/runtime_execution_policy/application_service_test.py src/azents/api/admin/runtime_execution/v1/route_test.py src/azents/api/public/runtime_execution/v1/route_test.py src/azents/api/public/agent_runtime/v1/data_test.py src/azents/repos/runtime_provider_policy/execution_snapshot_test.py src/azents/runtime/control_protocol/grpc/state_sinks_test.py` | PASS | Executed locally: `65 passed, 9 skipped` |
| `cd python/apps/azents-container-policy-gateway && uv run pytest -q tests` | PASS | Executed locally: `136 passed` |
| `cd python/apps/azents-runtime-provider-kubernetes && uv run pytest -q tests/test_provider.py tests/test_kubernetes_http.py tests/test_main_settings.py` | PASS | Executed locally: `64 passed` |
| `cd testenv/azents/e2e && uv run ruff format --check` / focused Ruff check | PASS | Static/local final handoff: formatted and lint clean |
| `cd testenv/azents/e2e && uv run pyright` for new helper and E2E modules | PASS | Static/local final handoff: `0 errors, 0 warnings` |
| `cd testenv/azents/e2e && uv run pytest --collect-only -q src/tests/azents/public/test_runtime_execution_policy.py src/tests/azents/public/test_runtime_execution_policy_web.py` | PASS | Static/collection: 3 tests collected |
| `cd testenv/azents/e2e && uv run pytest -vv src/tests/azents/public/test_runtime_execution_policy.py src/tests/azents/public/test_runtime_execution_policy_web.py` | UNAVAILABLE | Attempted locally; all 3 tests stopped in common Docker network fixture before product assertions because `/var/run/docker.sock` is absent |
| `git diff --check` | PASS | No whitespace errors after final corrections |

The direct E2E attempt yielded three fixture errors, not failed product assertions: `test_capability_gate_and_typed_policy_fail_closed`, `test_hierarchy_profile_override_apply_status_and_audit`, and `test_agent_runtime_execution_renders_server_status_and_required_action` each stopped before their bodies when Testcontainers initialized the missing Docker socket.

## Requirement-to-validation matrix

| Requirement | Phase 7 evidence | Status and limitation |
| --- | --- | --- |
| REQ-1 — hierarchical authority | API E2E models Workspace CPU restriction, Agent tightening, expansion rejection with Workspace governing layer, and later automatic Workspace tightening. Core/service/route suite passed. | E2E assertions are present and collected; Docker-backed execution unavailable locally. |
| REQ-2 — named Profiles and restrictive overrides | API E2E creates Profile, verifies Workspace disallow/allow, persists an Agent override, and rejects expansion. | E2E collected; backend supporting suite passed. |
| REQ-3 — typed extensible customization | API E2E submits an unknown raw Provider field and requires validation rejection. | E2E collected; no raw Kubernetes manifest acceptance is introduced. |
| REQ-4 — fail-closed compatibility | API E2E requires unavailable authority-bearing Profile creation to return `provider_engine_unsupported`; bounded capability projection remains disabled. | E2E collected; no positive privileged-engine claim. |
| REQ-5 — nested modules | Gateway suite passed; E2E asserts all authority-bearing modules are disabled by current capability gate. | Positive build/run/Compose evidence is unavailable and not claimed. |
| REQ-6 — containment | Gateway negative suite and Kubernetes resource-model suite passed. | CNI, Pod filesystem, socket, credential, and token live inspection require qualified Kubernetes evidence and remain unverified. |
| REQ-7 — storage lifecycle | Kubernetes resource-model suite passed; safe status projection asserts `none` storage/network. | Persistent engine storage remains unavailable; live engine-state and Workspace preservation evidence is not claimed. |
| REQ-8 — explicit Apply and safe convergence | Runtime Provider E2E contains save-without-generation-advance, Apply, idempotency, automatic restriction convergence without Agent Apply, same Runtime ID, restart, and no-reset observable evidence. Supporting backend/control suite passed. | Docker-backed E2E body did not execute locally. |
| REQ-9 — explainability and audit | E2E checks governing layer, configured/pending/applied status, action projection, automatic-restriction audit metadata, and secret-safe response shape. | E2E collected; backend route/service evidence passed. |
| REQ-10 — trust boundaries | Gateway private-boundary/security suite, control state-sink suite, and safe-projection checks passed. | Qualified live Pod mount/environment/ServiceAccount/socket inspection remains unavailable. |

## Review findings and corrections

Independent review by `/root/runtime-execution-reviewer` identified and the implementation corrected:

1. missing automatic restrictive-convergence and no-reset Runtime evidence;
2. Web coverage that initially relied entirely on browser-synthetic status values;
3. error/projection paths that could have rendered a sensitive response value;
4. an already-applied snapshot assertion that made the convergence path unreachable; and
5. a precondition race where initial Workspace restriction could itself trigger convergence.

The final targeted re-review found **no remaining Blocker, P1, or P2**. It confirmed response safety checks run before assertion-rendering paths and the initial Workspace restriction is configured before Runtime start so the later `1000 → 250` change is the only intended automatic convergence event.

## Strict implementation versus current living specs

The current living specs were read for comparison only. This validation phase does not modify them, the Requirements, the accepted ADR, or the primary Design.

The implementation is consistent with the approved fail-closed direction: Provider-neutral typed policy is represented through the API and UI, unavailable authority is not silently weakened, Apply remains separate from save, restrictive policy changes converge without reset, and safe projections omit Provider credentials/topology. Current living specs still need Phase 8 promotion for Runtime Provider, Agent, Workspace, persistence, Runtime Control, and E2E behavior. This omission is intentional stack sequencing, not a reason to claim implementation verification or qualified Kubernetes enablement.

## Residual blockers and evidence limits

1. **Local Docker substrate unavailable:** required deterministic, Runtime Provider, and Web Surface E2E commands cannot create Testcontainers network fixtures without `/var/run/docker.sock`.
2. **Qualified Kubernetes evidence unavailable:** no secret-safe prerequisite snapshot can represent advertised privileged-engine/CNI/isolation/storage qualification and distinguish it from unadvertised capability. No live Kubernetes test is therefore treated as skipped success.
3. **Persistent engine storage unavailable:** `home` and the current local environment have no qualified bounded persistent engine-storage evidence; it remains unadvertised.
4. **CI deliberately deferred:** full stack CI must be inspected only after PRs 9–11 exist, per delivery sequencing.

## Conclusion

Phase 7 adds E2E-first validation coverage for Runtime Execution Profiles and executes the planned backend/control, gateway, and Kubernetes resource-model suites successfully. The final new E2E modules pass format, lint, type, collection, diff, and independent review checks. Their Docker-backed execution is unavailable in this worktree before product assertions due to the absent Docker socket. Qualified Kubernetes enforcement, privileged-engine enablement, persistent engine storage, and live containment evidence remain explicitly unavailable and unadvertised; none is represented as a passing result. Phase 8 spec promotion and Phase 9 cleanup remain pending after the complete stack and its CI evidence are available.
