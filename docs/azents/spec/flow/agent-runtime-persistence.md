---
title: "Agent Runtime Persistence"
created: 2026-05-25
tags: [backend, engine, infra]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, workspace, conversation]
code_paths:
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/repos/agent_runtime/**
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/services/chat/workspace.py
  - python/apps/azents/src/azents/services/session_workspace_project/**
  - python/apps/azents/src/azents/runtime/**
  - python/apps/azents-runtime-provider-docker/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents-runtime-runner/**
  - infra/charts/azents/**
  - infra/argocd/azents-runtime-provider-kubernetes/**
last_verified_at: 2026-07-27
spec_version: 7
---

# Agent Runtime Persistence

## Overview

Agent Workspace durability is owned by the Runtime Provider backend, not by the Azents server
process and not by S3 checkpoint/restore as a event path. The Provider reports the Agent
Workspace absolute path as Runtime metadata. Server file APIs and prompts consume that reported
path instead of hardcoding `/home/sandbox`.

## Provider selection and immutable binding

When the first logical Runtime row is created, Agent Runtime service delegates Provider selection to
`RuntimeProviderSelectionService`. The exact Agent preference or typed Platform default is resolved in
one transaction. Selection does not use environment defaults or fallback after an explicit Provider is
ineligible. The selected durable Provider resource, binding origin, accepted contract/configuration
revision IDs, and an immutable policy snapshot are stored before lifecycle commands are dispatched.

A later availability, default, contract, or configuration change does not reassign an existing logical
Runtime. If no Provider can satisfy the request, the lifecycle API returns an explicit unavailable
conflict and no partial Runtime is persisted.

Runtime rows created before durable Provider contracts may contain only the historical logical
Provider ID. On the next Runtime access or lifecycle request, selection resolves that same logical
Provider, requires its accepted contract, stores the internal Provider resource ID with `migration`
origin, and attaches the initial policy snapshot transactionally. This upgrade does not replace the
logical Runtime, advance its desired generation, delete its workspace, or invoke a Provider
lifecycle command. A later explicit start or restart uses the normal generation-fenced policy and
preserves the existing host directory or PVC.

Runtime execution policy stores Agent intent separately from the applied Runtime target. Platform
and Workspace restrictions can only narrow policy. An Agent Profile/override change is pending until
explicit Apply attaches the next immutable target snapshot. A Platform or Workspace tightening
automatically attaches a narrower target and advances desired generation without reset, terminal
deletion, Provider fallback, or Agent Workspace data loss. Target/applied snapshots, policy digest,
source versions, and Provider evidence are generation-fenced durable metadata; they do not expose
credentials, projected tokens, socket paths, or raw manifests.

## Event Persistence

| Provider | Event persistence | Scope |
|---|---|---|
| Kubernetes Provider v1 | EBS-backed PVC per Runtime | Production Kubernetes path |
| Docker Provider v1 | Per-Runtime host directory bind mount on a stable single Docker host | Local/dev single-host path |

S3/RustFS checkpoint objects are not the event persistence contract for Agent Runtime v1.
Legacy checkpoint rows may remain for older data/model compatibility, but new Runtime lifecycle
correctness must not depend on checkpoint commit/restore.

## Workspace Path Contract

Provider reports the Agent Workspace path on lifecycle command completion and observe reports.
Control stores it on the Runtime row and exposes it through server-computed workspace/bootstrap
responses.

The current external providers mount `/workspace/agent` by default. That value is an implementation
default reported by Provider, not an API fallback. If the provider reports another absolute path,
the server uses that path after validation. If the provider reports no path, workspace operations
return explicit unavailable/failure state and do not fall back to `/home/sandbox` or
`/workspace/agent`.

Runner receives the provider path through provider-created backend configuration. Runner reports
its mounted path during registration/state updates; Control validates equality and records a
failure when Runner and Provider disagree.

## Destructive Operation Boundary

Only `reset` may delete Agent Workspace data.

- `start` may create compute and attach durable storage; it must not wipe existing workspace bytes.
- `stop` may stop compute; it must preserve durable storage.
- `restart` may recreate compute; it must preserve durable storage.
- `recover` and reconciliation may repair stale backend/control state; they must preserve durable
  storage.
- `observe` is read-only.

For desired-running Runtimes, periodic reconciliation uses idempotent `start` to compare the
Provider-managed workload against the current Runner image and configuration. Equivalent workloads
are reused. Drifted Docker containers or Kubernetes Pods are replaced while the host workspace
directory or PVC remains intact.

Any ambiguous backend outcome is treated as unavailable or retryable until Provider evidence proves
the desired state. Ambiguity is not permission to delete the workspace.

## Kubernetes Provider v1

Kubernetes Provider v1 is an external process that talks to the Kubernetes API and Runtime Control
gRPC. It uses Lease leader election so only the active leader issues lifecycle commands for a
provider id.

A healthy non-leader process reports Kubernetes readiness while it can inspect the leader Lease, so
a single-replica rolling Deployment can replace the old leader without waiting for the standby to
become active first. On leadership acquisition, the process clears readiness until Runtime Control
authentication and registration succeed. Standby processes do not open the authoritative Control
stream or mutate Runtime resources.

The active Provider keeps the Kubernetes Pod watch as a long-lived request without a client total or
socket-read deadline. Normal server-side watch completion is reopened independently and does not
rotate the authoritative Runtime Control connection.

For each Runtime, the provider creates or reuses an EBS-backed PVC and mounts it at the reported
Agent Workspace path in the Runner Pod. PVC identity is tied to Runtime identity/generation labels
and fenced by Control generation. Stale observations cannot overwrite newer desired generations.

Reset is the only command that may delete/recreate the PVC contents. Stop/restart/recover must not
delete the PVC.

The initial execution-policy topology is fixed Provider infrastructure, not user-configurable Pod
input. A Runtime may contain the Runner, policy gateway, and fixed engine components, but the
Runner and nested workloads do not receive the Provider ServiceAccount, Provider credentials,
Runtime Control credentials other than their Runtime-bound path, host sockets, or generic
privileged controls. Agent Workspace PVC storage remains distinct from nested-engine storage.
The current server capability gate exposes engine storage mode `none`; raw Provider registration
metadata does not itself enable ephemeral storage. Persistent nested-engine storage also remains
unavailable until a Provider advertises and qualifies bounded capacity.

## Docker Provider v1

Docker Provider v1 assumes one stable Docker host. For each Runtime it creates a host directory and
bind-mounts it into the Runner container at the reported Agent Workspace path. The host directory is
the event persistence source.

Stop/restart/recover may remove/recreate containers, but must keep the host directory. Reset may
delete or replace the host directory according to the reset command.

## Agent Workspace Projects

Session Workspace Project registry rows are AgentSession-scoped DB state. They are not derived from
filesystem snapshots. Runtime persistence preserves the bytes; the session registry preserves which
child paths are registered or awaiting registration approval for the selected conversation.

Project paths are normalized as children of the provider-reported Agent Workspace root. The root
itself is not a Project. Runtime persistence does not own Project membership. azents-web exposes
Project management inside the concrete session Workspace surface. The Workspace browser opens in
Project mode by default, keeps `All files` as an explicit Agent Workspace root inspection mode, and
uses backend Project browser manifest capabilities so Project root removal is registry-scoped rather
than filesystem-destructive.

## Validation

Required checks:

- Docker provider tests show stop/restart preserves the host directory and reset is destructive.
- Kubernetes provider tests render PVC-backed Runtime resources and leader-election settings.
- Workspace service tests reject missing provider workspace paths with explicit errors.
- Runner state sink tests preserve provider path authority and reject missing/mismatched paths.
- Deterministic azents E2E covers Agent Workspace bootstrap and reset action availability.
- Execution-policy E2E uses Admin/Public API setup, verifies save versus Apply and automatic
  restrictive convergence, and treats absent Docker or qualified Kubernetes prerequisites as
  unavailable evidence rather than passing enablement.

## Changelog

- **2026-07-27 (spec_version=7)** — Added lazy exact-Provider binding and initial policy snapshot attachment for pre-contract Runtime rows without workspace replacement.
- **2026-07-26 (spec_version=6)** — Added durable execution-policy target/applied snapshots, reset-free restrictive convergence, fixed Kubernetes topology isolation, and separate unqualified nested-engine storage.
- **2026-07-26 (spec_version=5)** — Added storage-preserving periodic convergence for desired-running Runtime workload image and configuration drift.
- **2026-07-03 (spec_version=3)** — Reflected Project-first Workspace browser ownership and registry-scoped Project root action boundary.
