---
title: "Runtime Execution Profiles Phase 5 Gateway and Engine Execution Plan"
created: 2026-07-26
tags: [runtime, docker, gateway, engine, security]
---

# Phase Execution Plan

- Phase: `5 — policy gateway, fixed engine, and Runner client`
- Branch/base: `feature/runtime-execution-profiles-07-gateway-engine` → `feature/runtime-execution-profiles-06-kubernetes-enforcement`
- PR boundary: Docker-compatible policy gateway, fixed Engine and Runner image contracts, and Kubernetes topology integration needed to mediate build, run, and Compose through the gateway.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, implementation plan, Phase 3 applied policy evidence, and Phase 4 fixed Kubernetes topology, storage, and NetworkPolicy contracts.
- Deliverables:
  - An unprivileged gateway application that accepts a closed, version-pinned Docker-compatible Unix-socket API and forwards only validated requests to the private Engine socket.
  - An immutable, Provider-owned Engine image contract and Runner image tooling for Docker CLI and Compose, all using a fixed compatibility tuple and image digest references.
  - Independent authorization for `container.image_build`, `container.run`, and `container.compose`, with default-deny method, path, query, header, and request-field validation.
  - Immutable applied-policy digest verification and digest-aware gateway readiness evidence.
  - Provider integration that keeps the Runner public gateway socket read-only, Engine socket private to the gateway, and Engine storage separate from the Workspace PVC.
  - Unit, protocol, image-contract, Provider/Runner integration, and negative security regression coverage.
- Non-goals:
  - No raw Docker socket or arbitrary Docker API proxying; unsupported API versions, endpoints, methods, query parameters, streaming/interactive attachment, and opaque BuildKit sessions are denied.
  - No host Docker socket, hostPath, host namespaces, host devices, ServiceAccount token projection, Provider credential, Runner-control credential, raw Pod customization, user-controlled gateway/Engine image, or generic privileged option.
  - No rootless Engine implementation, no persistent Engine storage enablement including Home, and no Workspace bind mounts. Initial Compose permits Provider-owned named volumes only.
  - No capability activation or Profile advertisement for privileged-engine modules before Phase 7 qualified live isolation evidence; this phase delivers fail-closed code and artifacts only.
  - No Admin/Workspace/Agent UI work.
- Interfaces:
  - Gateway configuration contains immutable Runtime ID, desired generation, policy snapshot ID, policy digest, module/source versions, canonical policy document, public gateway socket path, and private Engine socket path. It verifies the canonical digest before creating the public socket and never reloads policy in place.
  - Gateway route handlers create typed `AuthorizedEngineRequest` values. The Engine client cannot accept arbitrary method/path/body forwarding.
  - The initial compatibility tuple fixes Docker API/CLI/Compose/Engine versions and uses immutable image digests. The implementation may use a restricted classic `/build` path with BuildKit explicitly disabled; opaque `/session` forwarding is prohibited.
  - `container.image_build` may use only bounded local tar contexts and an allow-listed image API surface. `container.run` may use only validated container lifecycle and read APIs. `container.compose` adds the validated network, volume, image, event, and container APIs required by the supported Compose commands.
  - `containers/create` rejects privilege, `CapAdd`, host or bind paths, devices, host/container namespaces, host networking, custom runtime/security options, arbitrary sysctls/DNS/extra-hosts, port publishing, static address settings, arbitrary drivers, and non-Provider-owned images, volumes, or networks.
  - Phase 4 retains exact topology ownership. Runner sees only the public gateway socket; gateway sees the public and private sockets; Engine sees only its private socket and Engine storage. The Engine never mounts the Workspace PVC.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Gateway, Engine, Runner, Provider, and delivery integration | `/root/runtime-execution-implementer` | `python/apps/azents-container-policy-gateway/**` (new); `images/azents-runtime-engine/**` (new); `python/apps/azents-runtime-runner/**`; `python/apps/azents-runtime-provider-kubernetes/**`; `infra/charts/azents/**` only for digest/image contract seams; `.github/workflows/**` only for image build/release matrix; associated tests | Phase 4 fixed topology and Phase 3 evidence | Closed gateway protocol, fixed artifacts, socket/readiness contract, integration tests | Gateway and affected package Ruff/format/Pyright/pytest; image smoke; Provider/Runner tests; Helm render/lint; `git diff --check` |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-5-gateway-engine.md`; localized integration/review fixes only after owner report | Implementer output | Scope verification, review, commit, and PR creation | Plan/diff scope check, primary verification |

- Integration order:
  1. Add the gateway package, immutable configuration parser, policy digest validation, typed request model, and default-deny route registry.
  2. Add request validators and fake-Engine protocol tests before forwarding any allowed request.
  3. Add fixed Engine and Runner image contracts, then smoke and no-secret/no-socket tests.
  4. Wire Phase 4 Provider topology to read-only/public-private socket mounts and digest-aware readiness.
  5. Add restricted build/run/Compose compatibility tests and image CI/release integration.
  6. Confirm the backend does not advertise or activate privileged-engine modules before qualified live validation.

- Independent review: `/root/runtime-execution-reviewer` performs a read-only review focused only on Requirements/Design mismatch, authorization bypass, arbitrary socket forwarding, host/credential/isolation leaks, image mutability, policy-digest fail-open behavior, resource/network escape, and data loss. Findings are batched into one correction pass; targeted re-review applies only to those high-risk corrections.

- Final validation:
  - Gateway unit, policy, authorization, route-conformance, readiness, and fake-Unix-Engine tests.
  - Negative matrices for disabled build/run/Compose modules and denied privilege, capability, host path/device/namespace/network, ports, volume, security option, build entitlement, registry/build-secret, and Compose bind-mount requests.
  - Runner and Engine image smoke checks, including Docker CLI/Compose availability and absence of the private Engine socket from Runner.
  - Kubernetes Provider tests for socket mount isolation, exact digest-aware readiness, immutable image references, and Workspace PVC separation.
  - Helm lint/template/render tests, `git diff --check`, and pre-commit on commit. Do not monitor CI until the full stack exists.

- Scope-drift check: Compare the complete Phase 5 diff against `feature/runtime-execution-profiles-06-kubernetes-enforcement`. Reject generic or user-controlled privileged/image/Pod options, raw socket forwarding, BuildKit session passthrough, host infrastructure access, projected credentials, persistent Engine storage, profile capability activation without qualified evidence, UI/API expansion, and Workspace bind mounts. Confirm every Engine request has a typed gateway authorization decision derived from the immutable applied policy.
