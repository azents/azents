---
title: "Persistent Runtime System Tools"
created: 2026-08-31
tags: [runtime, package-management, persistence, kubernetes, docker, architecture, security]
document_role: primary
document_type: adr
snapshot_id: runtime-260831
---

# runtime-260831/ADR: Persistent Runtime System Tools

- Snapshot: `runtime-260831`
- Document reference: `runtime-260831/ADR`
- Requirements: [`runtime-260831/REQ`](../requirements/runtime-260831-persistent-system-tools.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The confirmed Requirements introduce rootless, persistent system-tool installation for managed Kubernetes and Docker Runtimes. The current Runner image has a fixed package set. Kubernetes persists only the Agent Workspace PVC, while Docker persists a Provider-owned Runtime host directory. The current Runner security boundary blocks unprivileged user and mount namespace creation, so a user-local chrooted package store cannot replace a normal persistent store without relaxing the sandbox.

Package storage must remain outside Agent Workspace browsing and download semantics, survive non-destructive lifecycle operations, and be removed by reset and terminal deletion. Kubernetes is the primary production and end-to-end verification path; Docker must preserve the same Agent-visible contract with narrower verification.

## Decision Map

### Fixed or derived outcomes

- The package-management foundation is Nix, as explicitly selected by the requester.
- Nix is a bundled Runner implementation baseline, not a Provider capability or infrastructure-Profile option.
- Kubernetes and Docker Providers are both in scope.
- Kubernetes is the primary E2E verification path; Docker uses targeted parity verification.
- Package storage is Provider-owned durable state outside the Agent Workspace path surface.
- Reset and terminal deletion remove package storage; ordinary lifecycle and recreation preserve it.
- The existing resolved Runtime Toolkit prompt remains the model-visible guidance boundary.
- The Runner remains non-root without privilege escalation or added Linux capabilities.

### Material decisions

- **Accepted — runtime-260831/ADR-D1:** Package-management foundation.
- **Accepted — runtime-260831/ADR-D2:** Nix is baseline Runner behavior rather than negotiated capability or Profile authority.
- **Accepted — runtime-260831/ADR-D3:** Direct single-user Nix with signed binary substitution and no local builds.
- **Accepted — runtime-260831/ADR-D4:** Runner releases own the pinned catalog and binary-cache trust.
- **Accepted — runtime-260831/ADR-D5:** Agents use the native Nix CLI.

### Agent-owned implementation details

Local class names, resource suffixes, helper boundaries, seed manifest formatting, lock-file names, test fixture names, Nix state/cache paths, profile mutation locking, and unreferenced-store garbage-collection thresholds remain implementation details. Garbage collection must preserve profile roots and low-capacity failure must satisfy runtime-260831/REQ-7.

## Decisions

### runtime-260831/ADR-D1. Use Nix as the package-management foundation

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** runtime-260831/REQ-1 through runtime-260831/REQ-8.

Use the Nix package ecosystem as the foundation for Runtime system-tool discovery, installation, dependency closure management, and persistent executable profiles.

Nix was selected because it supports rootless user-facing package operations over an isolated dependency store, broad user-space package coverage, immutable package paths, reproducible catalog references, and equivalent Linux behavior across Kubernetes and Docker Runtime substrates.

#### Rejected options

- **Homebrew on Linux:** familiar command UX, but the supported Linux deployment assumes a fixed prefix and Tier-1 conditions that do not match the current rootless Runtime. Its host/system-library interaction and rolling package model are weaker fits for the required isolated Runtime contract.
- **Rootless apt/dpkg extraction:** does not reproduce package scripts, system integration, dependency configuration, or a coherent user-owned package database.
- **Pixi/Conda:** strong user-prefix package handling but not the selected general Linux system-tool catalog.
- **pkgx or mise:** useful package-runner or development-tool abstractions, but they add a less authoritative intermediary without providing the desired store and catalog contract.

#### Consequences

- The Runtime needs a persistent Nix store and profile lifecycle.
- The Runtime release must include trusted Nix bootstrap material.
- Package catalog, cache trust, build policy, prompt interface, and garbage collection require explicit decisions below.
- Provider-specific storage topology remains hidden behind one Agent-visible package-management experience.

### runtime-260831/ADR-D2. Treat Nix as bundled Runner behavior, not a Runtime capability

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** runtime-260831/REQ-1, runtime-260831/REQ-4, and runtime-260831/REQ-8.

Nix availability is part of the bundled Runtime execution environment, alongside baseline commands and language tooling already present in the Runner image. It is not negotiated as a Provider capability, selected in an infrastructure Profile, enabled per Workspace, or exposed as an administrator/customer setting.

The existing Runtime Toolkit prompt includes the concise Nix guidance whenever the Agent has the bundled managed shell Runtime. Runtime-free and shell-disabled Agents continue to receive no Runtime prompt.

Provider implementations still own the substrate-specific durable store topology required to preserve the baseline behavior. That physical storage mechanism does not create a product capability or Profile choice.

#### Rejected options

- **Profile module:** incorrectly turns one bundled implementation dependency into customer-visible topology authority and would imply that equivalent preinstalled tools should also become Profile capabilities.
- **Provider capability advertisement:** adds negotiation and compatibility state for behavior supplied by the common Runner release rather than by an optional Provider feature.

#### Consequences

- Existing Kubernetes and Docker Profile schemas do not gain a Nix enablement field solely for this feature.
- Prompt rendering does not query a Nix capability flag.
- Storage capacity and lifecycle must be resolved as Provider implementation configuration or a derived baseline, not as an Agent-visible enablement choice.
- A future Runtime implementation that does not use the bundled Runner must define its own complete shell Runtime contract rather than silently claiming this baseline.

### runtime-260831/ADR-D3. Use direct single-user Nix with binary substitution only

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** runtime-260831/REQ-1, runtime-260831/REQ-6, and runtime-260831/REQ-7.

The non-root Runner user directly owns and operates the persistent Nix store and executable profile. Package operations do not cross a daemon or sidecar boundary. The Runner receives no added Linux capability, privilege escalation, Provider credential, or host package authority.

Local Nix builds are disabled. Package installation may realize only trusted signed binary artifacts from the configured substituters. A package without an available trusted binary artifact fails explicitly rather than starting a source build.

Provider startup prepares a valid Nix store before Runner readiness. Normal package operations then execute as the existing Runner UID/GID through the ordinary shell process boundary.

#### Rejected options

- **Managed Nix daemon sidecar:** provides a central policy and serialization boundary but adds a root daemon, Unix socket authority, sidecar lifecycle, and new failure modes without a confirmed source-build requirement.
- **Local source builds:** increase package coverage but require materially broader build sandbox authority, consume unpredictable CPU/storage/time, and can run package build logic outside the bounded binary-substitution path.

#### Consequences

- The persistent store is writable by the Runner operating-system user and is isolated per logical Runtime.
- Kubernetes and Docker use different physical storage implementations but expose the same direct Nix CLI.
- Startup bootstrap must be deterministic and independent from package-source availability.
- Cache misses, unsigned paths, and unavailable catalog artifacts are bounded installation failures rather than Runtime startup failures.
- The existing container security context and network policy remain authoritative.

### runtime-260831/ADR-D4. Make the Runner release authoritative for catalog and cache trust

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** runtime-260831/REQ-1, runtime-260831/REQ-6, runtime-260831/REQ-7, and runtime-260831/REQ-8.

Each Runner release pins one Nixpkgs revision, the registry source used by the Agent-facing package commands, the allowed binary substituter URLs, and their trusted public keys. Kubernetes and Docker Runtimes using the same Runner release therefore resolve the same package catalog and trust roots.

The trusted bootstrap material includes the pinned catalog source needed for package search and resolution. Normal first use does not depend on a live GitHub catalog fetch. Updating the default catalog or cache trust requires a new Runner release and ordinary Runtime recreation; already installed immutable store paths remain usable.

#### Rejected options

- **Provider operational configuration:** permits independent Provider-specific revisions and private caches, but creates separate trust/configuration authority, cross-Provider package drift, Admin configuration surfaces, and a rollout lifecycle outside the bundled Runner baseline.
- **Workspace or Agent-selected catalog:** would let untrusted Runtime input redefine the default package supply chain and break cross-Provider parity.
- **Release defaults with Provider fallback or override:** creates two authorities and ambiguous package resolution rather than one exact release-owned source.

#### Consequences

- Package catalog and trust changes follow the Runner image release process.
- Provider configuration does not gain catalog URLs, Nixpkgs revisions, or trust keys in this snapshot.
- The bootstrap process must reconcile the release-pinned Nix closure and catalog source into persistent stores without deleting installed packages.
- Runtime network policy still determines whether configured binary caches are reachable.
- Private or Workspace-specific package catalogs require a later feature with explicit authority.

### runtime-260831/ADR-D5. Expose the native Nix CLI

**Status:** Accepted on 2026-08-31 by the requester.

**Requirements:** runtime-260831/REQ-1, runtime-260831/REQ-4, and runtime-260831/REQ-8.

Agents use the native release-pinned Nix CLI for package discovery and installation:

```console
nix search nixpkgs <name>
nix profile add nixpkgs#<package>
```

The Runner-managed environment places Nix state, cache, and the default executable profile on Provider-owned tool storage and includes the resulting profile `bin` directory in the shell execution path. The existing Runtime prompt describes only the two commands, the prohibition on privileged operating-system package managers, and the Project-dependency boundary.

#### Rejected options

- **Azents package wrapper:** could hide profile paths and lock handling but adds a custom package interface, documentation surface, compatibility contract, and maintenance layer over two sufficient native commands.

#### Consequences

- Runner releases update the prompt together with any incompatible Nix CLI change.
- Internal environment and locking details remain outside the model-visible prompt.
- Agents retain access to the rest of the Nix CLI within their existing shell authority; this does not create additional Runtime privilege.
