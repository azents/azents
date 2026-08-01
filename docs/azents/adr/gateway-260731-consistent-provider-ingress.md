---
title: "Consistent Persistent Provider Ingress"
created: 2026-07-31
tags: [architecture, external-channel, gateway, slack, discord]
document_role: primary
document_type: adr
snapshot_id: gateway-260731
---

# gateway-260731/ADR: Consistent Persistent Provider Ingress

## Context

The confirmed
[gateway-260731/REQ](../requirements/gateway-260731-consistent-provider-ingress.md)
requires Slack Socket Mode and Discord Gateway to share one dedicated,
provider-neutral persistent-ingress runtime while preserving the current synchronous
External Channel ingestion boundary.

The intended topology was stated during the design of
[channel-260729/REQ](../requirements/channel-260729-responsive-context-preserving-conversations.md),
but it was omitted when that snapshot's ADR backlog was reduced. The resulting Design
preserved `SlackSocketManagerService` inside `AgentWorker` and retained the standalone
Discord Gateway Worker. The later provider-SDK lifecycle correction preserved the same
split topology.

The current managers are already process-neutral:

- both are dependency-injected from the same Azents server container;
- both discover configured connections from PostgreSQL;
- both claim, renew, and release database-fenced connection authority;
- both directly invoke `ExternalChannelTransportIngestionService`;
- both isolate customer-specific terminal connection state from their manager loop; and
- neither requires Agent Worker broker consumption or Session execution ownership.

No persistence migration or provider protocol replacement is required. The irreversible
choices are the runtime ownership boundary, top-level supervision contract, and
one-way deployment replacement.

## Decision Backlog

1. **Accepted: one provider-neutral persistent-ingress runtime owns both socket transport managers.**
2. **Accepted: required manager loops are fail-fast process dependencies while individual connection failures remain isolated.**
3. **Accepted: replace the split topology in one direction without a compatibility runtime.**

Direct invocation of the shared application service is already fixed by
`channel-260729/ADR-D1` and is not reopened here. Provider SDK lifecycle ownership and
connection fencing are already fixed by `channel-260731/ADR-D1` and
`channel-260731/ADR-D2` and are preserved.

## Decisions

### gateway-260731/ADR-D1 — One External Channel gateway owns persistent transports

Create one dedicated External Channel gateway runtime role that resolves and runs both
`SlackSocketManagerService` and `DiscordGatewayManagerService` from the existing Azents
dependency container.

The runtime is provider-neutral in its CLI name, shell launcher, Kubernetes Deployment,
container name, component labels, Helm values, and tests. Slack HTTP callbacks and
Discord signed interactions remain in the API server because they are request-driven
HTTP transports rather than persistent socket lifecycles.

`AgentWorker` no longer injects, starts, waits on, cancels, or reports failures for the
Slack Socket manager. Its lifecycle returns to Session broker consumption, Session
execution, recovery, provider-control settlement, and execution support.

This decision applies to `gateway-260731/REQ-1`, `REQ-2`, and `REQ-3`.

Keeping Slack Socket Mode in every general Worker is rejected because Worker scaling and
execution rollout should not change persistent transport ownership. Keeping a separate
Discord-only deployment is rejected because both managers implement the same
connection-discovery, lease-fencing, synchronous-ingestion, and long-lived supervision
role. Moving HTTP callbacks into the gateway is rejected because it would add network
routing without improving the shared application boundary.

### gateway-260731/ADR-D2 — Manager supervision is fail-fast and connection failures remain isolated

The External Channel gateway starts both manager `run()` coroutines under one shared
shutdown event. Either manager returning or raising before shutdown is an unexpected
loss of a required transport class, so the runtime stops and lets Kubernetes restart the
process. The runtime does not continue reporting ready with only Slack or only Discord
supervision active.

Each manager retains its existing per-connection task isolation. Credential, intent,
lease, provider, and reconnect outcomes update only that connection's sanitized durable
health and do not terminate the top-level manager. Therefore one customer configuration
does not remove the shared gateway pod from service.

Graceful shutdown marks readiness false first, sets the shared shutdown event, waits for
both managers to cancel connection tasks and release current authority, and then stops
the health server. Cancellation is propagated rather than classified as a manager
failure.

This decision applies to `gateway-260731/REQ-4` and `REQ-5`.

Treating manager completion as a healthy partial state is rejected because the pod would
silently stop supporting one provider. Crashing the process for an individual terminal
connection is rejected because customer configuration health is not process health.
Independent per-manager deployments are rejected because they recreate the split
provider topology this snapshot replaces.

### gateway-260731/ADR-D3 — Cut over by replacement and remove obsolete runtime identities

Replace the Discord-specific runtime surfaces rather than layering aliases or fallback
launchers:

- add an `externalchannelgateway` Python CLI and `externalchannelgateway.sh` launcher;
- render one `external-channel-gateway` Deployment and component label;
- replace `server.discordGateway` Helm values with
  `server.externalChannelGateway`;
- delete the Discord-specific CLI, shell launcher, template, and render tests; and
- remove Slack Socket manager composition and failure handling from `AgentWorker`.

Deployment uses the existing database leases as the handoff fence. The new gateway may
start before old pods fully terminate, but only one manager can retain authoritative
connection ownership. No dual-write, dual-read, legacy command alias, or long-lived
compatibility deployment remains after rollout.

This decision applies to `gateway-260731/REQ-6` and `REQ-7`.

Retaining deprecated chart keys or launcher aliases is rejected because the requester
requires removal of the obsolete topology and the project does not add compatibility
fallbacks without an explicit requirement. A staged dual-runtime mode is rejected
because database fencing already provides safe takeover and simultaneous topologies
would make ownership harder to verify.

## Consequences

- Persistent Slack and Discord connection availability no longer follows general Agent
  Worker replicas or rollout.
- The shared gateway image and process must include dependencies required by both
  managers, which the existing Azents server image already does.
- The gateway continues to depend on Redis for the current health readiness check even
  though provider connection authority remains in PostgreSQL.
- A top-level defect in either manager restarts the combined process and briefly affects
  both transport classes; database leases and provider SDK reconnect behavior provide
  recovery after restart.
- Helm consumers must use the new `server.externalChannelGateway` resource key.
- Operational dashboards and rollout checks must use the
  `external-channel-gateway` component identity.

## Risks

- Combining managers increases the blast radius of a manager-level programming failure.
  Fail-fast restart is deliberate, and focused supervision tests must distinguish this
  from isolated per-connection health.
- During rollout, old Worker pods may retain Slack leases and old Discord pods may retain
  Discord leases until shutdown or expiry. The new gateway must rely on existing fenced
  claims rather than assume immediate ownership.
- Consumers with explicit resource overrides under the old Helm key must update them;
  silent fallback would obscure whether the obsolete topology was actually removed.
