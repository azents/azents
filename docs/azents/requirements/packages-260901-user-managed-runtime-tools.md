---
title: "User-Managed Runtime Tools Requirements"
created: 2026-09-01
updated: 2026-09-01
implemented: 2026-09-01
tags: [runtime, package-management, workspace, product]
document_role: primary
document_type: requirements
snapshot_id: packages-260901
---

# User-Managed Runtime Tools Requirements

- Snapshot: `packages-260901`
- Document reference: `packages-260901/REQ`

## Problem

Managed Runtime Agents need to install missing user-space tools without sudo or an
operating-system package manager. The current bundled Nix configuration stores
package outputs under a nonstandard HOME-relative store, which prevents use of the
standard binary cache and causes ordinary tools such as ffmpeg to require an
impractical source build.

The Runtime needs a user-managed package path whose package payloads are physically
inside the persistent Agent Workspace while still supporting fast prebuilt
installation.

## Primary Actor

An Agent using a managed Runtime shell.

## Primary Scenario

The Agent searches for ffmpeg, installs a compatible prebuilt package without sudo,
runs `ffmpeg` directly from the ordinary shell, and finds the installed command
still available after the Runtime compute is recreated with the same Agent
Workspace. Resetting the Agent Workspace removes the installed command and package
state.

## Supporting Scenarios

- The Agent installs another user-space CLI with dependencies that differ from
  ffmpeg's dependencies.
- The Agent chooses a package version or changes native package-manager settings
  within its existing Runtime authority.
- A Runner release updates the bundled package-manager executable and defaults
  without changing already installed user packages.

## Goals

- Provide rootless search, installation, update, removal, and direct execution of
  common user-space tools.
- Keep package payloads, user package state, and reusable cache physically inside
  the existing Agent Workspace lifecycle.
- Use prebuilt packages for ordinary supported tools instead of rebuilding their
  complete dependency graphs from source.
- Preserve installed tools across ordinary Runtime compute replacement and remove
  them with Workspace reset or terminal deletion.
- Keep package management native and user-managed rather than adding Platform
  package inventory or policy authority.

## Non-Goals

- Installing kernel modules, system services, privileged daemons, device drivers,
  or other host operating-system components.
- Providing every package available from a Linux distribution or Nixpkgs.
- Adding a package approval flow, administrator package catalog, inventory,
  vulnerability scanner, quota, or automatic update service.
- Adding a Runtime capability, Profile option, API, Provider storage surface, PVC,
  or additional mount.
- Preserving compatibility with the current Nix command interface or HOME-relative
  Nix state.

## Requirements

### REQ-1. Rootless Workspace-resident package installation

The Agent must be able to install supported user-space packages as the existing
unprivileged Runtime user, with the package payload and user package state stored
under the current Agent Workspace.

**Acceptance criteria**

- Installation requires no sudo, privileged daemon, mount capability, user
  namespace, FUSE device, or operating-system package manager.
- Installed package payloads, manifests, exposed commands, and reusable package
  cache are physically located below the Runner-reported Agent Workspace.
- Package operations grant no authority beyond the existing Runtime user,
  filesystem, credential, and network boundaries.

### REQ-2. Native search, install, and direct command execution

The Agent must use one native package-manager CLI to search for compatible packages,
install them globally for that Agent Workspace, and run exposed commands directly.

**Acceptance criteria**

- Search can be limited to the current Linux platform.
- Installation resolves dependencies and downloads compatible prebuilt artifacts
  when the configured channel provides them.
- Installed commands are available through the ordinary Runtime `PATH` without
  environment activation.
- The Agent may select a package version and use native package-manager settings.

### REQ-3. Workspace lifecycle persistence

User-installed tools must follow the existing Agent Workspace persistence and
destruction boundaries.

**Acceptance criteria**

- Ordinary Runtime start, stop, restart, recovery, and recreation preserve installed
  package environments and exposed commands.
- Reusing the same Workspace at the same Runner path does not require package
  reinstallation.
- Workspace reset and terminal deletion remove package environments, exposed
  commands, manifests, and cache with the Workspace.
- Runtime reconciliation does not independently delete or rewrite user-installed
  package state.

### REQ-4. Isolated global tools

Independent global tools must not require one shared dependency environment.

**Acceptance criteria**

- Installing a global tool creates or uses an environment owned by that tool unless
  the Agent explicitly chooses a shared environment.
- Updating or removing one default global environment does not rewrite unrelated
  global environments.
- Exposed command names have an explicit conflict boundary and may be renamed by
  the Agent.

### REQ-5. No package-management control plane

The feature must remain bundled Runtime behavior rather than Platform-managed
package state.

**Acceptance criteria**

- No ToolkitConfig, capability, Runtime Profile field, API, database row, package
  inventory, approval flow, or administrator/customer setting is added.
- Release-provided channels and mirrors are user-overridable defaults rather than
  enforced package policy.
- Package updates occur only through explicit user or Agent commands.

### REQ-6. Replace the unusable Nix path

The Runtime must expose one supported package-manager path rather than retaining the
current nonfunctional Nix installation as a fallback.

**Acceptance criteria**

- The Runner image and prompt no longer advertise or configure Nix for user package
  installation.
- No legacy Nix environment, wrapper, or compatibility mode remains active.
- Existing unreferenced Nix files in an old Workspace are not automatically deleted
  by Runtime startup.

## Fixed Constraints

- The managed Runner remains non-root during normal execution.
- Docker and Kubernetes keep their existing Agent Workspace storage and security
  contracts.
- The Runner derives package paths from its current reported Agent Workspace rather
  than a fixed Provider mount path.
- Package installation remains subject to the Runtime's current network policy and
  available outbound endpoints.
- Git-tracked implementation and documentation remain in English.

## Open Assumptions

- The selected package channel continues providing prebuilt packages for common
  Linux x86_64 and aarch64 user-space tools.
- Provider recreation keeps one Runtime's Agent Workspace mounted at a stable
  absolute path.

## Confirmation

Confirmed by the requester on 2026-09-01 after reviewing the package-manager
alternatives, Pixi storage model, dependency isolation, persistence, maintenance,
and Azents integration design.
