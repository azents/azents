---
title: "gVisor + BYOC Sandbox Discussion"
created: 2026-04-03
tags: [infra, engine, security, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: gvisor-260403
historical_reconstruction: true
migration_source: "docs/azents/adr/0014-gvisor-byoc-sandbox.md"
---

# gvisor-260403/ADR: gVisor + BYOC Sandbox Discussion

> 📌 **Related**: [gvisor-260403-gvisor-byoc-sandbox.md](../design/gvisor-260403-gvisor-byoc-sandbox.md)

## Background

The current sandbox uses bwrap (bubblewrap) to provide filesystem isolation and network isolation. We reviewed moving to gVisor to support BYOC (Bring Your Own Cloud) and privileged sandboxes.

## Discussion Point A: Per-user `/data/user` Isolation

### Current State

bwrap creates a new mount namespace for every exec and mounts `/data/user` differently per user. This isolation breaks under the gVisor transition and BYOC sidecar structure:

- A dynamic volume mount cannot be added to a running Kubernetes container.
- In BYOC, the responsibility model is sudoer-based, so we may choose not to guarantee isolation at all.

### Options Considered

| Option | Description |
|---|---|
| A. gVisor + unshare | Decide after verifying whether `CAP_SYS_ADMIN` + `unshare --mount` works under gVisor |
| B. env var injection | Inject `USER_DIR=/data/users/{user_id}` per exec; file API routes paths through daemon |
| C. Give up isolation | Stop treating file isolation as a privacy boundary and unify the boundary around bot access control |

### Decision: combine C + B

**Give up treating isolation as a privacy mechanism.**

Rationale:

- In a public channel, A's session response can be visible to B. Even with file isolation, user memory is semi-public.
- Keep the concept of user memory, or per-user directories, without an isolation guarantee. It is useful for organization and personalization.
- Unify the privacy boundary around bot access control (#2242).

**Adopt agent path awareness using A+B style ergonomics:**

- A: State the actual path in the system prompt: `/mnt/agent-data/agents/{id}/users/{user_id}/`.
- B: Provide `$USER_DIR` env var shorthand so shell usage stays portable.

**Implemented**: user-folder PR series #2251-#2256, merged on 2026-04-03.

---

## Discussion Point B: gVisor + MITM Proxy Compatibility

### Current Structure, bwrap-based

`supervisord` runs these processes in the same container (`agent-runtime`):

- `mitmproxy` — `localhost:8080`, HTTP proxy with domain filtering through addon.py
- `socat` — `UNIX:/run/proxy/proxy.sock → TCP:127.0.0.1:8080`
- `sandbox-daemon`

Inside bwrap:

- `--unshare-net` removes network interfaces.
- `--bind proxy.sock /run/proxy/proxy.sock` bind-mounts the UNIX socket.
- socat maps `TCP:3128 → /run/proxy/proxy.sock`.
- `HTTP_PROXY=127.0.0.1:3128`.

### Does this structure work with gVisor?

**No, for two reasons:**

1. **Host UDS mount is unsupported**: mounting the sidecar UNIX socket as a gVisor container volume causes connection errors because the gVisor gofer treats the socket file like a regular file.

2. **Network isolation cannot be forced**: bwrap `--unshare-net` removes network interfaces entirely, and there is no equivalent under gVisor. Setting only HTTP_PROXY can be bypassed.

### iptables REDIRECT Review

**Not reliable:**

- gVisor iptables support is partial, including NAT REDIRECT checksum bugs and no UDP support for `SO_ORIGINAL_DST`.
- eBPF cannot access the isolated boundary between gVisor netstack and the host kernel.

### Decision: split mitmproxy into a separate Pod per agent

```text
[sandbox Pod]  egress: allow only mitmproxy Pod through NetworkPolicy
  app → HTTP_PROXY=http://agent-home-mitmproxy-{agent_id}.nointern-sandbox.svc:8080
  sandbox-daemon

[mitmproxy-{agent_id} Pod]  egress: open
  mitmproxy + addon.py (ALLOWED/DENIED_DOMAINS)
```

Rationale:

- Containers inside a Pod share a network namespace, so app/mitmproxy separation cannot be achieved as sidecars.
- NetworkPolicy can enforce `sandbox Pod egress → only mitmproxy Pod`, replacing `--unshare-net`.
- mitmproxy must be a separate Pod so that mitmproxy itself can reach the internet.
- ALLOWED/DENIED_DOMAINS differ by agent, so a shared DaemonSet is not viable; use one Pod per agent.

Remove socat: once bwrap is gone, the socat bridge is also unnecessary. Connect to mitmproxy directly over TCP.

---

## Discussion Point C: Warm Pool Strategy Change

### Decision

- **Reintroduce the gVisor NodePool at the same time bwrap is removed.**
- Revisit BYOC-specific details such as image pulling and warm pool optimization when BYOC planning begins.

---

## Feasibility Check Summary

| Item | Conclusion | Difficulty |
|---|---|---|
| Remove bwrap | ✅ Simple — gVisor replaces isolation | Low |
| Split mitmproxy Pod | ✅ Feasible — same pattern as mcp-proxy | Medium |
| NetworkPolicy change | ✅ Only add egress rule | Low |
| gVisor RuntimeClass | ✅ One line in Pod spec | Low |
| Karpenter NodePool | ⚠️ Need new pool; verify AL2023 gVisor installation method | High |
| Local development isolation | ⚠️ Develop without gVisor in Docker; accept isolation-level differences | N/A |

## Migration provenance

- Historical source filename: `0014-gvisor-byoc-sandbox.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
