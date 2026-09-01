---
title: "User-Managed Runtime Tool Addon Requirements"
created: 2026-08-31
updated: 2026-08-31
tags: [runtime, package-management, nix, product]
document_role: primary
document_type: requirements
snapshot_id: nix-260831
---

# User-Managed Runtime Tool Addon Requirements

- Snapshot: `nix-260831`
- Document reference: `nix-260831/REQ`
- Related capability: [runtime-260831/REQ](./runtime-260831-persistent-system-tools.md)

## Problem

The persistent Runtime system-tool work selected Nix as the bundled package
interface, but its implementation review exposed an ambiguity about product
ownership. Release-provided package defaults were treated as an Azents-enforced
supply-chain policy even though Nix exists for Agent convenience rather than as a
Platform-managed package system.

## Primary Actor

An Agent using a bundled managed shell Runtime.

## Primary Scenario

The Agent uses the release-provided Nix defaults to search for and install a
convenience tool, while remaining free to use native Nix configuration and command
options within the Runtime's existing user, filesystem, and network authority.

## Supporting Scenarios

- The Agent customizes native Nix registry or command settings for its own Runtime.
- A Runner release updates the provided defaults without turning them into an
  administrator-managed policy surface.

## Goals

- Keep Nix a native, user-managed Runtime addon.
- Provide useful release defaults without presenting them as an enforcement or
  security boundary.
- Preserve the existing Runtime privilege, network, persistence, and Workspace
  boundaries.

## Non-Goals

- Enforcing one package catalog, substituter, signature policy, or binary-only
  realization policy against the Agent.
- Adding a package policy service, privileged daemon, wrapper command, package
  inventory, approval flow, or administrator/customer configuration.
- Guaranteeing that Agent-selected Nix options retain the release defaults.

## Requirements

### REQ-1. Release defaults without Platform policy ownership

The bundled Runtime must provide working Nix defaults, but Azents must not represent
those defaults as an enforced package policy.

**Acceptance criteria**

- The default native search and install commands work without prior Agent
  configuration.
- The Agent may use native Nix configuration, registries, and command options.
- Azents does not claim that Agent package operations are restricted to the
  release-provided catalog, substituters, signatures, or binary artifacts.

### REQ-2. Existing Runtime authority remains the security boundary

Nix customization must remain ordinary Agent shell activity inside the selected
Runtime.

**Acceptance criteria**

- Nix customization grants no additional container privilege, Provider credential,
  ServiceAccount, host filesystem, host package database, or network authority.
- Direct, proxy-required, and no-network Runtime policies remain effective.
- No package-management control plane or package inventory becomes Platform state.

### REQ-3. Addon state remains outside ordinary Workspace content

The default location for Nix package and user configuration state must remain in
Provider-owned Runtime storage rather than ordinary Agent Workspace paths.

**Acceptance criteria**

- Default Nix store, profile, state, cache, and user configuration paths are under
  the dedicated persistent Nix storage.
- Nix addon state is excluded from ordinary Workspace browsing, publication, and
  complete Workspace download.
- Runtime reset and terminal deletion retain the destructive boundaries established
  by `runtime-260831/REQ`.

## Fixed Constraints

- The Agent-facing interface remains the native Nix CLI.
- The Kubernetes Runner remains non-root with privilege escalation disabled and
  capabilities dropped.
- The feature remains bundled behavior rather than a Runtime capability, Profile
  option, or administrator/customer setting.
- Kubernetes and Docker expose the same Agent-visible addon behavior.

## Open Assumptions

- Release defaults remain useful for common tools even though the Agent may replace
  them.
- Agent-selected Nix behavior is bounded sufficiently by the existing Runtime
  execution and network sandbox.

## Confirmation

Confirmed by the requester on 2026-08-31 after the Phase 2 feasibility review:
Nix is a user-convenience addon, not an Azents-managed package system.
