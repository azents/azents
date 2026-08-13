---
title: "Hierarchical Runtime Network Restriction Phase 7 Validation Plan"
created: 2026-08-12
updated: 2026-08-13
tags: [runtime, network, security, kubernetes, testenv, validation, documentation]
---

# Hierarchical Runtime Network Restriction Phase 7 Validation Plan

## Phase Execution Plan

- Phase: `7 — Validation, Specs, and implementation record`
- Branch/base: `feature/network-restriction-7-validation` → rebased Phase 6 commit `edbe193cd`
- PR boundary: Validate the approved hierarchical Runtime network restriction implementation through deterministic API/control-plane E2E and focused Kubernetes Provider/proxy tests, promote current behavior into Living Specs, and record implementation only after the retained validation scope succeeds.
- Inputs: Phase 1–6 implementation through PR #1274; confirmed [`network-260812/REQ`](../requirements/network-260812-hierarchical-runtime-network-restriction.md), accepted [`network-260812/ADR`](../adr/network-260812-hierarchical-runtime-network-restriction.md), approved [`network-260812/DESIGN`](../design/network-260812-hierarchical-runtime-network-restriction.md) revision 2, and the tracked [multi-phase implementation plan](network-260812-hierarchical-runtime-network-restriction-implementation-plan.md).
- Deliverables: Credential-free deterministic API/control-plane coverage explicitly labeled as non-packet evidence; Kubernetes Provider/proxy unit, manifest, protocol, lifecycle, trust, and forwarding tests; an M1–M15 authority/removal/security/lifecycle/migration/rollout/rollback audit; updated Runtime Provider, Runtime Control, Runtime Persistence, Workspace, and E2E Living Specs; matching `implemented: 2026-08-13` frontmatter on Requirements and Design only after the retained checks and independent review succeed.
- Non-goals: A Kubernetes test cluster, live Kubernetes resource creation, kind or Calico, packet probes, a dedicated qualification workflow, prerequisite snapshots, qualification artifacts, new product mechanisms, new capability authority, direct database state creation, Docker strict-mode claims, legacy v1/v2 convergence or deletion, Phase 8 plan cleanup, deployment rollout, PR merge, or any weakening/fallback behavior.
- Interfaces: Kubernetes Profile v3 and Workspace Policy v2 contracts; server-owned hierarchy composition; Kubernetes Provider protocol v3 aggregate `network_enforcement`; existing desired/applied sequence, digest, Provider generation, desired generation, and Runner evidence; operator-owned capability attestations; Admin/Public API-created product state; a bounded fake Provider protocol participant for control-plane E2E.
- Approved Design mechanisms: `M15` as the phase mechanism, with complete validation of `M1` through `M15`.
- Authority references: `network-260812/REQ-1` through `REQ-12`; `network-260812/ADR-D1` through `ADR-D8`; `network-260812/DESIGN` revision 2 Test Strategy, Design Authority, Removal and Replacement, Security and Permissions, Persistence/Migration/Rollout/Rollback, and Failure/Retry/Recovery; current Runtime Provider, Agent Runtime Control, Agent Runtime Persistence, Workspace, and E2E Primary Test Strategy Specs; repository no-direct-DB-write constraints.
- Design delta: `None`
- Removal obligations: Remove the Phase 7 live qualification workflow, prerequisite contract, packet-probe support, conformance driver, and all delivery claims derived from them. Audit all earlier Design removal rows and preserve the explicit retained authority of legacy v1/v2 contracts, the MCP egress proxy, and Workspace PVC lifecycle.
- Absence verification: Static searches and focused tests prove no Kubernetes v2 `network_policy` fallback can serve a v3 strict contract, no strict Runtime DNS/direct-customer-egress fallback is represented by current Provider builders, no Phase 7 live qualification file or claim remains, no test result becomes capability authority, no direct DB writes create E2E state, no Phase 8 plan deletion is included, and every Design removal row has replacement or retained-authority evidence.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and validation record | `/root` | this file | Approved snapshot and Phase 6 head | Current scope, commands, results, failures, fixes, audit, and checkpoint | Frontmatter validation, `git diff --check`, plan completeness review |
| Deterministic control-plane journey | `/root` | `testenv/azents/e2e/src/tests/azents/public/**`, `testenv/azents/e2e/src/support/**`, focused E2E configuration | Phase 6 generated clients and server APIs | API-created v3/Policy-v2 hierarchy, compatibility, desired/applied projection, and bounded fake-Provider evidence labeled control-plane-only | E2E Ruff/format/type/unit checks and deterministic E2E selector |
| Kubernetes Provider/proxy validation | `/root` | `python/apps/azents-runtime-provider-kubernetes/**`, `python/apps/azents-runtime-proxy/**` | Phase 3–4 resources/lifecycle and Phase 7 corrections | Exact manifests, ownership, comparison, cleanup, protocol evidence, trust/authority, and selected-IP forwarding | Package Ruff/format/type/pytest suites; no live cluster |
| Living Specs and implementation audit | `/root` | Runtime Provider, Runtime Control, Runtime Persistence, Workspace, and E2E Specs; Requirements/Design frontmatter | Stable code and retained validation results | Current v3 hierarchy, strict network lifecycle/evidence, product projection, test-policy boundary, M1–M15 and removal traceability | `/spec-review`, document validation, targeted searches, `git diff --check` |
| Independent review | `/root/network-260812-reviewer` | Read-only across the complete Phase 7 diff and evidence | Stable implementation and validation outputs | Findings covering authority, validation separation, security, lifecycle/storage, Spec accuracy, removal obligations, and scope drift | Grounded findings resolved; targeted re-review only for material corrections |

- Integration order: Remove rejected qualification scope; correct Design, plan, and Living Specs; run focused retained checks; audit M1–M15 and removal obligations; obtain independent review; apply grounded corrections; rerun affected and final validation; set matching implementation dates; commit; create the stacked Phase 7 PR.
- Independent review: `/root/network-260812-reviewer` reviews against confirmed Requirements, accepted ADR, approved Design revision 2 and M1–M15 authority, this phase contract, current Specs, stable diff, and retained deterministic evidence. The reviewer must reject any control-plane or unit result presented as live packet evidence.
- Final validation: `cd python/apps/azents-runtime-provider-kubernetes && uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -q`; equivalent checks in `python/apps/azents-runtime-proxy`; E2E Ruff/format/type/unit tests plus `uv run pytest -q -m "not live_external and not runtime_provider and not web_surface" ./src/tests`; affected backend/Runner/Helm checks identified by the audit; documentation validation; `git diff --check`.
- Scope-drift check: Verify every M1–M15 behavior and removal row has evidence; reject new product state, capability source, enforcement mode, fallback, compatibility path, resource owner, lifecycle boundary, failure contract, or secret-bearing artifact absent from Design Authority; retain v1/v2 and Policy-v1 compatibility; exclude Phase 8 cleanup and live infrastructure mutation.
- Context checkpoint: Phase 1–6 were rebased onto `main` commit `180720c47`. Phase 7 initially contained a dedicated live Kubernetes qualification lane, which the requester explicitly rejected. Those workflow, prerequisite, probe, conformance, and artifact changes and claims are superseded and are not delivery evidence. The retained scope is deterministic API/control-plane E2E plus focused Kubernetes Provider/proxy tests.

## Validation Evidence Record

This section is updated during execution. Test results are validation evidence, never capability authority.

### Retained deterministic validation

- Status: `passed`
- Environment: current worktree; Docker-backed credential-free E2E fixture; no Kubernetes cluster, Kubernetes credentials, or live resource creation.
- Required evidence classification: API E2E is `control-plane only`; Provider/proxy suites are unit, manifest, protocol, lifecycle, trust, and forwarding evidence; neither is packet-enforcement evidence.
- Superseded evidence: every earlier kind/Calico, live Kubernetes resource, packet-probe, prerequisite, qualification artifact, JUnit, hash, or resource-role result is discarded and must not be cited for delivery.
- Commands and results:
  - Kubernetes Provider: Ruff, format check, `ty`, and full pytest passed with `173 passed`.
  - Runtime proxy: Ruff, format check, `ty`, and full pytest passed with `24 passed`.
  - Runtime Control library: Ruff, format check, `ty`, and full pytest passed with `122 passed`.
  - Runtime Runner: Ruff, format check, `ty`, and full pytest passed with `169 passed`.
  - Backend hierarchy, Provider admission/evidence, desired/applied, and API projection focused suite passed with `112 passed`.
  - Rebased migration-head and topology regression suite passed with `3 passed`.
  - E2E Ruff, format check, `ty`, and unit tests passed with `51 passed`.
  - Deterministic API E2E selector passed with `294 passed, 6 skipped, 31 deselected` in `756.32s`.
  - E2E lock consistency and `git diff --check` passed.
  - Helm Provider render tests collected but all `24` were skipped because the local environment has no `helm` binary. This is unavailable local evidence, not a pass; the required PR check remains responsible for executing the render suite.

### Failures found and retained corrections

- Proxy selected-IP forwarding: mitmproxy derives the actual upstream destination from the request host. The addon retains authorization of the original authority, dials the selected authorized IP, preserves HTTP Host/CONNECT authority and verified-hostname TLS SNI, and performs pre-connect and post-connect IP authorization. This correction remains covered by focused proxy tests.
- Kubernetes Provider resource comparison and lifecycle corrections discovered during validation remain in scope when they are deterministic implementation fixes covered by Provider unit/manifest/lifecycle tests.
- Runner public trust and Provider manifest corrections remain in scope where their behavior is covered by deterministic package tests and existing Phase 1–6 authority.
- The E2E project directly imports the production `azents-runtime-control` contract. That package requires `protobuf>=7.35.1`, while the prior E2E `temporalio==1.21.1` dependency required `protobuf<7`; the resolved Temporal/Nexus lock update is therefore a required test-environment compatibility change rather than an unrelated package upgrade.

## M1–M15 and Removal Audit Record

- Status: `complete`
- Authority coverage:
  - `M1` and `M2`: Profile v3 and Policy v2 parsing, canonical hierarchy, legacy pairing, and expansion rejection are covered by backend core/service tests; API E2E creates and resolves both supported strict Workspace modes through Admin/Public APIs.
  - `M3`, `M6`, and `M7`: exact direct, proxy-only, and Platform-only policies, strict DNS/host aliases, typed owned resources, comparison, and cleanup are covered by Kubernetes Provider manifest and lifecycle tests.
  - `M4` and `M14`: proxy authority, redirect checks, selected-IP forwarding, Host/CONNECT preservation, hostname SNI, pre/post-connect IP authorization, protocol denial, and redacted logging are covered by the proxy suite.
  - `M5`: logical-Runtime CA separation, public-only Runtime mount, bounded writable trust workspace, and Runner trust bootstrap are covered by Provider and Runner tests.
  - `M8`: independent operator attestations and bounded warning diagnostics remain capability inputs and observations respectively; neither tests nor warnings become capability authority.
  - `M9` and `M10`: Runtime Control separates retained protocol-v2 legacy `network_policy` admission from protocol-v3 aggregate `network_enforcement`; incomplete/drifted v3 rejection, exact `in_sync` acknowledgement, repair fencing, and desired/applied promotion are covered by Runtime Control, backend, Provider, and API E2E tests.
  - `M11`: backend impact classification and Provider lifecycle tests cover CIDR/proxy-owned in-place changes, recreation-required mode/trust/hosts changes, and narrow-first replacement.
  - `M12`: Provider and Runner lifecycle tests preserve Workspace PVC/data outside reset and terminal delete.
  - `M13`: backend/API tests and the API E2E verify effective mode, compatibility, desired/applied, and bounded status projection without Kubernetes resource or private CA fields.
  - `M15`: E2E unit contracts and the API-created deterministic journey are explicitly control-plane-only; Provider/proxy unit, manifest, protocol, lifecycle, trust, and forwarding tests independently validate Kubernetes behavior without a live cluster or packet claim.
- Reverse Design Authority: every Phase 7 product-code correction maps to existing `M4`, `M5`, `M7`, or `M11`; no new product state, mode, fallback, capability source, resource owner, lifecycle boundary, or failure contract was added.
- Removal verification: the Phase 7 diff contains no dedicated qualification workflow, Kubernetes prerequisite contract, packet probe/target/Runner-control support, live conformance driver, qualification unit test, artifact schema/hash, or live resource-role evidence claim. Testenv prerequisite files have no Phase 7 diff.
- Protocol compatibility verification: promoted Specs and current protocol tests require Kubernetes v3 aggregate `network_enforcement` for v3 strict contracts. Profile v1/v2 and Provider protocol v2 remain legacy direct compatibility paths using `network_policy`; protocol v1 is not admitted, and v2 cannot act as a strict-contract fallback.
- Security verification: E2E creates product state through Admin/Public APIs, adds no feature-state DB write, and exposes only bounded control-plane evidence. The evidence model forbids packet, endpoint, credential, kubeconfig, and CA fields.
- Lifecycle verification: deterministic tests cover exact Runtime-owned cleanup, stable proxy Service/logical CA retention where required, API-defaulted Pod reuse, and Workspace PVC preservation outside reset and terminal delete.
- Migration/rollout/rollback verification: legacy documents remain readable with direct semantics, unsupported strict modes fail closed, Kubernetes protocol v3 is the coordinated strict-contract path while protocol v2 remains legacy direct-only, Docker remains direct-only, and no implicit fallback or recreation was added.
- Retained authority: the MCP egress proxy and Workspace PVC lifecycle remain independently governed and are not replaced by this feature.

## Phase Checkpoint

- Completed: latest `main` pull; Phase 1–6 stack rebase; Phase 7 working-tree restoration; rejected qualification files and prerequisite extensions removed; Design, plans, Helm guidance, and Living Specs corrected; fresh retained checks and the M1–M15/removal audit completed; `/spec-review` and independent Phase 7 review findings corrected and re-reviewed; matching `implemented: 2026-08-13` frontmatter recorded.
- Remaining: final documentation/pre-commit validation; commit; update rebased stack branches; create Phase 7 PR.
- Risks/blockers: local Helm render evidence is unavailable because the `helm` binary is absent. This does not block useful local work and must be verified by the required PR check. External CI remains pending until the complete PR stack is created.
