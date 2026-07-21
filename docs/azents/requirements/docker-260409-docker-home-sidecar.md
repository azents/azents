---
title: "DockerAgentHomeClient sandbox-daemon Sidecar Historical Requirements Reconstruction"
created: 2026-04-09
implemented: 2026-04-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: docker-260409
historical_reconstruction: true
migration_source: "docs/azents/design/docker-agent-home-sidecar.md"
---

# DockerAgentHomeClient sandbox-daemon Sidecar Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `docker-260409`
- Source: `docs/azents/design/docker-260409-docker-home-sidecar.md`
- Historical source date basis: `2026-04-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

`DockerAgentHomeClient` in `python/apps/nointern/src/nointern/runtime/sandbox/agent_home_docker.py` creates only **single container** `agent-home-{agent_id}` per agent. However, `.exec` / `.write_file` / `.read_file` call `SandboxDaemonClient` at `http://{container_ip}:8081`, and this port is supposed to be listened by `nointern-sandbox-daemon`.

Actual `supervisord.conf` in `docker/nointern/agent-runtime` image runs only `[program:mcp-proxy]` and there is no sandbox-daemon. Comment in `entrypoint.sh:5` says "sandbox-daemon: always start", but actual program does not exist; this is comment rot.

Result: in local docker backend, `exec` / `write_file` / `read_file` all do not work. Stage 3 testenv `live/sandbox.py` depends on this path, so Stage 3 Phase 2+ is blocked.

Reproduction:
```
Sandbox daemon not ready after timeout
RuntimeError: Sandbox daemon exec failed: All connection attempts failed
```

## Primary Actor

**File**: `python/apps/nointern/src/nointern/runtime/sandbox/agent_home_docker.py`

**Main changes**:
1. Add `sandbox_daemon_image: str` field to `__init__` (no default, injected by factory)
2. Split `_create_container` into `_create_main_container` + `_create_daemon_container`
3. Extract bind mount list into dataclass:
   ```python
   @dataclass(frozen=True)
   class _AgentHomeBinds:
       home_dir: Path
       agent_dir: Path
       users_dir: Path
       mcp_config_dir: Path | None
       mcp_creds_dir: Path | None
       extra: tuple[str, ...] = ()

       def to_docker_binds(self) -> list[str]: ...
   ```
4. Add `extra_binds: list[str] | None = None` keyword-only parameter to `ensure_ready` (testenv extension point, prod path None)
5. Lifecycle:
   ```python
   async def ensure_ready(self, agent_id, domain_config, stdio_configs=None, *, extra_binds=None):
       # 1) check/create main container
       main = await self._ensure_main_container(agent_id, domain_config, stdio_configs, extra_binds)
       # 2) create daemon sidecar (only possible after main is running)
       daemon = await self._ensure_daemon_sidecar(agent_id, extra_binds)
       # 3) wait for daemon health
       await self._wait_for_daemon(agent_id)
   ```
6. `get_file_storage` no longer queries main container IP — daemon shares main network namespace, so main IP is daemon IP. Since "daemon listens on main's `localhost:8081`", worker accesses main container IP:8081
7. `delete_agent` deletes daemon sidecar → mcp-proxy sidecar → main in reverse lifecycle order
8. Add `_daemon_containers: dict[str, DockerContainer]` — track independently from main

**Daemon container config example**:
```python
{
    "Image": self._sandbox_daemon_image,
    "Env": [
        "SANDBOX_DAEMON_EXECUTOR=docker",
        f"SANDBOX_DAEMON_TARGET_CONTAINER_NAME={main_container_name}",
    ],
    "HostConfig": {
        "NetworkMode": f"container:{main_container_name}",  # share network ns
        "Binds": [
            *main_binds,  # same bind mount (path consistency)
            "/var/run/docker.sock:/var/run/docker.sock:ro",
        ],
        "Memory": 256 * 1024 * 1024,
        "CpuQuota": 25_000,
    },
    "Labels": {
        "managed-by": "nointern",
        "nointern/agent-id": agent_id,
        "nointern/role": "sandbox-daemon",
    },
}
```

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

K8s features that Docker backend **does not reproduce**. These are docker-specific limits, not implementation defects; design intentionally gives up these items.

| # | K8s feature | Docker reproduction? | Description |
|---|---|---|---|
| 1 | `runtimeClassName: sandbox` (gVisor/kata) | ❌ give up | docker has no runtimeClass concept. If similar isolation is needed, manually specify `--runtime=runsc` (when gVisor installed), not provided by default |
| 2 | custom `seccompProfile` | ⚠️ partial | supports `--security-opt seccomp=profile.json`. Current `agent_home_docker.py` uses `seccomp=unconfined`. Prod profile can be ported to `testenv/nointern/fixtures/` if needed, but excluded from initial implementation |
| 3 | `NetworkPolicy` (CNI layer egress/ingress) | ❌ give up | k8s NetworkPolicy is implemented by CNI. docker approximates with bridge + manual iptables rules or mitmproxy-based domain filtering (`ENABLE_PROXY` env). Current code already uses proxy method, so domain filtering is reproduced |
| 4 | `ServiceAccount` `pods/exec` RBAC | ❌ give up | docker has no SA concept. daemon execs through `docker.sock` → permission boundary is **docker daemon permission (root-equivalent)** and excessive. Security boundary mismatch — accepted for local dev premise |
| 5 | Pod lifecycle (restartPolicy, probes) | ⚠️ approximate | can approximate with docker `HostConfig.RestartPolicy` + `Healthcheck`. Initial implementation does not restart `always` |
| 6 | Downward API env (`SANDBOX_DAEMON_POD_NAME`) | ⚠️ approximate | no corresponding meaning in docker. Manually inject `SANDBOX_DAEMON_CONTAINER_NAME=agent-home-{id}` into daemon (parallel role to k8s `target_pod_name`) |
| 7 | EFS PVC subPath | ✅ reproduced | maintain same path structure with host bind mount |
| 8 | mcp-proxy sidecar composition | ✅ reproduced | can be added with same sidecar pattern (not **included in scope** of this design — keep existing embedded mcp-proxy method, consider sidecar migration as follow-up) |
| 9 | Resource limits (memory/cpu) | ✅ reproduced | same with `Memory` / `CpuQuota` |
| 10 | network isolation (`--ip` fixed, sandbox VLAN) | ❌ give up | initial implementation uses testenv compose default bridge network |

**Core principle**: fact that "this cannot be reproduced in docker" is itself a design output. This table answers future contributors asking "why is docker different from k8s?".

## Non-goals

K8s features that Docker backend **does not reproduce**. These are docker-specific limits, not implementation defects; design intentionally gives up these items.

| # | K8s feature | Docker reproduction? | Description |
|---|---|---|---|
| 1 | `runtimeClassName: sandbox` (gVisor/kata) | ❌ give up | docker has no runtimeClass concept. If similar isolation is needed, manually specify `--runtime=runsc` (when gVisor installed), not provided by default |
| 2 | custom `seccompProfile` | ⚠️ partial | supports `--security-opt seccomp=profile.json`. Current `agent_home_docker.py` uses `seccomp=unconfined`. Prod profile can be ported to `testenv/nointern/fixtures/` if needed, but excluded from initial implementation |
| 3 | `NetworkPolicy` (CNI layer egress/ingress) | ❌ give up | k8s NetworkPolicy is implemented by CNI. docker approximates with bridge + manual iptables rules or mitmproxy-based domain filtering (`ENABLE_PROXY` env). Current code already uses proxy method, so domain filtering is reproduced |
| 4 | `ServiceAccount` `pods/exec` RBAC | ❌ give up | docker has no SA concept. daemon execs through `docker.sock` → permission boundary is **docker daemon permission (root-equivalent)** and excessive. Security boundary mismatch — accepted for local dev premise |
| 5 | Pod lifecycle (restartPolicy, probes) | ⚠️ approximate | can approximate with docker `HostConfig.RestartPolicy` + `Healthcheck`. Initial implementation does not restart `always` |
| 6 | Downward API env (`SANDBOX_DAEMON_POD_NAME`) | ⚠️ approximate | no corresponding meaning in docker. Manually inject `SANDBOX_DAEMON_CONTAINER_NAME=agent-home-{id}` into daemon (parallel role to k8s `target_pod_name`) |
| 7 | EFS PVC subPath | ✅ reproduced | maintain same path structure with host bind mount |
| 8 | mcp-proxy sidecar composition | ✅ reproduced | can be added with same sidecar pattern (not **included in scope** of this design — keep existing embedded mcp-proxy method, consider sidecar migration as follow-up) |
| 9 | Resource limits (memory/cpu) | ✅ reproduced | same with `Memory` / `CpuQuota` |
| 10 | network isolation (`--ip` fixed, sandbox VLAN) | ❌ give up | initial implementation uses testenv compose default bridge network |

**Core principle**: fact that "this cannot be reproduced in docker" is itself a design output. This table answers future contributors asking "why is docker different from k8s?".

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
