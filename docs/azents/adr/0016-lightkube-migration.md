---
title: "ADR-0016: kubernetes_asyncio → lightkube Migration Discussion"
created: 2026-04-01
tags: [backend, kubernetes, engine]
---

# ADR-0016: kubernetes_asyncio → lightkube Migration Discussion

> 📌 **Related design document**: [lightkube-migration.md](../design/lightkube-migration.md)

## Background

Type bugs have repeatedly appeared in the kubernetes_asyncio library (#2198, NOINTERN-SEVER-3N, NOINTERN-SEVER-1W, NOINTERN-SEVER-3F). The root cause is insufficient type safety in the library. We will solve this by migrating to lightkube.

## Discussion Points and Decisions

### 1. Migration Scope

**Background:** nointern uses kubernetes_asyncio in two places:

- `engine/tools/kubernetes.py` — Toolkit tools: list, get, logs, events, apply, delete, exec, api-resources
- `runtime/sandbox/agent_home_k8s.py` — Agent Home Pod management, using 20+ models such as V1Pod and V1Container

**Options:**

A) **Migrate only Toolkit** (`kubernetes.py` + `kubernetes_auth.py`)

- Pros: narrower scope and lower risk. `agent_home_k8s.py` uses 20+ V1* models, so migration cost is high.
- Cons: two libraries coexist.

B) **Full migration** (`kubernetes.py` + `agent_home_k8s.py` + auth)

- Pros: single library dependency.
- Cons: converting V1* models in `agent_home_k8s.py` to lightkube models is a lot of work, and no type bug has occurred in that file.

**Decision: A — Toolkit only**

- Type bugs have not occurred in `agent_home_k8s.py`; it only uses typed models.
- DynamicClient bugs occur only in Toolkit, so replace only that path.
- Keep kubernetes_asyncio for `agent_home_k8s.py`, but remove it completely from Toolkit code except exec as described below.

### 2. Pod Exec Handling

**Background:** lightkube does not support WebSocket, so pod exec is not possible through lightkube. Current `_make_exec_tool()` uses kubernetes_asyncio `WsApiClient`.

**Options:**

A) **Keep kubernetes_asyncio WsApiClient** — use kubernetes_asyncio only for exec tool.

- Pros: verified implementation, minimal change.
- Cons: kubernetes_asyncio dependency remains in Toolkit code.

B) **Implement directly with raw websockets library**

- Pros: can fully remove kubernetes_asyncio.
- Cons: requires direct implementation of the K8s exec protocol, including SPDY/WebSocket multiplexing; high risk.

C) **Use lightkube's httpx client for raw HTTP request in exec tool**

- Pros: reduces library dependency.
- Cons: impossible because exec is WebSocket, not HTTP.

**Decision: A — keep WsApiClient**

- exec uses a WebSocket protocol and cannot be replaced by an HTTP library.
- Direct implementation has no benefit relative to risk.
- kubernetes_asyncio already remains for `agent_home_k8s.py`, so there is no additional dependency cost.
- Create a separate ApiClient only for the exec tool to isolate it.

### 3. API Resource Discovery

**Background:** lightkube does not have a discovery API equivalent to `kubectl api-resources`. Current implementation uses `async for resource in dyn.resources`, which is exactly the source of the bug.

**Options:**

A) **Call `/apis` directly through lightkube's httpx client**

- Pros: stays inside lightkube dependency and directly controls types.
- Cons: must implement API response parsing directly.

B) **Use `async_load_in_cluster_generic_resources()` + `get_generic_resource()`**

- Pros: uses lightkube built-ins.
- Cons: loads only CRDs; built-in resources still need to be collected from `lightkube.resources.*` modules.

C) **Use CoreV1Api + ApisApi combination for direct discovery**

- Pros: accurate data.
- Cons: multiple API calls required.

**Decision: A — call /apis with httpx**

- Using lightkube's internal AsyncClient httpx client automatically applies authentication.
- It can be implemented simply with `/api/v1` + `/apis` → `/apis/{group}/{version}`.
- Response structure is simple enough to parse with Pydantic models for type safety.

### 4. Auth Layer Architecture

**Background:** current `kubernetes_auth.py` supports four auth methods—kubeconfig, token, EKS, and GKE—and creates kubernetes_asyncio `Configuration` + `ApiClient`.

**Options:**

A) **Create lightkube KubeConfig directly**

- Pros: native to lightkube, clean interface.
- Cons: needs mapping for EKS/GKE token refresh hooks.

B) **Inject auth through custom httpx Transport**

- Pros: full control.
- Cons: depends on lightkube internals and is harder to maintain.

**Decision: A — create KubeConfig directly**

- Most cases can be handled with `KubeConfig.from_one(cluster=Cluster(...), user=User(token=...))`.
- EKS/GKE token refresh can use lightkube `User(exec=UserExec(...))` or custom auth httpx middleware.
- kubeconfig uses `KubeConfig.from_dict()`, keeping existing exec provider validation logic.
- proxy is natively supported through `AsyncClient(proxy=...)`.

### 5. Error Handling Mapping

**Background:** current code catches `ApiException` from kubernetes_asyncio and `ClientError` from aiohttp. lightkube uses httpx-based `ApiError`.

**Decision:**

- `ApiException` → `lightkube.ApiError`, using `.status.code` and `.status.reason`.
- `ClientError` from aiohttp → `httpx.ConnectError` / `httpx.TimeoutException`.
- Keep `FunctionToolError` mapping the same.

### 6. DynamicClient → Generic Resource Pattern

**Background:** current code accesses dynamic resources with `dyn.resources.get(api_version=..., kind=...)` → `dyn.get(resource, ...)`. lightkube creates resource classes through `create_namespaced_resource()`.

**Decision:**

- Replace `dyn.resources.get(api_version, kind)` with `create_namespaced_resource(group, version, kind, plural)` or `create_global_resource()`.
- Problem: lightkube needs the plural name. Cache it from discovery API or keep a kind → plural mapping.
- list/get/delete: `client.list(ResourceClass, namespace=...)`, `client.get(ResourceClass, name, namespace=...)`.
- server_side_apply: `client.apply(obj, field_manager="nointern-toolkit")`.

## Alternatives Reviewed

### kr8s

Rejected because server-side apply is not supported; issue #443 is open.

### kubernetes (sync) + asyncio wrapper

Not truly async and has performance issues.

### Keep kubernetes_asyncio + strengthen stubs

Applied as a short-term fix in #2203, but not a fundamental solution. DynamicClient internal bugs can only be guarded with stubs.

## Risks

| Risk | Impact | Mitigation |
|--------|------|------|
| lightkube Generic resource requires plural names | Additional API calls or hardcoding | Implement discovery cache |
| EKS/GKE token refresh may not work in lightkube | Authentication failure | exec-based auth or httpx auth middleware |
| lightkube may update less frequently than kubernetes_asyncio | Delay in new K8s API support | Cover with Generic resource |
