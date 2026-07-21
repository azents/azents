---
title: "NoIntern Helm Packaging Historical Requirements Reconstruction"
created: 2026-05-12
implemented: 2026-05-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: helm-260512
historical_reconstruction: true
migration_source: "docs/azents/design/helm-packaging.md"
---

# NoIntern Helm Packaging Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `helm-260512`
- Source: `docs/azents/design/helm-260512-helm-packaging.md`
- Historical source date basis: `2026-05-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

NoIntern production Kubernetes deployment is currently centered on ArgoCD app-of-apps and Kustomize overlays. This structure fits the current operating environment, but has high entry barrier for these purposes:

- Need an install unit to validate OSS deployment possibility.
- Need to install on a home cluster and use it as a non-production test zone.
- Need to provide installation UX familiar to Kubernetes users through Helm packaging.

Based on GitHub Issue #3594 and Discussion #3608, this design assumes direction: **provide one chart, but structure internals as componentized umbrella-style single chart**.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Implementation PR performs following QA.

1. `helm lint infra/charts/nointern`.
2. Run `helm template` with dependency-enabled values combination and confirm `server`, `web`, `adminWeb`, `sandbox`, bundled PostgreSQL/Redis/RustFS resources render.
3. Run with external dependency values combination and confirm bundled dependencies are off and only external endpoint/`existingSecret` references render.
4. Confirm opt-in rendering of `snapshotter`, `mcpEgressProxy`, `discordGateway`, `externalSecret` with advanced values.
5. If possible, perform dry-run/server-side apply in consumer-owned values or kind-like environment. For cluster-capability-dependent items such as RuntimeClass, record preflight/NOTES verification result in PR.

## Supporting Scenarios

Implementation PR performs following QA.

1. `helm lint infra/charts/nointern`.
2. Run `helm template` with dependency-enabled values combination and confirm `server`, `web`, `adminWeb`, `sandbox`, bundled PostgreSQL/Redis/RustFS resources render.
3. Run with external dependency values combination and confirm bundled dependencies are off and only external endpoint/`existingSecret` references render.
4. Confirm opt-in rendering of `snapshotter`, `mcpEgressProxy`, `discordGateway`, `externalSecret` with advanced values.
5. If possible, perform dry-run/server-side apply in consumer-owned values or kind-like environment. For cluster-capability-dependent items such as RuntimeClass, record preflight/NOTES verification result in PR.

## Goals

- Make NoIntern installable as one Helm chart.
- Default install should be service-runtime profile where core NoIntern user flow actually works, not merely minimal installation-barrier profile.
- Reflect component boundaries already separated in production in internal chart values structure.
- Separate production-only coupling such as AWS/EKS, ALB, ExternalSecrets, ECR into values and optional features.
- Include sandbox in default install as agent execution/runtime core, while keeping advanced prerequisite-heavy optimization components like snapshotter explicit opt-in.
- Leave compatibility path for existing ArgoCD operating model to transition toward consuming Helm chart.

## Non-goals

- This design alone does not declare NoIntern complete public OSS product.
- Do not immediately remove production Kustomize deployment.
- Do not redesign application code configuration model. However, identify environment variable/Secret/ConfigMap surface required for chart value injection.
- Do not automatically install sandbox/gVisor/snapshotter so it works in every home cluster.
- Do not complete transition of production managed dependencies in this design. Chart provides both bundled dependencies for home cluster convenience and external dependency connection for production.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
