---
title: "Hierarchical Runtime Network Restriction Phase 5 Helm Packaging Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, kubernetes, helm]
---

# Phase Execution Plan

- Phase: `5/8 — Helm packaging and operator attestations`
- Branch/base: `feature/network-restriction-5-helm` →
  `feature/network-restriction-4-provider-lifecycle` at `043825e1d`
- PR boundary: Package the Phase 4 Kubernetes Provider strict-network boundary with
  independent default-disabled operator attestations, immutable proxy inputs,
  explicit mandatory Service references, narrow RBAC, chart-owned workload default
  deny, and warning-only deployment diagnostics without adding product API/UI
  projections or claiming packet enforcement.
- Inputs: Completed Phase 4 protocol-v3 Provider lifecycle and aggregate
  `network_enforcement` evidence; Phase 3 immutable proxy/addon, typed Kubernetes
  resource, CA, and Runner trust primitives; Phase 2 connection-generation-scoped
  operational diagnostics protocol and persistence; the existing single-chart Helm
  packaging model, stable `runtime-control` ClusterIP Service, split Provider and
  workload namespace RBAC, and policy-managed workload default deny.
- Deliverables: Independent `proxyRequired` and `noNetwork` boolean attestations,
  both default disabled; capability-contract advertisement driven only by those
  booleans; immutable proxy image and addon digest values with proxy port/readiness
  settings; explicit role-unique `runtime_control` and `runtime_transfer` mandatory
  Service references, both mapped by default to the chart-owned stable
  `runtime-control` Service while retaining role-specific endpoint hostname and port
  inputs; workload Role lifecycle permissions for owned Pods, PVCs, Services,
  ConfigMaps, Secrets, and NetworkPolicies; exact resource-name-scoped `get` Roles
  and bindings for mandatory Services in their namespaces; bounded warning-only
  startup and periodic diagnostic snapshots for required API/RBAC access, mandatory
  Services, workload namespace identity/default-deny ownership, safely discoverable
  CNI support, unexpected selecting NetworkPolicies, and immutable proxy artifacts;
  chart schema/render tests for defaults, validation, environment, exact RBAC,
  default deny, and absence of DNS/proxy controller Deployments; Provider settings,
  capability, diagnostics, HTTP adapter, and run-loop tests; operator documentation
  for dedicated namespace, enforcing CNI, additive-policy ownership, attestations,
  and the distinction between warnings and enforcement evidence.
- Non-goals: Runtime lifecycle or enforcement-policy changes; new mandatory Platform
  Services; a transfer Service separate from the existing chart-owned
  `runtime-control` Service; capability inference from diagnostics, Kubernetes
  discovery, or successful reconciliation; capability suppression after an operator
  attestation; cluster-wide Service discovery, Secret access, TokenReview, node, or
  host-network permissions; a DNS controller, proxy controller, CRD, second
  reconciler, or new Deployment; Admin/Public API projection, OpenAPI/generated
  clients, web surfaces, testenv or live packet enforcement, Living Spec promotion,
  rollout to a live cluster, or plan cleanup.
- Interfaces: Helm values own `runtimeProviderKubernetes.strictNetwork.attestations`
  booleans, immutable proxy image/addon identity, proxy ports, mandatory Service
  references, and bounded diagnostic refresh settings. Provider environment parsing
  requires every deployment-critical field explicitly. `proxyRequired=true`
  requires a `sha256:` image digest and a 64-character lowercase addon SHA-256
  digest; `noNetwork` is independent and does not require proxy artifacts.
  `runtime.inspected-http-proxy` plus `runtime.network-enforcement` are advertised
  only for `proxyRequired`; `runtime.external-network-denial` plus
  `runtime.network-enforcement` are advertised only for `noNetwork`; shared
  `runtime.network-enforcement` is present when either attestation is enabled.
  Operational diagnostics are immutable snapshots returned by a supplier used for
  registration and heartbeat replacement. Every check is best effort and maps only
  to the Phase 2 allowlisted warning codes and metadata. Warning state never enters
  the capability contract, capability digest, lifecycle configuration, or Runtime
  acknowledgement. Mandatory Service Roles grant only `get` on exact configured
  names in exact namespaces. Workload namespace lifecycle RBAC remains namespaced.
- Approved Design mechanisms: `M3`, `M4`, `M6`, `M7`, `M8`
- Authority references: `network-260812/REQ-3`, `REQ-5`, `REQ-7`, `REQ-8`,
  `REQ-9`, `REQ-10`, `REQ-11`; `network-260812/ADR-D3`, `ADR-D5`, `ADR-D6`,
  `ADR-D7`; approved Design Provider Capability and Deployment Configuration,
  Kubernetes Resource Ownership, DNS, Mandatory Services and NetworkPolicy,
  Security and Permissions, Observability and Operations, deterministic coverage,
  Design Authority, Removal and Replacement, and Feasibility sections; historical
  Helm packaging Design `helm-260512/DESIGN`; current Runtime Provider and Runtime
  Control Specs.
- Design delta: `None`
- Removal obligations: Replace workload RBAC limited to Pod/PVC/NetworkPolicy with
  narrow lifecycle permissions for the complete Provider-owned resource set and
  exact-name mandatory Service reads. Replace unconditional absence of strict
  capabilities with explicit independent attestation authority. Reject mutable or
  missing proxy artifacts when proxy-required is attested. Do not introduce
  diagnostics-based capability inference/suppression, cluster-wide Service or Secret
  access, or new DNS/proxy controllers.
- Absence verification: Render defaults and every independent attestation
  combination and prove strict capabilities are absent unless their exact boolean is
  enabled. Settings/capability tests prove warning contents and Kubernetes results do
  not alter advertised capabilities. Schema/render failure tests prove attested
  proxy-required cannot render mutable or missing artifacts. Rendered RBAC inspection
  proves workload namespace scope, exact resources/verbs, mandatory Service
  `resourceNames`, no broad ClusterRole authority, and no TokenReview authority. Static rendered-kind
  and source searches prove no DNS/proxy controller Deployment, CRD, or second
  reconciler. Diagnostics tests prove only bounded allowlisted metadata is emitted
  and errors remain warnings. Existing default-deny selector render tests remain
  authoritative.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Helm values and schema | `/root` | `infra/charts/azents/values.yaml`, `values.schema.json`, `values-advanced-runtime.yaml` if applicable | fixed Provider deployment inputs and historical chart model | default-disabled independent attestations, immutable proxy/addon, mandatory Service, diagnostic settings and conditional schema validation | Helm schema failure/success matrix and JSON validation |
| Helm helpers and Deployment | `/root` | `infra/charts/azents/templates/_helpers.tpl`, `templates/runtime-provider-kubernetes/deployment.yaml.tpl` | chart values/schema | exact immutable references and Provider environment contract | render snapshots for defaults and all attestation combinations |
| Helm RBAC and workload boundary | `/root` | `infra/charts/azents/templates/runtime-provider-kubernetes/rbac.yaml.tpl`, `networkpolicy.yaml.tpl` | mandatory Service values and Phase 4 resource ownership | workload lifecycle Role plus exact-name mandatory Service Roles/Bindings while retaining chart-owned default deny | exact kind/namespace/resource/resourceName/verb assertions and no broad authority search |
| Provider capability authority | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/main.py`, `tests/test_main_settings.py` | independent boolean environment inputs | attestation-only strict capability advertisement and explicit artifact/settings validation | settings and capability combination tests; diagnostics-independence tests |
| Deployment diagnostics | `/root` | focused new Provider diagnostic module; `kubernetes_api.py`, `kubernetes_http.py`, `main.py`; focused tests | Phase 2 diagnostics types and existing typed resource adapters | bounded startup/periodic warning snapshot for API/RBAC, mandatory Service, namespace/default deny, CNI uncertainty, unexpected policies, and artifacts | fake API matrices, HTTP request tests, logging/redaction checks, run-loop supplier/refresh tests |
| Chart documentation | `/root` | `infra/charts/azents/README.md`, this plan and active implementation plan | final values, permissions, warning semantics | operator-owned dedicated namespace/CNI/additive-policy/attestation guidance and warning-not-proof boundary | documentation checks, terminology search, `git diff --check` |
| Helm render contracts | `/root` | `infra/charts/azents/tests/runtime_provider_kubernetes_render_test.py` | all Helm workstreams | deterministic disabled/default, independent enablement, validation, RBAC, environment, default-deny and controller-absence coverage | focused pytest with Helm plus chart lint/template |
| Independent review | `/root/network-260812-reviewer` | read-only stable Phase 5 diff | implementation and focused evidence | authority, RBAC least privilege, immutable artifacts, diagnostics isolation/redaction, chart semantics, removal and scope report | written Critical/Warning finding report |

- Integration order: Helm values/schema and immutable image helper → Deployment
  environment and attestation authority → capability/settings tests → workload and
  mandatory-Service RBAC → diagnostics typed API boundary and warning builder →
  registration/heartbeat supplier and bounded refresh → chart documentation → Helm
  and Provider focused tests → removal/authority searches → independent review →
  required corrections → final validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against the
  confirmed Requirements, ADR-D3/D5/D6/D7, approved Design
  `M3`/`M4`/`M6`/`M7`/`M8`, current Specs, historical Helm packaging authority,
  this plan, focused evidence, and the stable Phase 5 diff. It reports only material
  findings concerning attestation authority, capability combinations, mutable
  artifacts, mandatory Service trust, RBAC escalation or cross-namespace scope,
  default-deny ownership, warning-only isolation, metadata redaction/bounds,
  registration/heartbeat generation behavior, diagnostics failure handling,
  controller absence, operator documentation, and scope drift.
- Final validation: In `python/apps/azents-runtime-provider-kubernetes`, run
  `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run ty check --error-on-warning`, and `uv run pytest -vv`. In
  `infra/charts/azents`, run the focused render pytest suite, `helm lint .` with
  required external defaults/fixtures, and representative `helm template` renders
  for disabled, proxy-only, no-network-only, and both attestations. Validate
  `values.schema.json` as JSON; inspect rendered RBAC and resource kinds; run static
  searches for cluster-wide/TokenReview/Secret authority, automatic capability
  inference/suppression, mutable proxy references, and DNS/proxy controller units;
  run documentation hooks as part of commit and `git diff --check`. Qualified CNI
  packet enforcement remains Phase 7 and is not inferred from these checks.
- Scope-drift check: Confirm complete M8 authority and the M3/M4/M6/M7 packaging
  inputs required to activate existing Phase 4 behavior. Confirm no new product
  contract, mandatory Platform service, Runtime lifecycle behavior, fallback,
  capability auto-detection, enforcement claim, cluster-scoped permission, raw
  manifest configuration, controller, API/UI/client surface, live operation, Spec
  promotion, or unrelated chart refactor is added. Confirm diagnostics cannot alter
  capability advertisement or Runtime reconciliation.
- Context checkpoint: Phase 5 begins from Phase 4 commit `043825e1d` with a clean
  branch and `Design delta: None`. Phase 4 already requires explicit mandatory
  Service and immutable proxy inputs but the chart does not yet inject them; strict
  capabilities remain withheld; workload RBAC covers only Pods, PVCs, and
  NetworkPolicies; and the run loop supplies no operational diagnostics. The chart
  already owns one stable `runtime-control` ClusterIP Service, so both required
  Platform roles can reference that Service with independent endpoint/port data
  without inventing a new transfer Service. The chart already renders the dedicated
  workload namespace default deny for policy-managed Pods and must retain it.
  Remaining Phase 5 work is the implementation above, focused evidence, exact
  independent review, correction, final validation, commit/push, and a stacked PR
  against `feature/network-restriction-4-provider-lifecycle`. Later phases own
  product/API/web projections, qualified packet validation, Spec promotion, and plan
  cleanup.
