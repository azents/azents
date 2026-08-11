---
title: "Untrusted Runtime Boundary"
created: 2026-08-11
tags: [runtime, security, provider, runner, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260811
---

# Untrusted Runtime Boundary

- Snapshot: `runtime-260811`
- Document reference: `runtime-260811/ADR`
- Requirements: [Untrusted Runtime Boundary Requirements](../requirements/runtime-260811-untrusted-runtime-boundary.md) (`runtime-260811/REQ`)

## Decision Map

- [x] `runtime-260811/ADR-D1` — Treat the complete Runtime as untrusted.
- [x] `runtime-260811/ADR-D2` — Remove the active process-containment product contract without replacement.
- [x] `runtime-260811/ADR-D3` — Preserve direct Profiles while failing closed for stored contained Profiles.
- [x] `runtime-260811/ADR-D4` — Restore minimum-privilege direct Runtime workloads.
- [x] `runtime-260811/ADR-D5` — Keep future user filesystem policy independent from Platform security.
- [x] `runtime-260811/ADR-D6` — Keep future Runtime network restriction independent from filesystem policy.

## Context

The `runtime-260808` snapshot introduced Provider-owned process containment around
Agent-started processes and treated the Runner as a trusted component. Its initial
Linux implementation installed a set-user-ID bwrap executable, added broad workload
capabilities, enabled privilege escalation, disabled the workload seccomp boundary,
unmasked proc, and required an enforcing node-local AppArmor profile.

Subsequent investigation established that bwrap itself does not require AppArmor,
that current upstream bwrap no longer supports the set-user-ID deployment model, and
that rootless bwrap inside an existing container depends on user-namespace and mount
preparation that is not portable across supported Provider environments. Local
qualification reproduced both nested-user-namespace denial and inherited-mount
propagation failure. Landlock worked without workload privilege and is a plausible
future path policy mechanism, but it is not a complete Platform containment boundary.

More importantly, the original trust model is incorrect for the product direction.
A future customer may provide the Runner. The Platform must therefore assume that
the Runner, every Agent-started process, and the complete Runtime workload are
malicious or compromised.

## Decisions

### runtime-260811/ADR-D1: Treat the complete Runtime as untrusted

**Affected requirements:** `runtime-260811/REQ-1`, `REQ-2`

The Azents Platform trust boundary ends before the Runtime workload. Runner
credentials are narrow capabilities for one logical Runtime and desired generation,
not proof that the Runner implementation is trusted. Runtime-originated registration,
state, operation, result, and transfer payloads remain untrusted and cannot create
authority beyond server-created, authenticated, generation-fenced work for that
Runtime.

Runtime compromise may destroy Runtime-local processes, Workspace data, temporary
state, results, or availability. It must not grant Provider, control-plane,
host-runtime, unrelated-Runtime, Workspace, Agent, or Session authority.

### runtime-260811/ADR-D2: Remove the active process-containment product contract without replacement

**Affected requirements:** `runtime-260811/REQ-3`, `REQ-4`

The portable `process_containment` Profile module, the
`runtime.process-containment` Provider capability, containment status projections,
and the bundled bwrap backend are removed from active product contracts.

This snapshot does not replace them with Landlock, another namespace launcher,
gVisor, an executor sidecar, or a new sandbox mode. Ordinary direct Runtime execution
already occurs inside the untrusted Runtime boundary and remains the only
non-DinD process behavior after removal.

The earlier `runtime-260808` and `runtime-260810` snapshots remain immutable
historical records of superseded decisions.

### runtime-260811/ADR-D3: Preserve direct Profiles while failing closed for stored contained Profiles

**Affected requirements:** `runtime-260811/REQ-4`, `REQ-5`

Profile schema v2 remains because it is a current Provider contract version
independent from process containment. Active typed Profile contracts remove the
`process_containment` field.

Persisted v2 direct documents that contain the previously required
`process_containment: null` representation are normalized as if the obsolete key
were absent. A persisted document with a non-null value is invalid under the new
contract and is unavailable. Admin inventory may expose bounded invalid-document
evidence but cannot reinterpret that Profile as direct execution. No data migration
strips an enabled containment claim, and Providers never drop it during command
lowering.

### runtime-260811/ADR-D4: Restore minimum-privilege direct Runtime workloads

**Affected requirements:** `runtime-260811/REQ-2`, `REQ-3`, `REQ-4`

Direct Runner workloads use a non-root identity, no privilege escalation, no added
capabilities, a dropped capability set, ordinary runtime-default syscall mediation,
and default proc masking. Runtime workloads receive no ServiceAccount token,
Provider credential, host container-runtime socket, host path, containment
RuntimeClass requirement, or node-local AppArmor profile selection.

Provider- and operator-owned node security may add stronger isolation, but the active
Azents Runtime contract does not configure or require it.

### runtime-260811/ADR-D5: Keep future user filesystem policy independent from Platform security

**Affected requirements:** `runtime-260811/REQ-6`

A future optional Project-based filesystem policy protects user-controlled local
files from Agent operations executed by a conforming Runner. It is not a Platform
security boundary against a malicious customer-provided Runner.

The policy will have an unrestricted state matching current behavior and a
restriction-enabled state compiled consistently for shell/managed processes and
typed file, edit, search, Git, import, and transfer operations. This snapshot does
not choose bwrap, Landlock, mount projection, or another implementation.

### runtime-260811/ADR-D6: Keep future Runtime network restriction independent from filesystem policy

**Affected requirements:** `runtime-260811/REQ-6`

The planned network direction uses a separate MITM proxy workload and Provider
network policy that permits Runtime egress only to that proxy plus mandatory
Platform destinations such as Runtime Control and DNS. Runtime Agent environments
receive the applicable HTTP(S) proxy and CA configuration. Network policy is the
anti-bypass boundary; proxy environment variables are client routing configuration.

This direction is future scope and does not create an implemented capability in
this snapshot. Filesystem restriction and network restriction have independent
ownership, configuration, enforcement, and availability.

## Consequences

- Runtime-originated protocol authorization becomes the primary Platform boundary.
- bwrap and AppArmor no longer block Provider availability.
- Runtime workload privilege is reduced instead of expanded.
- Existing direct Profile behavior is preserved.
- Stored contained Profiles require explicit administrator replacement.
- Future filesystem and network work can proceed independently and require new
  Requirements snapshots before implementation.
