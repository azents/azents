---
title: "ADR-0015: Agent Home kubernetes_asyncio → lightkube Migration Discussion"
created: 2026-04-03
tags: [backend, kubernetes, sandbox]
---

# ADR-0015: Agent Home kubernetes_asyncio → lightkube Migration Discussion

> 📌 **Related design document**: [lightkube-migration-agent-home.md](../design/lightkube-migration-agent-home.md)

## Background

In the [previous migration](../design/lightkube-migration.md), only the Toolkit (`kubernetes.py`) moved to lightkube, and Agent Home (`agent_home_k8s.py`) was excluded. The reason at the time was: "It only uses V1* models, so there is no type bug and no change is needed."

This time, we unify the Kubernetes interface on lightkube and clean up dependencies. Agent Home's `kubernetes_asyncio` CRUD usage will be migrated to lightkube.

Discussion: #2273

## Discussion Points and Decisions

### 1. Remaining kubernetes_asyncio for exec tool

**Background:** lightkube does not support WebSocket exec, so `kubernetes_asyncio` cannot be completely removed.

**Options:**

A) **Keep kubernetes_asyncio for exec only** — migrate only Agent Home CRUD.

- Pros: stable, verified code, minimum work.
- Cons: keep two dependencies: lightkube + kubernetes_asyncio.

B) **Replace exec with kr8s** — httpx-based and supports exec.

- Pros: can fully remove kubernetes_asyncio.
- Cons: mixes two libraries, kr8s maturity is uncertain, auth integration required.

C) **Implement WebSocket exec directly** — use the `websockets` library.

- Pros: fully removes kubernetes_asyncio.
- Cons: SPDY protocol handling is complex and costly to maintain.

**Decision: A**

- exec is a single Toolkit tool and kubernetes_asyncio is working reliably.
- kubernetes_asyncio imports remain only in kubernetes.py exec code and `create_exec_api_client()` in kubernetes_auth.py.

### 2. Agent Home client initialization method

**Background:** current `K8sAgentHomeClient` loads kubeconfig or in-cluster config internally.

```python
async def _get_api_client(self) -> ApiClient:
    if self._kubeconfig:
        await k8s_config.load_kube_config(config_file=self._kubeconfig)
    else:
        k8s_config.load_incluster_config()
    self._api_client = ApiClient()
```

**Options:**

A) **Use lightkube auto-loading** — `AsyncClient(namespace=...)`.

- Pros: concise code.
- Cons: cannot explicitly specify kubeconfig path.

B) **Inject AsyncClient externally through DI** — create in factory and pass in.

- Pros: easier testing, auth logic separated.
- Cons: constructor signature changes.

C) **Accept a KubeConfig object and create internally**.

- Pros: similar to current pattern.
- Cons: caller must create KubeConfig.

**Decision: B — inject AsyncClient externally**

DI makes testing easier and keeps auth logic in one place in the factory.

### 3. Pod spec build: lightkube models vs dict

**Background:** `_build_pod_spec()` currently uses about 20 `kubernetes_asyncio` V1* models.

**Options:**

A) **Use lightkube-models dataclasses**.

- Pros: type safety, IDE autocomplete, dataclass-based.
- Cons: requires one-to-one mapping work.

B) **Build as dict**.

- Pros: simpler mapping.
- Cons: no type safety; typos found only at runtime.

**Decision: A — use lightkube-models dataclasses**

Use lightkube's type-safety advantages. Mapping is mechanical work.

## Alternatives Reviewed

| Alternative | Reason Rejected |
|------|-----------|
| Replace exec with kr8s | Mixes two libraries and maturity is uncertain |
| Implement WebSocket exec directly | SPDY protocol complexity and maintenance burden |
| Dict-based Pod spec | Gives up type safety and does not use lightkube's advantage |
| lightkube auto-loading | Cannot control kubeconfig path; harder to test |
