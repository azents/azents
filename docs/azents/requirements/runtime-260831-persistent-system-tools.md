---
title: "Persistent Runtime System Tools Requirements"
created: 2026-08-31
updated: 2026-08-31
tags: [runtime, package-management, persistence, kubernetes, docker]
document_role: primary
document_type: requirements
snapshot_id: runtime-260831
---

# Persistent Runtime System Tools Requirements

- Snapshot: `runtime-260831`
- Document reference: `runtime-260831/REQ`

## Problem

Agents can encounter a missing general-purpose command-line tool while working in a managed Runtime. The current Runtime image has a fixed tool set, and an Agent has no supported rootless installation path whose installed commands remain available after compute recreation.

## Primary Actor

An Agent executing shell work in a managed Kubernetes Runtime.

## Primary Scenario

During a task, the Agent discovers that a required user-space system command is unavailable. The Runtime gives the Agent concise installation guidance. The Agent finds and installs a suitable package without root privileges, uses the command in the same Runtime, and can use it again after the Runtime Pod is restarted or recreated.

## Supporting Scenarios

- An Agent in a managed Docker Runtime receives the same command-level installation experience and persistence semantics.
- An Agent continues using an already installed tool while external package sources are temporarily unavailable.
- An explicit Runtime reset returns package storage to an empty initial state.

## Goals

- Let Agents install a broad range of general-purpose user-space command-line tools and native libraries without root privileges.
- Preserve installed tools across ordinary stop, restart, recovery, and compute recreation.
- Keep package installation guidance short and consistently available in bundled managed Runtimes.
- Preserve the existing Runtime security, network, and destructive lifecycle boundaries.
- Provide the same Agent-visible installation commands on Kubernetes and Docker Runtimes.

## Non-Goals

- Installing kernel modules, host drivers, system services, privileged daemons, device integrations, system users or groups, or software that requires host operating-system mutation.
- Replacing a Project's dependency manager or modifying Project dependency manifests automatically.
- Guaranteeing that every upstream package or every package version is available.
- Bypassing `no_network`, proxy, domain, CIDR, or other Runtime network policy.
- Providing a package inventory or package-management UI in this snapshot.
- Making system-tool installation an administrator- or customer-selectable Runtime capability.
- Providing identical end-to-end verification depth for Kubernetes and Docker.

## Requirements

### REQ-1. Rootless system-tool installation

A bundled managed Runtime must let its Agent search for and install supported user-space system packages without root privileges or host operating-system mutation.

**Acceptance criteria**

- The Agent can search for a package and install it through the Runtime-provided package interface.
- The installed command becomes executable by later shell operations in the same Runtime.
- Installation does not require `sudo`, a privileged Runner, or writes to host system package state.

### REQ-2. Durable tool availability

Installed system tools must survive non-destructive Runtime lifecycle operations.

**Acceptance criteria**

- Installed tools remain usable after stop, restart, recovery, ordinary Pod or container replacement, and Runtime Profile recreation that preserves durable storage.
- A transient compute replacement does not require the Agent to reinstall previously installed tools.

### REQ-3. Destructive reset boundary

System-tool storage must follow the existing explicit destructive Runtime boundary.

**Acceptance criteria**

- Runtime reset removes installed system tools and returns tool storage to its initial state.
- Terminal Runtime deletion removes system-tool storage.
- No other lifecycle operation deletes system-tool storage.

### REQ-4. Concise Runtime guidance

The existing resolved Runtime prompt must concisely describe the package interface as part of the bundled Runtime environment.

**Acceptance criteria**

- A supported Runtime prompt identifies the search and install commands, prohibits privileged operating-system package managers, and distinguishes system tools from Project dependencies.
- The complete package-installation guidance is no more than 50 English words.
- A Runtime-free or shell-disabled Agent receives no Runtime package guidance.

### REQ-5. Storage separation

System package data must not become user Project data or ordinary Agent Workspace content.

**Acceptance criteria**

- Package-store contents are excluded from Agent Workspace browsing, Project registration, file publication, and complete Workspace download.
- Package storage has a Provider-owned durable lifecycle independent from user file paths while sharing the Runtime's reset and terminal-delete boundary.

### REQ-6. Existing security and network authority

Package discovery and installation must remain inside the selected Runtime's existing execution and network authority.

**Acceptance criteria**

- Installation cannot bypass the effective direct, proxy-required, or no-network policy.
- Package management grants no Provider credential, Kubernetes ServiceAccount, host package database, host filesystem, or additional container privilege to the Runner.
- Existing installed tools remain executable when network access is unavailable, provided the tool itself does not require network access.

### REQ-7. Bounded and recoverable failures

Package-management failures must not corrupt existing installed tools or prevent ordinary Runtime execution.

**Acceptance criteria**

- Unavailable packages, blocked network access, exhausted storage, invalid package input, and missing binary artifacts fail with explicit command errors.
- A failed installation leaves previously installed tools usable.
- Runtime startup remains available when package sources are unavailable.

### REQ-8. Kubernetes-first verification with Docker compatibility

Kubernetes is the primary production verification path, while Docker must preserve the same Agent-visible commands and lifecycle semantics.

**Acceptance criteria**

- Kubernetes verification covers installation, immediate execution, Pod recreation persistence, reset deletion, prompt presence, and network-policy failure behavior.
- Docker verification covers provider storage preservation and deletion, command availability, and prompt parity through targeted provider and Runner tests; an equivalent full Docker end-to-end matrix is not required.

## Fixed Constraints

- The existing Runtime prompt production path remains the model-visible guidance boundary.
- The PATH defect is handled independently and is not authority for this feature.
- Nix availability is a bundled Runner implementation baseline, not a Runtime capability, Profile option, or administrator/customer choice.
- Kubernetes Runner remains non-root with privilege escalation disabled and capabilities dropped.
- The package-management design must support both bundled Kubernetes and Docker Runtime Providers.
- Kubernetes is the primary end-to-end verification environment; Docker verification may be narrower as long as its user-visible contract remains equivalent.

## Open Assumptions

- The selected package catalog has sufficient binary coverage for common Agent user-space tooling.
- Platform operators can provide durable package-store capacity appropriate for the bundled Runtime deployment.
- Package-manager bootstrap artifacts can be included in the trusted Runtime release supply chain.

## Confirmation

Confirmed by the requester on 2026-08-31 before ADR and design decisions began.
