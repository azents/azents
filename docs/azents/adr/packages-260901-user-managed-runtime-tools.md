---
title: "User-Managed Runtime Tools"
created: 2026-09-01
tags: [runtime, package-management, workspace, architecture]
document_role: primary
document_type: adr
snapshot_id: packages-260901
---

# packages-260901/ADR: User-Managed Runtime Tools

- Snapshot: `packages-260901`
- Document reference: `packages-260901/ADR`
- Requirements:
  [packages-260901/REQ](../requirements/packages-260901-user-managed-runtime-tools.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The current Runner installs Debian `nix-bin` and relocates Nix's writable store and
state under the Agent Workspace. Direct validation showed that the standard
`cache.nixos.org` artifacts require the logical `/nix/store` prefix. A
HOME-relative store therefore planned 3,749 source derivations for ffmpeg and
failed before producing an executable.

Nix symlink and chroot-store probes did not provide a transparent solution under
the current non-root Docker and Kubernetes security contracts. Provider-level
additional mounts would restore the standard path but would reintroduce a storage
surface explicitly excluded by the confirmed Requirements.

Research and local probes compared Pixi, micromamba, pkgx, Homebrew, and
nix-portable. Pixi installed and exposed a prebuilt ffmpeg environment entirely
under a fresh HOME without privileged operations.

## Decision Map

### Fixed or derived outcomes

- Package payloads and user package state live inside the current Agent Workspace.
- Existing Docker and Kubernetes Workspace storage and non-root execution remain
  unchanged.
- Package management remains native user activity with no Platform inventory,
  policy, API, capability, or Profile state.
- Runtime reset and terminal deletion remain the only package-state destruction
  boundaries.

### Accepted material decisions

- D1: replace Nix with Pixi global package management.
- D2: keep Pixi environments, global state, exposed commands, and cache under the
  Agent Workspace.
- D3: provide conda-forge through a release default mapped to the Prefix.dev mirror.
- D4: expose the native Pixi CLI and its global command trampolines without an
  Azents package wrapper or control plane.
- D5: perform one coordinated replacement with no Nix compatibility mode.

### Agent-owned implementation details

Exact helper names, file layout below the approved Workspace paths, Docker build
steps, checksum constants, environment-composition helpers, and equivalent unit
fixture structure are implementation-owned.

## Decisions

### packages-260901/ADR-D1. Replace Nix with Pixi global package management

**Status:** Accepted on 2026-09-01 by the requester.

**Requirements:** `packages-260901/REQ-1`, `REQ-2`, `REQ-4`, and `REQ-6`.

The Runner bundles a checksum-pinned Pixi executable. Agents use native
`pixi search`, `pixi global install`, `pixi global update`, and
`pixi global uninstall` commands.

Pixi was selected because Conda packages support installation into an arbitrary
user-owned prefix. Global environments isolate independent tool dependency graphs,
while exposed trampoline commands allow direct shell execution without activation.

**Rejected alternatives:**

- **Relocated single-user Nix:** rejected because standard binary-cache artifacts
  embed `/nix/store`, causing ordinary packages to rebuild from source.
- **Provider-mounted `/nix/store`:** rejected because it adds a Provider storage or
  mount contract excluded by `packages-260901/REQ-5`.
- **micromamba:** technically feasible but requires activation, `micromamba run`, or
  Azents-managed command exposure that Pixi already provides natively.
- **pkgx:** useful for on-demand execution, but persistent direct command exposure
  requires another shim or companion installation model.
- **Homebrew:** arbitrary prefixes can lose bottle compatibility and fall back to
  source builds.
- **nix-portable:** requires virtualized execution through bubblewrap or proot,
  cannot transparently expose ordinary installed commands outside that wrapper,
  and showed unacceptable overhead in the current Runtime.

### packages-260901/ADR-D2. Place all writable Pixi state under the Agent Workspace

**Status:** Accepted on 2026-09-01 by the requester.

**Requirements:** `packages-260901/REQ-1`, `REQ-3`, and `REQ-4`.

The Runner derives `PIXI_HOME` and `PIXI_CACHE_DIR` from its current
Runner-reported Agent Workspace. Pixi global environments, manifest, trampoline
configuration, and cache therefore follow the existing Workspace persistence and
destruction lifecycle.

Both locations remain on the same Workspace filesystem so the package cache and
environments can use supported hardlink or reflink deduplication. The Runner adds
only the Pixi global binary directory to the command `PATH`.

The Runtime does not migrate or delete historical `.nix` data found in an existing
Workspace.

### packages-260901/ADR-D3. Provide an overridable Prefix.dev conda-forge release default

**Status:** Accepted on 2026-09-01 by the requester.

**Requirements:** `packages-260901/REQ-2` and `REQ-5`.

The Runner image provides a system Pixi configuration whose default channel is
conda-forge and whose conda-forge endpoint is mirrored through Prefix.dev. This
provides a concise native install command and avoids depending on the
`conda.anaconda.org` download endpoint for the default path.

The configuration is a release default, not a security or policy boundary. Native
Pixi user configuration and command options may override it within existing
Runtime authority.

### packages-260901/ADR-D4. Keep package operations native and user-managed

**Status:** Accepted on 2026-09-01 by the requester.

**Requirements:** `packages-260901/REQ-2`, `REQ-4`, and `REQ-5`.

Azents provides prompt guidance and environment preparation only. It does not add
an `azents-pkg` wrapper, package service, mutation API, inventory, approval flow,
automatic update, or centrally owned lock.

Pixi's package-specific global environments remain the default isolation unit.
Agents may explicitly choose native Pixi version constraints, shared environments,
or exposed command names.

### packages-260901/ADR-D5. Replace the package-manager path in one cutover

**Status:** Accepted on 2026-09-01 by the requester.

**Requirements:** `packages-260901/REQ-5` and `REQ-6`.

The Runner image, environment preparation, shell profile, prompt guidance, tests,
and Living Specs replace Nix with Pixi in one release. No dual package-manager
mode, feature flag, legacy prompt, or compatibility fallback remains.

Existing Workspace `.nix` files are left untouched because deleting user-owned
state during startup would create an unapproved destructive migration.

## Consequences

- Common supported tools install from prebuilt Conda artifacts into the Agent
  Workspace and run without activation.
- Package availability and feedstock quality vary across conda-forge; privileged
  operating-system components remain outside the feature.
- Installing a package executes third-party artifacts with the Agent's existing
  Runtime permissions.
- Global environments are persistent but are not a replacement for project-level
  Pixi lock files when exact transitive reproducibility is required.
- Package cache growth remains user-managed.
