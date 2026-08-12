---
title: "Hierarchical Runtime Network Restriction Phase 3 Provider Resources Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, kubernetes, proxy]
---

# Phase Execution Plan

- Phase: `3/8 — Provider resource primitives, CA, proxy, and trust`
- Branch/base: `feature/network-restriction-3-provider-resources` →
  `feature/network-restriction-2-control` at `4d19170a1`
- PR boundary: Add strict Kubernetes resource transport and comparison primitives,
  persistent logical-Runtime CA and canonical proxy-policy artifacts, a pinned
  mitmdump/Azents-addon image, and Runner public-trust bootstrap without activating
  the complete Provider resource lifecycle or enforcement bundle.
- Inputs: Completed Phase 1 canonical Profile v3 network modes and Phase 2
  protocol-v3 aggregate enforcement evidence; current Provider Pod, PVC,
  NetworkPolicy, and Lease API boundary; current Runner direct child-process
  execution and system trust roots.
- Deliverables: Typed Kubernetes Service, ConfigMap, Secret, selected Secret and
  ConfigMap volume, host-alias, and strict-DNS models; REST transport, manifests,
  parsers, exact owned-resource names, labels, annotations, redacted views, and
  comparison helpers; versioned logical-Runtime CA generation and fail-closed
  validation with separated public and proxy-only values; canonical proxy policy
  document and digest; independent proxy application/image with pinned mitmdump,
  policy validation, fail-closed protocol hooks, bounded redacted logs, and
  conformance tests; Runner public-certificate validation, inherited writable trust
  bundle, and child-process trust environment; Python and Docker CI plus release and
  snapshot image registration for the proxy artifact; focused transport, ownership,
  crypto, policy, addon, image, redaction, and Runner tests.
- Non-goals: Calling the new Service, ConfigMap, or Secret methods from Provider
  lifecycle commands; creating, updating, deleting, recovering, or observing the
  complete strict enforcement bundle; mandatory Platform Service reads; complete
  Runtime or proxy NetworkPolicy builders; readiness sequencing; mode transitions;
  removal of active protocol-v2 `network_policy` reconciliation; Helm values,
  attestations, RBAC, Service references, or default-deny packaging; Admin/Public
  APIs, OpenAPI, generated clients, web surfaces, E2E, Living Spec promotion,
  automatic CA rotation, management UI, or live infrastructure changes.
- Interfaces: Resource names derive only from a validated logical Runtime ID and
  fixed role suffixes. Owned labels include exact managed-by, Provider ID, Runtime
  ID, Workspace ID, Agent ID, resource role, configuration-management identity, and
  applicable desired generation. Safe annotations include only configuration
  sequence/digest, policy digest, CA fingerprint, and immutable artifact digest.
  Secret transport preserves opaque byte values but every diagnostic or comparison
  view exposes only key presence and safe digests. The CA profile has an explicit
  schema/profile version and expected Runtime-bound subject identity; initial
  creation returns a combined proxy private-key/certificate PEM and a separate
  public certificate PEM, while validation rejects malformed material,
  key/certificate mismatch, identity mismatch, unsupported profile, and fingerprint
  mismatch without regeneration. Runtime-selected Secret volumes can expose only
  the public certificate key; proxy-selected volumes can expose the combined private
  value read-only. Canonical proxy policy serialization is deterministic and carries
  schema version, Runtime ID, configuration sequence/digest, domain mode and
  canonical patterns, inherited allowed/denied CIDRs, expected CA fingerprint, and
  immutable proxy/addon artifact digest. The addon verifies the expected policy
  digest before readiness, authorizes host before resolution, validates every
  resolved and selected upstream address, rechecks redirect and authority
  consistency, and has no raw TCP/UDP/QUIC, TLS passthrough, insecure-upstream,
  `ignore_hosts`, direct-network fallback, flow persistence, body storage, or
  management UI path. Strict Pod inputs use `dnsPolicy: None`, a non-listening local
  resolver address, bounded resolver attempts, and exact mandatory `hostAliases`.
  Runner trust preparation is opt-in through fixed Provider-owned paths, validates
  exactly one public CA certificate, appends it to the image CA bundle rather than
  replacing public roots, writes an incarnation-local file atomically, and exports
  `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`, and
  `NODE_EXTRA_CA_CERTS` to every child operation. Direct and no-network inputs remain
  free of interception-trust and proxy variables. Proxy environment injection
  remains a Phase 4 Provider-Pod concern.
- Approved Design mechanisms: `M4`, `M5`, `M6`, `M7`, `M14`
- Authority references: `network-260812/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`,
  `REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`, `REQ-12`; `network-260812/ADR-D3`,
  `ADR-D4`, `ADR-D5`, `ADR-D6`, `ADR-D8`; approved Design Kubernetes Resource
  Ownership, Interception CA and Runtime Trust, Proxy Workload and Policy
  Enforcement, DNS/Mandatory Services/NetworkPolicy, Security, and Test Strategy
  sections; current Runtime Provider and Runtime Control Specs.
- Design delta: `None`
- Removal obligations: Replace the Kubernetes API boundary limited to
  Pod/PVC/NetworkPolicy with typed Service/ConfigMap/Secret/selected-volume/hosts/DNS
  primitives. Replace the Runner startup boundary without interception trust
  bootstrap with validated public-CA bundle preparation and inherited child-process
  trust variables. Retain the old active Provider lifecycle and v2 actionable
  `network_policy` path until Phase 4 activates the complete replacement.
- Absence verification: Exact protocol/method searches and transport tests prove the
  new typed resources are represented without raw untyped lifecycle payloads.
  Ownership tests reject name-only or foreign-label adoption, and Secret
  comparison/logging tests find no raw values, private keys, or certificate PEM.
  Volume tests prove Runtime inputs cannot select the proxy private key. CA tests
  prove existing malformed or mismatched state fails closed and is never silently
  regenerated. Addon/static image checks prove no passthrough, insecure upstream,
  raw transport, body persistence, or management listener is configured. Runner
  tests prove public roots are retained, required trust variables reach child
  processes, invalid mounted material prevents readiness, and direct/no-network
  startup does not add proxy or interception variables. Provider lifecycle tests and
  searches prove the new API methods are not yet called by start, observe, update,
  restart, stop, reset, recovery, or terminal deletion.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Kubernetes typed resource boundary | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/kubernetes_api.py`, `kubernetes_http.py`, focused transport tests | existing typed Pod/PVC/NetworkPolicy adapter | Service/ConfigMap/Secret CRUD/list models and REST methods; selected volumes, host aliases, DNS config; manifests and parsers | focused HTTP/model pytest, Ruff, format, ty, request-path and round-trip assertions |
| Provider-owned resource artifacts | `/root` | new focused modules under `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/`, `provider.py` only for shared constant extraction without lifecycle activation, focused tests | Profile v3 canonical inputs and typed Kubernetes resources | deterministic names and ownership metadata, safe comparison views, versioned CA material and validation, canonical proxy-policy document and digest | naming/ownership/redaction vectors, cryptography tests, deterministic serialization and mismatch tests |
| Provider dependencies and image | `/root` | `python/apps/azents-runtime-provider-kubernetes/pyproject.toml`, `uv.lock`, `Dockerfile` when required | CA implementation | exact pinned `cryptography` runtime dependency and reproducible Provider image | `uv add`, frozen lock install, full Provider checks and Docker build |
| Proxy addon and image | `/root` | new `python/apps/azents-runtime-proxy/**` | canonical proxy-policy contract and CA file contract | pinned mitmdump application, Azents policy addon, readiness evidence, bounded redacted stdout/stderr diagnostics, no-fallback image entrypoint | Ruff, format, ty, full pytest, addon conformance vectors, static launch-option checks, Docker build and smoke check |
| Runner trust bootstrap | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`, `execution.py`, new focused trust module, tests, Dockerfile only for fixed system-bundle contract if required | public-only CA mount contract | startup validation, atomic inherited bundle creation, child-process trust-variable inheritance, readiness failure on invalid input | focused Runner startup/execution/trust pytest, Ruff, format, ty, mounted-private-key absence assertions |
| Artifact CI and publication registration | `/root` | `.github/workflows/ci.yaml`, `.github/workflows/release.yaml`, `.github/workflows/snapshot.yaml`, `.dockerignore` only if required | proxy package and Dockerfile | proxy Python quality/test lane and CI/release/snapshot image builds with existing pinned actions | workflow syntax inspection, path-filter assertions, proxy Docker CI build |
| Documentation | `/root` | this phase plan and active implementation plan only | approved Design revision 1 | tracked Phase 3 execution scope and completion checkpoint | docs validators and `git diff --check` |
| Independent review | `/root/network-260812-reviewer` | read-only Phase 3 diff | stable implementation and focused evidence | authority, Kubernetes transport, cryptographic identity, secret exposure, proxy fail-closed behavior, Runner trust, publication, and scope report | written review findings |

- Integration order: typed Kubernetes resource/Pod input models → REST
  serialization/parsing → deterministic names/ownership and safe comparison views →
  CA profile/generation/validation → canonical proxy policy/digest → proxy
  addon/image and conformance tests → Runner trust preparation and child-process
  inheritance → CI/publication registration → focused validation → independent
  review → required corrections → final validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against the
  confirmed Requirements, ADR-D3/D4/D5/D6/D8, approved Design
  `M4`/`M5`/`M6`/`M7`/`M14`, current Specs, this plan, focused evidence, and the
  stable Phase 3 diff. It reports only material findings concerning resource
  ownership/adoption, typed transport fidelity, secret/private-key exposure,
  cryptographic profile and persistent identity, deterministic policy authority,
  proxy protocol bypass or unsafe logging, Runner system-root preservation and
  environment inheritance, artifact pinning/publication, removal boundaries, and
  scope drift.
- Final validation: In each of
  `python/apps/azents-runtime-provider-kubernetes`,
  `python/apps/azents-runtime-proxy`, and `python/apps/azents-runtime-runner`, run
  `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run ty check --error-on-warning`, and `uv run pytest -vv`; build the Provider,
  proxy, and Runner Dockerfiles and run the proxy image smoke/conformance check; run
  focused transport request/response round trips, CA corruption/mismatch and
  public/private separation vectors, policy digest/addon authorization and redaction
  vectors, strict DNS/host-alias manifest vectors, and Runner invalid/valid/direct
  startup and child-environment tests; run existing Kubernetes Provider and Runner
  full suites; validate workflow parsing/path and image-matrix registration,
  documentation hooks, static absence/authority searches, and `git diff --check`.
- Scope-drift check: Confirm complete M4/M5/M6/M7/M14 primitives and both Phase 3
  removal obligations. Confirm no Provider command invokes the new resource methods;
  no complete Runtime/proxy enforcement policy, lifecycle transition, recovery,
  mandatory Service authority, Helm/RBAC/attestation, API/UI/E2E/Spec behavior,
  automatic CA rotation, passthrough, direct fallback, second controller, CRD,
  Control-plane Kubernetes client, or network-resource persistence is added.
- Context checkpoint: Phase starts from Phase 2 commit `4d19170a1`. The Kubernetes
  adapter currently supports only Pod, PVC, NetworkPolicy, and Lease resources;
  Pod volumes support PVC and EmptyDir only; Pod specs have neither host aliases nor
  explicit DNS settings. Provider lifecycle remains the existing direct-path
  Pod/PVC/NetworkPolicy implementation and must remain behaviorally unchanged in
  this phase. The Runner currently starts without mounted CA preparation and creates
  a direct execution backend whose operation environment is passed unchanged to
  child processes. There is no proxy package or image. Remaining phases own complete
  Provider enforcement lifecycle and v2 actionable removal, Helm packaging and
  operator attestations, product projections, E2E/Spec promotion, and plan cleanup.
