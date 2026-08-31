---
title: "User-Managed Runtime Tool Addon"
created: 2026-08-31
tags: [runtime, package-management, nix, architecture]
document_role: primary
document_type: adr
snapshot_id: nix-260831
---

# nix-260831/ADR: User-Managed Runtime Tool Addon

- Snapshot: `nix-260831`
- Document reference: `nix-260831/ADR`
- Requirements: [nix-260831/REQ](../requirements/nix-260831-user-managed-runtime-tools.md)
- Related snapshot: [runtime-260831](../requirements/runtime-260831-persistent-system-tools.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

`runtime-260831/ADR-D3` selected direct single-user Nix with local builds disabled,
and `runtime-260831/ADR-D4` made the Runner release authoritative for catalog and
cache trust. Phase 2 implementation proved that the same non-root UID directly
owning the Nix store can rewrite configuration and registry state and can use native
command options to override release defaults. A network-disabled validation command
successfully enabled a local derivation build by overriding `max-jobs` and sandbox
settings.

Preventing those actions requires a separate store-owning policy boundary, a
restricted non-native interface, or a materially different package architecture.
The requester clarified that Nix is an Agent convenience addon rather than an
Azents-managed package system.

## Decision Map

- **Fixed:** native Nix CLI, persistent Provider-owned storage, non-root Runner,
  existing Runtime network authority, and no capability/Profile/Admin setting.
- **Accepted material decision:** release package settings are Agent-overridable
  defaults rather than Platform policy.
- **Agent-owned details:** exact default file paths, bootstrap helpers, environment
  composition, and equivalent validation fixtures.

## nix-260831/ADR-D1. Treat Nix package settings as Agent-overridable release defaults

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** `nix-260831/REQ-1`, `REQ-2`, and `REQ-3`.

The Runner release supplies a pinned initial Nixpkgs registry, signed-cache trust
keys, substituters, and conservative build defaults. These values provide a
functional and safe default experience, but they are not a security or policy
boundary against the Agent.

The Agent may use native Nix configuration files, user registries, environment
variables, and command options. Azents does not enforce binary-only realization or
one exclusive catalog after the Runtime becomes available. The existing Runtime
user, filesystem, container, and network boundaries remain authoritative.

Azents does not add a package daemon, sidecar, wrapper, policy service, approval
flow, package inventory, or administrator/customer configuration for this addon.

### Supersession

This decision supersedes `runtime-260831/ADR-D3` only where it requires local Nix
builds and unsigned or alternate realization paths to be impossible for the Agent.
It retains direct non-root single-user operation and the absence of added privilege.

This decision supersedes `runtime-260831/ADR-D4` only where it makes the release
catalog and cache trust the exclusive post-startup authority. The Runner release
continues to own the provided defaults and bootstrap seed.

### Rejected options

- **Separate store-owner package service or daemon:** would enforce policy but adds
  lifecycle, socket, ownership, Provider, and failure boundaries that are not
  justified for a convenience addon.
- **Restricted wrapper command:** would replace the approved native Nix interface
  and still require a separate authority to prevent direct store or binary access.
- **Abandon Nix:** discards the implemented persistence and native package
  experience even though the product does not require hard policy enforcement.

### Consequences

- Release defaults reduce accidental local builds and untrusted substitutions, but
  tests and documentation must not describe them as enforced.
- Agent-selected registries and configuration are ordinary persistent Runtime state
  and must default outside Agent Workspace storage.
- Package behavior may differ after explicit Agent customization.
- A future requirement for centrally enforced package policy requires a new
  management boundary and development snapshot.
