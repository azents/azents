---
title: "Kubernetes Toolkit Historical Decision Reconstruction"
created: 2026-03-27
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: kubernetes-260327
historical_reconstruction: true
migration_source: "docs/azents/design/kubernetes-toolkit.md"
---

# Kubernetes Toolkit Historical Decision Reconstruction

- Snapshot: `kubernetes-260327`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/kubernetes-toolkit.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### kubernetes-260327/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
sequenceDiagram
    participant Admin as Customer Admin
    participant Agent as Agent
    participant NI as nointern Server
    participant Proxy as Egress Proxy
    participant K8s as Customer K8s API Server

    Admin->>NI: Create Kubernetes Toolkit<br/>(clusters + credentials)

    Agent->>NI: Agent execution
    NI->>NI: resolve() → create ApiClient per cluster<br/>(configured through proxy)
    NI->>Agent: provide 7 Generic tools

    Agent->>NI: k8s_list(cluster="prod", kind="Pod", namespace="app")
    NI->>Proxy: GET /api/v1/namespaces/app/pods
    Proxy->>K8s: (forward after SSRF validation)
    K8s-->>Proxy: Pod list
    Proxy-->>NI: Pod list
    NI-->>Agent: formatted result
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
