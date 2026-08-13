---
title: "Hierarchical Runtime Network Restriction Phase 4 Provider Lifecycle Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, kubernetes, lifecycle]
---

# Phase Execution Plan

- Phase: `4/8 — Provider lifecycle and enforcement`
- Branch/base: `feature/network-restriction-4-provider-lifecycle` →
  `feature/network-restriction-3-provider-resources` at `7630cbf1e`
- PR boundary: Activate the complete mode-aware Kubernetes Runtime network
  enforcement lifecycle from the Phase 3 resource primitives, switch the Provider
  to protocol-v3 aggregate evidence, and remove the actionable protocol-v2
  `network_policy` reconciliation path without adding Helm attestations or product
  projections.
- Inputs: Completed Phase 1 canonical Profile v3 `network_access` contracts and
  application-impact classification; completed Phase 2 protocol-v3
  `network_enforcement` evidence, admission, repair fencing, and diagnostics
  contracts; completed Phase 3 typed Service/ConfigMap/Secret/selected-volume,
  strict DNS/hosts, owned-resource, persistent CA, proxy-policy, proxy image/addon,
  and Runner public-trust primitives; current Pod/PVC lifecycle and Runtime Control
  command fencing.
- Deliverables: Typed Runtime Control parsing for Kubernetes Pod Profile v3 direct,
  proxy-required, and no-network inputs; explicit mandatory Platform Service
  references and validated Service observations; complete direct, proxy-only,
  Platform-only, proxy-ingress, and proxy-egress NetworkPolicies; strict Runtime DNS
  and exact host mappings; persistent CA creation/validation; canonical proxy policy
  ConfigMap, stable Service, proxy Pod, readiness fencing, and public/private mount
  separation; mode-aware start, observe, update, restart, stop, reset, recovery, and
  terminal deletion; narrow-first transitions; in-place proxy-policy/artifact/CIDR
  repair with bounded recreation-required outcomes; complete owned-resource
  reconciliation and aggregate `network_enforcement` evidence; Provider protocol-v3
  registration; focused Runtime Control, Kubernetes API, Provider, Pod/Runner-input,
  lifecycle, recovery, and removal tests.
- Non-goals: Helm values, default-disabled strict capability attestations, workload
  or mandatory-Service RBAC, chart-owned namespace default deny, periodic deployment
  diagnostics, Admin/Public API projections, OpenAPI/generated clients, web
  surfaces, testenv/live packet enforcement, Living Spec promotion, automatic CA
  rotation, management UI, a DNS controller, CRD, second reconciler, Runtime Control
  Kubernetes client, direct fallback, or live infrastructure changes. Phase 4 does
  not change Runner trust implementation; it verifies the Provider supplies the
  Phase 3 fixed public-CA and proxy environment contract. Legacy Profile v1/v2
  direct behavior remains readable and enforceable.
- Interfaces: `azents-runtime-control.runtime_configuration` owns the exact typed
  Kubernetes Profile v3 parser and exposes a closed direct/proxy-required/no-network
  union; v1/v2 remain unchanged. Provider deployment configuration supplies
  immutable proxy image/addon artifact identity, proxy port, and explicit mandatory
  Service references containing namespace, name, endpoint hostnames, and authorized
  ports; runtime configuration cannot select these values. Mandatory Services must
  be non-headless, non-`ExternalName`, and have a stable ClusterIP, and command
  Runtime Control/transfer endpoint hostnames must be covered by the configured
  references. Strict Runtime Pods use `dnsPolicy: None`, the Phase 3 non-listening
  resolver configuration, and only observed mandatory Service plus own-proxy
  `hostAliases`; direct mode retains cluster DNS. Runtime Pods mount only the public
  CA key and receive the fixed Runner trust path plus matching HTTP(S) proxy
  variables in proxy-required mode. Proxy Pods mount only combined private CA
  material and canonical policy content, and exact readiness requires Pod Ready plus
  matching configuration sequence, policy digest, CA fingerprint, and artifact
  digest metadata. Complete policies select exact owned roles: direct Runtime allows
  Platform paths, DNS, and effective direct CIDRs; proxy-required Runtime allows
  Platform paths and its own proxy port only; no-network Runtime allows Platform
  paths only; proxy ingress allows only its matching Runtime; proxy egress allows DNS
  and inherited effective destination CIDRs. Reconciliation emits exactly one
  `network_enforcement` observation whose first bounded reason identifies a safe
  repair class and whose diagnostics contain only safe counts, roles, and digests.
  `UPDATE_CONFIGURATION` may update direct/proxy egress CIDRs, replace proxy
  ConfigMap/Pod for policy or immutable artifact changes, and remove obsolete owned
  policy ConfigMaps only after replacement readiness. Runtime Pod shape, mode,
  trust, strict DNS, hosts, PVC, scheduling, DinD, or mandatory Service mapping drift
  returns `network_recreation_required`. Lifecycle commands never advance generation
  autonomously.
- Approved Design mechanisms: `M3`, `M7`, `M10`, `M11`, `M12`
- Authority references: `network-260812/REQ-2`, `REQ-3`, `REQ-5`, `REQ-6`,
  `REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`; `network-260812/ADR-D3`, `ADR-D4`,
  `ADR-D5`, `ADR-D6`, `ADR-D8`; approved Design Kubernetes Resource Ownership,
  Interception CA and Runtime Trust, Proxy Workload and Policy Enforcement, DNS,
  Mandatory Services and NetworkPolicy, Desired/Applied/Reconciliation Evidence,
  Application Impact and Lifecycle, Security, and Test Strategy sections; current
  Runtime Provider, Runtime Control, and Agent Runtime Persistence Specs.
- Design delta: `None`
- Removal obligations: Replace Runtime DNS rules in strict modes with strict DNS and
  mandatory host mappings. Replace direct customer egress in proxy/no-network modes
  with proxy-only or Platform-only complete Runtime policies. Replace
  NetworkPolicy-only Provider updates with mode-aware bounded enforcement-bundle
  repair. Replace the narrow protocol-v2 actionable `network_policy` observation
  with protocol-v3 aggregate `network_enforcement`. Retain legacy v1/v2 Profile
  `network_policy` parsing only as direct configuration authority, not as an active
  reconciliation kind. Preserve Workspace PVC except at existing reset and terminal
  delete boundaries.
- Absence verification: Static searches and Runtime Control/Provider tests find no
  Provider registration, report, reconciliation, repair reason, or lifecycle result
  that emits actionable `network_policy`; only legacy v1/v2 configuration parsing
  and Kubernetes object terminology remain. Strict Pod manifest equality proves no
  DNS egress rule, default DNS policy, proxy/trust input in no-network, or direct
  customer CIDR egress in proxy/no-network modes. Policy equality proves no
  cross-Runtime or additive fallback. Lifecycle deletion tests prove stop and
  ordinary replacement retain PVC and CA, reset alone destroys/recreates PVC, and
  terminal deletion removes the exact complete owned set including PVC and CA.
  Ownership-filtered recovery and deletion tests prove no name-only or foreign
  resource adoption. Update tests prove recreation-required inputs are never
  repaired in place and narrow-first mode transitions never retain broader direct
  authority.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime configuration v3 consumption | `/root` | `python/libs/azents-runtime-control/src/azents_runtime_control/runtime_configuration.py`, `python/libs/azents-runtime-control/tests/runtime_configuration_test.py` | Phase 1 canonical JSON shape | closed typed Profile v3 network-access models and exact parser while retaining v1/v2 | focused parser/canonical/unknown-field tests, Ruff, format, ty, pytest |
| Enforcement bundle model and builders | `/root` | new focused modules under `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/`, `owned_resources.py`, focused new tests | Phase 3 owned resources, CA, proxy policy, typed Kubernetes models | mode-aware desired bundle, mandatory Service observations, complete policies, Runtime/proxy Pod inputs, safe comparison and first-drift classification | manifest equality, ownership, strict DNS/hosts, public/private mounts, policy and redaction vectors |
| Kubernetes API reconciliation support | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/kubernetes_api.py`, `kubernetes_http.py`, `tests/test_kubernetes_http.py` | desired bundle and recovery/deletion needs | exact list/read/apply/delete support required for owned NetworkPolicy recovery and bounded Service observation without raw payloads | HTTP request/response round trips, selectors, parser/manifests, foreign-resource rejection |
| Provider lifecycle integration | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/provider.py`, focused Provider modules, `tests/test_provider.py`, focused new lifecycle tests | typed v3 input and enforcement builders | mode-aware create/observe/update/restart/stop/reset/recovery/delete, proxy-before-Runtime readiness, narrow-first transitions, PVC/CA matrix, aggregate evidence | direct/proxy/no-network lifecycle matrices, idempotency, drift/repair, recreation-required, readiness, recovery, deletion tests |
| Provider process contract | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/main.py`, `tests/test_main_settings.py` | lifecycle configuration inputs and Phase 2 protocol v3 | protocol-v3 registration, schema v3 capability contract, immutable proxy settings, explicit mandatory Service references, no premature Helm attestation authority | settings validation, registration/capability snapshots, v2 actionable absence search |
| Runner-input integration | `/root` | Provider Pod builders and tests; `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`, focused proxy-environment helper and tests | Phase 3 fixed Runner trust contract | exact public-CA path plus Provider-only proxy input projected to standard proxy variables for child operations without changing Runner Control/transfer process networking; absence in direct/no-network | Provider manifest tests, Runner child-environment tests, existing trust tests |
| Helm integration boundary | `/root` | `infra/charts/azents/**` read-only; Phase 5 owns changes | final Provider environment/RBAC requirements | recorded exact Phase 5 inputs without chart edits or enabled strict attestations | static diff confirms no Helm changes; settings tests enumerate required future inputs |
| Documentation | `/root` | this phase plan and active implementation plan only | approved Design revision 1 | tracked Phase 4 execution scope and completion checkpoint | documentation hooks and `git diff --check` |
| Independent review | `/root/network-260812-reviewer` | read-only Phase 4 diff | stable implementation and focused evidence | authority, fail-closed enforcement, lifecycle, ownership, reconciliation, removal, persistence, and scope report | written review findings |

- Integration order: Runtime Control typed Profile v3 parsing → mandatory Service and
  deployment input types → mode-aware desired enforcement bundle and complete policy
  builders → Kubernetes list/observation support → Runtime/proxy Pod and resource
  builders → aggregate comparison/reconciliation → start/observe/recovery lifecycle →
  in-place repair and narrow-first transition behavior → stop/reset/terminal deletion
  matrix → protocol-v3 registration and removal search → focused validation →
  independent review → required corrections → final validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against the
  confirmed Requirements, ADR-D3/D4/D5/D6/D8, approved Design
  `M3`/`M7`/`M10`/`M11`/`M12`, current Specs, this plan, focused evidence, and the
  stable Phase 4 diff. It reports only material findings concerning complete policy
  authority, DNS or direct-egress bypass, mandatory Service trust, ownership and
  foreign-resource adoption, CA/private-key exposure, proxy readiness ordering,
  narrow-first transitions, in-place versus recreation boundaries, PVC/CA lifecycle,
  aggregate evidence truth, actionable-v2 removal, bounded diagnostics, and scope
  drift.
- Final validation: In `python/libs/azents-runtime-control` and
  `python/apps/azents-runtime-provider-kubernetes`, run `uv sync --frozen`,
  `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run ty check --error-on-warning`, and `uv run pytest -vv`; run focused existing
  Runner trust tests only if Provider mount/environment contracts require regression
  confirmation while keeping Runner source unchanged; run direct, proxy-required,
  no-network, transition, in-place repair, recreation-required, recovery, stop,
  restart, reset-running, reset-stopped, and terminal-delete matrices; run exact
  Kubernetes HTTP round trips; run static authority/removal searches; validate
  documentation hooks and `git diff --check`. Docker builds and qualified packet
  enforcement remain Phase 7 evidence unless a Provider image dependency changes.
- Scope-drift check: Confirm complete M3/M7/M10/M11/M12 coverage and all Phase 4
  removal obligations. Confirm no Helm/RBAC/attestation, periodic diagnostics,
  Admin/Public API, OpenAPI/client, web, testenv/live, Spec promotion, automatic CA
  rotation, management UI, DNS controller, CRD, second reconciler, Runtime Control
  Kubernetes client, fallback, packet-enforcement claim, or unrelated refactor is
  added. Confirm strict capabilities are not advertised without the independent
  operator attestations owned by Phase 5.
- Context checkpoint: Phase 4 is implemented on Phase 3 commit `7630cbf1e` with
  `Design delta: None`. Runtime Control now parses the closed Kubernetes Profile v3
  direct/proxy-required/no-network union; the Provider process requires explicit
  mandatory Service and immutable proxy inputs and registers protocol/configuration
  v3; and lifecycle integration builds complete strict policies, DNS/hosts, persistent
  CA, proxy ConfigMap/Service/Pod, readiness fencing, public-only Runtime trust, and
  aggregate `network_enforcement` evidence. Start/restart/update/observe/stop/reset,
  recovery, and terminal deletion cover narrow-first transitions, broader-mode Pod
  removal, proxy-before-Runtime readiness, in-place CIDR/policy repair, bounded
  recreation-required outcomes, PVC preservation outside reset/terminal delete, CA
  preservation outside terminal delete, proxy-role recovery exclusion, and complete
  pre-mutation ownership fencing that rejects foreign same-name resources. The stable
  local evidence is 155 passing Kubernetes Provider tests, 121 passing Runtime Control
  tests, and 13 passing Runner trust tests, with Ruff, format, configured type checks,
  actionable-v2 absence searches, and `git diff --check` passing. Independent review
  found premature strict capability advertising, missing-CA regeneration, and
  incomplete recovery/watch ownership validation; the implementation now withholds
  strict capability authority until Phase 5 attestations, retains a safe CA fingerprint
  marker on the Workspace PVC and fails closed on CA loss or mismatch, and validates
  deterministic names plus complete ownership before recovery/watch reporting. The
  same reviewer approved all three corrections with no residual material finding.
  Remaining work is final unchanged-diff validation, commit/push, and the stacked PR.
  Later phases own Helm/RBAC/attestations, product/API/web projections, qualified packet
  validation, Spec promotion, and plan cleanup.
