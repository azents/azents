---
title: "NoIntern Helm Packaging Historical Decision Reconstruction"
created: 2026-05-12
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: helm-260512
historical_reconstruction: true
migration_source: "docs/azents/design/helm-packaging.md"
---

# NoIntern Helm Packaging Historical Decision Reconstruction

- Snapshot: `helm-260512`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/helm-packaging.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### helm-260512/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Namespace and sandbox-server contract

Current production deployment places `nointern-server` and `nointern-sandbox` in separate namespaces. Before implementation, Helm chart must explicitly choose one of following.

1. **Keep multi-namespace**: closer to current production structure. Chart receives `server.namespace`, `sandbox.namespace` and must correctly render sandbox NetworkPolicy namespace selector and cross-namespace service address.
2. **Simplify to single namespace**: easier home cluster install. But less production parity and requires re-review of sandbox isolation model.

Default direction of this design is keeping multi-namespace for production parity. Therefore chart must state following contract.

- sandbox Pod preStop hook must be able to call `apiserver` internal endpoint.
- sandbox control client must be able to open outbound gRPC stream to `sandbox-control` service.
- `nointern-server` and `nointern-sandbox` must share same `internal-api-hmac` value.
- If NetworkPolicy is enabled, `nointern-sandbox` → `nointern-server` egress rule must render together.

### Explicit source section: Step 2: optional component parity

- Add `discordGateway`, `mcpEgressProxy` as opt-in.
- Verify ExternalSecret mode and component-specific ingress override.
- Confirm bundled-dependency-off + external-endpoint mode with temporary verification values combination.

### Explicit source section: Unresolved Decisions and User Confirmation Needed

1. **Public image registry**: Need decide where OSS/home cluster users pull images from. Current production ECR cannot be default.
2. **RustFS packaging method**: Need confirm before implementation whether to use public RustFS Helm chart as dependency or provide RustFS resources through nointern chart internal template.
3. **Sandbox prerequisite fail-fast**: Since default install includes `sandbox`, need decide how much RuntimeClass/NetworkPolicy/node scheduling assumptions are validated fail-fast through Helm schema, NOTES, preflight.
4. **`mcpEgressProxy` location**: Need check call path before implementation and decide whether to keep as server sub opt-in or promote to top-level component.
5. **Secret key contract**: Need decide whether to fix existing Secret names and keys according to production env wiring, or convert to chart-specific normalized keys.
6. **Production cutover goal**: Need confirm scope: only home cluster packaging, or production ArgoCD conversion to Helm too.
7. **Helm release strategy**: Need decide which release pipeline syncs chart version, appVersion, image tag.
8. **Preflight delivery method**: Need decide whether sandbox/snapshotter prerequisite verification stays in Helm schema/NOTES docs only or is provided as separate script.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
