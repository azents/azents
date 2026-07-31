---
title: "Consistent Persistent Provider Ingress Requirements"
created: 2026-07-31
updated: 2026-07-31
tags: [external-channel, gateway, slack, discord, reliability]
document_role: primary
document_type: requirements
snapshot_id: gateway-260731
---

# Consistent Persistent Provider Ingress Requirements

- Snapshot: `gateway-260731`
- Document reference: `gateway-260731/REQ`

## Problem

Slack Socket Mode and Discord Gateway provide the same External Channel conversation
capability, but their persistent connections currently run under different service
boundaries. Slack Socket Mode is coupled to general Agent Worker availability while
Discord uses a provider-specific Gateway deployment. This split contradicts the
confirmed provider-neutral ingress direction, gives equivalent transports different
operational lifecycles, and leaves the Discord-specific runtime as a permanent product
boundary.

A configured Slack or Discord connection needs one consistent persistent-ingress
runtime boundary while preserving the same synchronous provider-history, mailbox, and
Session handoff already shared by direct and socket-based delivery.

## Primary Actor

A Workspace or Agent administrator who configures a Slack Socket Mode or Discord
Gateway connection and expects supported provider messages to keep reaching the bound
Agent Session independently from general Agent Worker rollout and execution load.

## Primary Scenario

1. The External Channel persistent-ingress runtime starts and discovers configured
   Slack Socket Mode and Discord Gateway connections.
2. It acquires the existing fenced authority for each eligible connection and maintains
   the provider-supported socket lifecycle.
3. A supported provider message arrives and the transport directly invokes the shared
   synchronous External Channel ingestion operation.
4. The provider conversation and Session are resolved, provider history is accepted into
   the canonical mailbox, and Session execution is triggered before the transport
   reports successful handling.
5. Agent execution continues asynchronously in a general Agent Worker without that
   Worker owning either provider socket.

## Supporting Scenarios

- A general Agent Worker rolls, scales, or restarts without releasing or recreating
  healthy Slack Socket Mode or Discord Gateway connections.
- The persistent-ingress runtime rolls and existing lease fencing prevents concurrent
  authoritative owners while another replica takes over eligible connections.
- One customer connection becomes reconnect-required while other configured Slack and
  Discord connections continue operating in the shared runtime.
- Slack signed HTTP delivery remains in the API server and produces the same durable
  ingestion outcome without being routed through the persistent-ingress runtime.

## Goals

- Give Slack Socket Mode and Discord Gateway one provider-neutral runtime and deployment
  lifecycle.
- Decouple persistent provider connections from general Agent Worker execution.
- Preserve one shared synchronous ingestion behavior across Slack HTTP, Slack Socket
  Mode, and Discord Gateway.
- Preserve provider SDK lifecycle ownership, connection fencing, acknowledgement
  ordering, and content-free operational evidence.
- Remove obsolete provider-specific runtime identities after the replacement is active.

## Non-Goals

- Moving Slack HTTP callbacks or Discord signed interactions out of the API server.
- Changing provider-history collection, conversation read positions, mailbox identity,
  Session execution, routing, access approval, delivery, or file-transfer behavior.
- Changing Slack or Discord provider-visible message and interaction behavior.
- Adding a durable transport queue, internal HTTP relay, or compatibility worker.
- Combining External Channel ingress with the unrelated runtime container-policy
  gateway.
- Changing connection credential formats or persisted lease schemas.

## Requirements

### REQ-1. Provider-neutral persistent-ingress runtime

Slack Socket Mode and Discord Gateway connections must run under one dedicated External
Channel persistent-ingress runtime boundary.

**Acceptance criteria**

- One runtime role starts and supervises both Slack Socket Mode and Discord Gateway
  connection managers.
- The general Agent Worker does not start, supervise, or own Slack Socket Mode
  connections.
- No Discord-only deployment or runtime entrypoint remains in the active topology.
- The runtime role and deployment identity describe External Channel ingress rather than
  one provider.

### REQ-2. Shared synchronous ingestion outcome

Socket-delivered Slack and Discord messages must retain the same admitted-request
outcome as direct provider delivery.

**Acceptance criteria**

- Both socket managers directly invoke the existing provider-neutral ingestion
  application boundary after provider-specific authentication, authority checks, and
  trigger projection.
- Successful handling still means the provider conversation and Session are resolved,
  one canonical mailbox input is accepted, and Session execution is triggered.
- Agent model execution and reply delivery remain asynchronous after that handoff.
- No internal HTTP relay or provider-specific duplicate conversation orchestrator is
  introduced.

### REQ-3. Independent Agent Worker lifecycle

Persistent provider connection availability must not depend on the lifecycle of general
Agent Worker processes.

**Acceptance criteria**

- Agent Worker startup and shutdown contain no Slack Socket Mode manager dependency or
  task.
- Agent Worker scaling or replacement does not change persistent connection ownership.
- Session broker consumption and Agent execution remain unchanged after socket ownership
  moves.

### REQ-4. Fenced connection ownership and handoff

Runtime replacement and concurrent replicas must preserve the existing single-authority
connection contract.

**Acceptance criteria**

- Existing Slack and Discord lease claims, renewals, generation checks, release behavior,
  and stale-owner rejection remain enforced.
- Shutdown stops new transport admission before owned connections are released.
- A replacement replica can claim an expired or released connection without persisted
  provider socket session state.
- No deployment interval requires both the old split topology and the replacement
  topology to own connections concurrently.

### REQ-5. Isolated connection health and truthful process health

The shared runtime must distinguish customer connection state from failure of its own
required supervision loops.

**Acceptance criteria**

- A credential, intent, authorization, or provider-specific terminal state affects only
  the corresponding connection and retains the current sanitized reconnect-required
  outcome.
- Recoverable connection failures retain the current degraded and reconnect behavior.
- The runtime remains healthy while its required manager supervision loops are running,
  even when one customer connection requires intervention.
- Unexpected termination of a required top-level manager causes the runtime process to
  stop rather than continue reporting ready without that transport class.

### REQ-6. Complete topology replacement

The migration must leave one active persistent-ingress topology and remove obsolete
ownership surfaces.

**Acceptance criteria**

- Helm renders the provider-neutral gateway deployment and command.
- Helm values and schema no longer expose the Discord-specific gateway component.
- The Discord-specific CLI launcher and shell entrypoint are removed.
- Tests assert absence of the old deployment name, command, and Agent Worker socket
  dependency.
- Living External Channel specs describe the provider-neutral runtime as current
  behavior.

### REQ-7. Regression safety

The topology replacement must preserve supported External Channel behavior and be
verifiable before release.

**Acceptance criteria**

- Automated tests cover combined runtime startup, manager failure propagation, graceful
  shutdown, Worker composition, Helm rendering, and removal assertions.
- Existing focused Slack Socket Mode and Discord Gateway manager tests continue to pass.
- Deterministic External Channel E2E coverage proves both providers still reach the
  canonical mailbox and Session execution path.
- Repository quality checks and required CI pass on the pull request head.

## Fixed Constraints

- The accepted `channel-260729/ADR-D1` direct application-service boundary remains in
  force; trusted processes do not relay socket triggers through internal HTTP.
- The accepted `channel-260731` provider-SDK lifecycle, durable admission,
  multi-replica fencing, and sanitized diagnostic boundaries remain in force.
- Slack HTTP and Discord signed-interaction routes remain API-server responsibilities.
- Provider credentials, endpoints, payloads, message content, IDs, and transient URLs
  must not enter logs, health responses, tracked evidence, or command arguments.
- The replacement uses the existing Azents server image and dependency container.
- The work is delivered in a separate pull request from inbound-storage replacement and
  deployment recovery, and is not merged without explicit requester approval.

## Open Assumptions

- The existing Slack and Discord lease implementations are process-neutral and require
  no data migration when their manager host process changes.
- One replica remains the default deployment size; existing database fencing continues
  to protect correctness if the runtime is scaled above one replica.
- The combined runtime can use the current health server without exposing per-connection
  provider details.

## Confirmation

Confirmed by the requester on 2026-07-29 through the explicit direction to generalize
the Discord Gateway runtime so it also runs Slack Socket Mode, and through approval of
direct shared application-service invocation. Reconfirmed on 2026-07-31 when the
requester identified the surviving split topology as omitted gateway work and directed
that it be implemented after deployment recovery in a separate change.
