---
title: "Sandbox Runtime Profile Abstraction Discussion"
created: 2026-04-19
tags: [backend, sandbox, runtime, gvisor, kata, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sandbox-260419
historical_reconstruction: true
migration_source: "docs/azents/adr/0022-sandbox-runtime-profile.md"
---

# sandbox-260419/ADR: Sandbox Runtime Profile Abstraction Discussion

> 📌 **Related design document**: [sandbox-runtime-profile.md](../design/sandbox-runtime-profile.md)

## Background

The current nointern sandbox is hardcoded to Kubernetes + gVisor, and nointern-snapshotter is fixed to a workaround using `nerdctl commit --pause=false` to avoid the gVisor runsc ttrpc issue. In the short term, we keep the gVisor `--pause=false` workaround. Long term, we plan to move to Kata Containers + bare metal and eventually cover full VM hibernate as a good-to-have.

This document records design decisions for covering "current gVisor / future Kata / local runc" with a single abstraction layer.

## Current Structure, Starting Point

**In the nointern app**

- `AgentHomeClient` ABC: implemented by `DockerAgentHomeClient` and `K8sAgentHomeClient`; backend abstraction already exists.
- `AgentHomeSnapshotClient` Protocol: Docker / K8s / Fake implementations.
- `SnapshotRef` value object: centered on OCI image refs, assuming rootfs commit+push model.

**Runtime-specific hardcoding points**

| Location | Hardcoding | Impact |
|---|---|---|
| `agent_home_k8s.py:386` | `runtimeClassName="sandbox"` | fixed to gVisor |
| `agent_home_k8s.py:398-402` | no seccomp setting, only gVisor comment | switching to runc/Kata weakens security |
| `ctr.py:268-277` | `nerdctl commit --pause=false` | unnecessary race for runc/Kata |
| `SnapshotRef` shape | single OCI image | cannot represent VM state blob |

## Discussion Points

### 1. Shape of `SandboxRuntimeProfile`

**Decision: discriminated union**

```python
@dataclass(frozen=True, kw_only=True)
class GVisorProfile:
    name: Literal["gvisor"] = "gvisor"
    # No seccomp/apparmor fields: gVisor isolates syscalls through a userspace kernel.

@dataclass(frozen=True, kw_only=True)
class RuncProfile:
    name: Literal["runc"] = "runc"
    seccomp_profile: Literal["RuntimeDefault", "Localhost"] = "RuntimeDefault"
    apparmor_profile: str | None = None

@dataclass(frozen=True, kw_only=True)
class KataQemuProfile:
    name: Literal["kata-qemu"] = "kata-qemu"
    snapshot_strategy: Literal[
        SnapshotStrategy.ROOTFS_PAUSE_TRUE,
        SnapshotStrategy.VM_CHECKPOINT,
    ] = SnapshotStrategy.ROOTFS_PAUSE_TRUE
    seccomp_profile: Literal["RuntimeDefault", "Localhost"] = "RuntimeDefault"
    apparmor_profile: str | None = None

SandboxRuntimeProfile = GVisorProfile | RuncProfile | KataQemuProfile
```

**Rationale:**

- Each runtime has different policies. gVisor has no meaningful seccomp setting, while only Kata has a rootfs vs VM choice. A flat dataclass makes it unclear whether `None` means "not meaningful for this runtime" or "meaningful but defaulted."
- `match profile:` enables exhaustive narrowing, and pyright forces all use sites to update when adding a new profile.
- `snapshot_strategy` is fixed as a `Literal` inside each variant, so the type system guarantees that gVisor cannot have anything other than `PAUSE_FALSE`.

**Rejected: flat dataclass + Optional fields**

- Ambiguity around `None = not meaningful or default`.
- No exhaustive narrowing.

### 2. Code placement

**Decision: A — local to nointern app + duplicate only `SnapshotStrategy` enum in snapshotter**

- Put profile + enum in `python/apps/nointern/src/nointern/runtime/sandbox/runtime_profile.py`.
- `python/apps/nointern-snapshotter/` defines only its own `SnapshotStrategy` enum. Wire communication uses strings.

**Rationale:**

- Wire communication is one `str` field, so sharing the full class has little value.
- Avoid mixing nointern domain types into `az-common`.
- Enum duplication is closer to duplicating wire contract constants and is acceptable.

**Rejected: shared az-common lib / new nointern-common lib**

- `az-common` is shared with azents, so adding nointern domain types blurs boundaries.
- There is weak justification for a new nointern-common library just for one type.

**Risk mitigation:** add one drift-prevention test that checks strategy string matching between snapshotter and nointern when snapshotter supports a new strategy.

### 3. Path for injecting snapshotter strategy

**Decision: A — DaemonSet env var through NodePool-specific Kustomize overlay**

- `Settings.snapshot_strategy` reads from `NOINTERN_SNAPSHOT_STRATEGY` env.
- Separate Kustomize overlays per node group / Karpenter NodePool.

**Rationale:**

- Maintain the premise that one node group has one runtime. There is no reason to mix gVisor and Kata nodes in one node group.
- Runtime transition is a deployment event, not a per-request change.
- Client-side runtime inference is unnecessary; current client only looks up hostIP.

**Rejected: send strategy in HTTP body / inspect node directly**

- Body approach requires the client to know the agent's node runtime, spreading concerns.
- Node inspection increases snapshotter complexity, and K8s RuntimeClass ↔ containerd runtime mapping is not guaranteed one-to-one.

**Risk:** if gVisor and Kata node groups coexist in one cluster later, deploy two DaemonSets with separate NodeSelectors. Operational burden is minimal.

### 4. Timing for expanding `SnapshotRef` structure

**Decision: B — introduce discriminated union now, with `RootfsSnapshotRef` as the first variant**

```python
@dataclass(frozen=True, kw_only=True)
class RootfsSnapshotRef:
    kind: Literal["rootfs"] = "rootfs"
    image_ref: str
    base_image_ref: str
    digest: str | None
    size_bytes: int | None

# Future VmSnapshotRef, added when Kata+metal work begins:
# kind="vm", vm_state_uri, rootfs_image_ref, memory_bytes, vcpu_count

SnapshotRef = RootfsSnapshotRef  # TypeAlias. Expand to Union when VM variant is added.
```

**Rationale:**

- DP1 uses a union for profile; keeping this flat would break consistency.
- Enforcing `match ref:` now lets pyright exhaustively check all use sites when a VM variant is added.
- Include `kind` in the wire format now; this is backward-compatible and prepares future client branching.

**Rejected: flat kind field / keep current shape and change later**

- Union is better for consistency than a flat kind field.
- Leaving it unchanged now effectively means the abstraction will not happen later; the user explicitly rejected that by saying abstraction must start now.

### 5. Runtime equivalence test scope

**Decision: B — parameterized unit tests + manual live checklist when introducing a new runtime**

- Use `pytest.mark.parametrize` to verify each profile creates the correct Pod spec / commit command.
- Use fake subprocess runner to prevent regressions in strategy ↔ command arg mapping.
- Verify real runtime bugs manually when introducing a runtime, as with the current gVisor ttrpc issue.

**Rationale:**

- The key invariant of the abstraction is correct `profile → cmd/pod spec` mapping, which fake tests can verify.
- Runtime-swap CI with real environments would require keeping a sandbox NodePool always running, wasting cost.
- Introducing a new runtime is an infrastructure event, so a manual validation step is natural.

**Rejected: no tests / azents-e2e runtime-swap scenario**

**Additional deliverable:** new profile checklist in `docs/nointern/design/sandbox-runtime-profile.md`:

1. Verify `nerdctl commit` behavior for the runtime.
2. Live test pause/unpause.
3. Define/deploy RuntimeClass.
4. Configure Karpenter NodePool labels/taints.
5. Update snapshotter DaemonSet env.
6. Review security profiles such as seccomp/apparmor.

## Implementation Plan

Four sequential PRs:

1. **PR1** — Profile types + SnapshotRef union + config fields.
2. **PR2** — Refactor K8sAgentHomeClient with profile injection.
3. **PR3** — Refactor nointern-snapshotter with strategy injection.
4. **PR4** — Deployment config + docs + ctr.py docstring update.

Each PR is a no-op in production behavior because gVisor remains the default.

## References

- `docs/nointern/design/phase3-snapshot-hibernation.md` — original snapshot design
- `docs/nointern/adr/gvisor-260403-gvisor-byoc-sandbox.md` — background for gVisor adoption
- Live diagnosis from the previous turn: `nerdctl commit --pause=true` succeeds in about 4s under gVisor, but the following unpause fails with `ttrpc: closed`, causing the container to exit 255. This is the actual root cause of production stuck Pods.

## Migration provenance

- Historical source filename: `0022-sandbox-runtime-profile.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
