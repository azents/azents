---
title: "Multi-Agent Slack App Routing"
created: 2026-07-25
tags: [slack, external-channel, agent, frontend, security, architecture]
document_role: primary
document_type: adr
snapshot_id: slackapp-260725
---

# Multi-Agent Slack App Routing

- Snapshot: `slackapp-260725`
- Document reference: `slackapp-260725/ADR`
- Requirements: [Multi-Agent Slack App Routing Requirements](../requirements/slackapp-260725-multi-agent-routing.md) (`slackapp-260725/REQ`)

## Status

Accepted. `slackapp-260725/ADR-D1` through `ADR-D8` define the approved direction.

## Context

`slackapp-260725/REQ` preserves an Agent-admin-owned Single App for one Agent and adds
a separate Workspace-admin-owned Multi App for zero or more Agents. The product
experiences and lifecycle owners are distinct, but both modes need the same provider
connection, Agent route, authorization, binding, and delivery machinery.

The existing External Channel implementation already separates a Workspace-owned
provider connection record from an Agent route. It does not yet record the App's
management mode: every active Slack connection is constrained to one dedicated route
and every management operation is addressed through an Agent. Multi Apps therefore
need an explicit Workspace management boundary and an explicit routing decision
before an unbound Slack conversation enters the route-scoped authorization and
binding flow.

## System-Grounded Framing

- `external_channel_connections` already owns Workspace identity, Slack App and Team
  identity, transport, encrypted credentials, capabilities, health, Socket lease, and
  terminal disconnect state independently from an Agent.
- `external_channel_agent_routes` already relates a connection to an Agent, but a
  partial unique index permits only one `dedicated` route per connection. The
  `platform` route mode is reserved but unused.
- The connection has no durable Single App or Multi App management mode. Its
  `workspace_id` is a tenant boundary and does not by itself express which
  administrators own the product lifecycle.
- Event admission already identifies and authenticates the receiving connection by
  Slack App and Team identity before asynchronous processing. This boundary does not
  need an Agent to authenticate the provider event.
- Unbound event processing currently selects one routable route directly from the
  connection with an ordered `limit(1)`. Multiple routes would make this selection
  ambiguous and could route to the wrong Agent.
- Provider resources are connection-scoped. Bindings connect one resource and one
  route to one Agent Session. Existing active-binding uniqueness is per
  `(resource_id, route_id)`, so multiple routes could currently create more than one
  active binding for the same Slack thread.
- Pending context and access requests are route-scoped. Agent grants and blocks are
  already Agent-scoped and can be reused after an Agent has been selected.
- Existing binding-originated delivery and file authorization reload the route,
  Agent, connection, Session, and binding from durable state. Stable route identity is
  therefore embedded in retained history and lifecycle fences.
- Connection disconnect currently accepts an Agent-qualified management command and
  terminalizes all connection-owned resources, bindings, work, and credentials. Its
  implementation already matches Single App removal semantics but assumes the
  qualifying Agent is the sole lifecycle owner.
- Agent decommission eventually removes direct Agent-owned routes after binding and
  Session lifecycle cleanup. There is no separate operation for removing an Agent
  only from a reusable App catalog while preserving historical route references.
- Public management APIs, generated clients, tRPC, localized copy, and the complete
  External Channel management UI are Agent-scoped. No Workspace Slack App management
  surface exists.
- Slack message shortcuts and interactive Agent-selection payloads are not admitted
  by the current provider ingress. The generated Manifest contains Events API and bot
  configuration but no shortcut/interactivity configuration.
- No durable channel-default record exists. Current resources represent tracked Slack
  threads rather than a complete channel configuration directory.
- Existing connection and route rows can be migrated in place without reinstalling
  Slack or changing provider installation identity.

## Requirement Gap Summary

| Requirements | Current gap |
| --- | --- |
| `slackapp-260725/REQ-1`, `REQ-4` | Connections have a Workspace tenant boundary, but there is no Multi App mode, Workspace management API, or Workspace-authorized lifecycle. |
| `slackapp-260725/REQ-2` | Route persistence exists, but there is no explicit mode that retains one route for Single Apps while permitting zero or many routes for Multi Apps. |
| `slackapp-260725/REQ-3` | The current Agent-qualified setup closely matches Single App creation, but the connection does not explicitly encode Single App ownership or association-removal semantics. |
| `slackapp-260725/REQ-5`, `REQ-6` | There is no App Agent catalog or signed Slack shortcut and modal flow. |
| `slackapp-260725/REQ-7`, `REQ-8` | There is no channel-default state or unconfigured-channel selection workflow. |
| `slackapp-260725/REQ-9` | Binding identity is reusable, but uniqueness does not prevent different routes from binding the same resource concurrently. |
| `slackapp-260725/REQ-10` | Existing approval retention is route-scoped and reusable after selection, but no pre-route selection request exists. |
| `slackapp-260725/REQ-11` | Whole-connection disconnect exists, but mode-specific Single App removal and Multi App association removal do not share one impact-projected lifecycle. |
| `slackapp-260725/REQ-12` | Existing rows preserve all required identities and can become Single Apps, but schema, APIs, and UI need a coordinated in-place migration. |
| `slackapp-260725/REQ-13` | Connection admission and binding routing are strongly fenced, but unbound multi-route selection and cross-route binding uniqueness are not implemented. |

## Decision Backlog

The following decisions must be accepted one at a time before the Design is written.

1. **App mode and Agent association identity** — how Single Apps and Multi Apps share
   one connection-and-route model while enforcing different ownership and cardinality.
2. **Unbound conversation selection** — ownership and durable identity for channel
   defaults, shortcut selections, mention-triggered selectors, and retained source
   messages before a route is chosen.
3. **Mode-specific removal** — how Single App removal and Multi App Agent removal
   affect connections, defaults, bindings, and retained history.
4. **Management and authorization surface** — separate Agent-admin-owned Single App
   and Workspace-admin-owned Multi App experiences and permissions.
5. **App mode immutability** — whether an existing Single App can move into
   Workspace-owned Multi App management.
6. **Slack interaction admission** — signature verification, idempotency, modal state,
   expiry, and retry behavior for shortcuts and selection submissions.
7. **Migration and rollout** — schema ordering, generated API transition, UI rollout,
   and evidence that existing installations and bindings remain uninterrupted.
8. **Selected Agent presentation** — how Slack participants distinguish the selected
   Agent while every Agent shares one Slack bot identity, including initial
   selection, replies, approval states, errors, and retained thread context.

## Decisions

### slackapp-260725/ADR-D1 — Share one connection-and-route model across App modes

Single Apps and Multi Apps use the same External Channel connection and Agent route
identities. The connection records its durable management mode, and the Agent route
remains the association between that connection and one Agent.

- A Single App permits exactly one durable Agent route. Its product lifecycle owner is
  the administrator set of that route's Agent.
- A Multi App permits zero, one, or many durable Agent routes. Its product lifecycle
  owner is the authorized Workspace administration boundary.
- Enforce one durable association identity for each `(connection_id, agent_id)` pair.
- Enforce mode-aware route cardinality instead of using separate connection, binding,
  authorization, or delivery implementations.
- Preserve existing route IDs and every binding, pending context, approval, delivery,
  and retained-history reference during migration.
- Multi App routes have an explicit catalog-availability lifecycle that prevents a
  removed association from new selection without deleting its historical identity.
- Keep provider connection health and Agent lifecycle independent from catalog
  availability.

**Affected requirements**: `slackapp-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-9`, `REQ-11`, `REQ-12`, `REQ-13`.

**Rejected**

- Add a separate App–Agent catalog table while retaining Agent routes. This would
  represent the same connection and Agent relationship twice and require ongoing
  association-to-route consistency.
- Implement Single Apps and Multi Apps as separate runtime integration models. Their
  ownership and cardinality differ, but their provider and execution invariants are
  the same.
- Remove Agent routes and point binding and authorization records directly to the
  connection and Agent. This would require broad identity migration across retained
  lifecycle and history records.

### slackapp-260725/ADR-D2 — Admit unbound conversations before route selection

One durable conversation admission owns the selection lifecycle for an unbound
provider conversation before an Agent route is chosen.

- Persist the canonical connection-scoped resource, message, message revision,
  attachment metadata, and immutable external-principal provenance before route
  selection.
- Add a durable conversation admission that references the resource and source
  message, records the invocation origin and initiating external principal, and may
  later record the selected route. It does not infer an Azents User from the Slack
  participant.
- Permit at most one active admission for an unbound resource. A default resolution,
  shortcut selection, or mention-triggered selection must use this same admission
  boundary rather than create competing candidate-route state.
- Store each channel default as a connection-and-provider-channel association to one
  Agent route. A default is effective only while its route remains selectable; an
  invalid default resolves as unconfigured and never falls back to another route.
- After a route is selected, materialize route-scoped pending context and, when
  required, an access request from the retained source message. Approval-required
  selection does not create an Agent run, Agent Session, or binding before access is
  granted.
- Once access permits invocation, lock the provider resource and atomically create
  the Agent Session and active binding for the selected route.
- Enforce at most one active binding per provider resource, independently of route.
  A later selection attempt against an already bound resource cannot replace its
  route or Agent Session.

`slackapp-260725/ADR-D6` defines provider-payload idempotency, admission expiry, and
retry mechanics without changing this durable ownership boundary.

**Affected requirements**: `slackapp-260725/REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`,
`REQ-9`, `REQ-10`, `REQ-11`, `REQ-13`.

**Rejected**

- Represent Agent selection as a provisional binding with nullable route or Agent
  Session identity. This would weaken the binding contract and spread incomplete
  binding handling across delivery, hydration, and lifecycle code.
- Keep selector state only in Slack interaction payloads and retrieve the source
  message after selection. This would make source retention, attachment continuity,
  approval resumption, and retries depend on later provider availability.
- Create route-scoped pending context for every candidate Agent before selection.
  This would duplicate retained content and authorization state and could allow
  competing routes to claim the same provider conversation.

### slackapp-260725/ADR-D3 — Apply mode-specific removal with terminal bindings

Removing an Agent relationship revokes its ability to invoke the Agent for both new
and already bound conversations. The connection lifecycle then depends on App mode.

- Before confirmation, project the channel defaults and active bindings affected by
  a Single App removal, Multi App association removal, or whole Multi App disconnect.
- Removing the sole Agent association from a Single App terminally disconnects the
  whole connection, removes its credentials and transport lease, and preserves its
  terminal connection and route identity for retained history.
- Removing one Agent association from a Multi App marks that preserved route
  unavailable for new catalog selection while keeping the connection and its other
  routes active.
- Treat every channel default that references the unavailable route as unconfigured;
  never replace it with another route.
- Terminalize the route's active bindings with an explicit relationship-removal
  reason. Later messages in those Slack threads cannot invoke the Agent and receive
  an explicit unavailable response rather than silent failure or fallback routing.
- Preserve the binding, Agent Session, canonical messages, pending and decision
  records, and retained history for audit and continuity of identity. Relationship
  removal is not data deletion.
- Reassociating an Agent with a Multi App may re-enable its preserved route for new
  selections but does not silently reactivate terminalized bindings. A new Slack
  conversation is required.
- A removed Single App cannot be revived by adding an Agent back to its terminal
  connection. A new Single App connection is required.
- Agent decommission, connection disconnection, participant blocking, and other
  broader security lifecycles remain independent and may still make additional
  resources unavailable.

**Affected requirements**: `slackapp-260725/REQ-2`, `REQ-7`, `REQ-9`, `REQ-11`,
`REQ-13`.

**Rejected**

- Keep existing bound conversations live after removing the Agent from the App. An
  administrator who disconnects the relationship reasonably expects that App to stop
  invoking the Agent, including through previously linked threads.
- Keep a zero-Agent Single App connected. This would contradict the Agent-owned
  lifecycle and make the connection ownerless in its management experience.
- Require the administrator to choose relationship semantics for every removal. This
  would make the same catalog operation produce inconsistent execution lifecycles and
  increase the risk of unintentionally retaining access.

### slackapp-260725/ADR-D4 — Separate Single App and Multi App management

Single App and Multi App ownership is determined by the management surface and App
mode, not by the individual who supplies Slack credentials.

- Agent settings create and manage Single Apps. Every current administrator of the
  sole associated Agent can create, inspect, validate, update credentials, reconnect,
  or disconnect the Single App.
- Workspace integration settings create and manage Multi Apps. Only a user with the
  required Workspace administration permission can create, inspect, validate, update
  credentials, reconnect, disconnect, manage Agent associations, or change channel
  defaults for a Multi App.
- Multi App associations may be shown from an Agent context, but their lifecycle
  remains managed through the Workspace experience.
- Do not expose one combined setup flow with a technical Single App or Multi App mode
  selector. Entering from Agent settings creates a Single App; entering from
  Workspace integration settings creates a Multi App.
- Do not create registrant-specific App ownership. Single App authority follows the
  current Agent administrator set, and Multi App authority follows the current
  Workspace administration permission.
- A Slack-side channel-default action must complete under an explicitly
  authenticated Azents Workspace administrator. The Slack sender is immutable
  external-principal provenance and is not inferred to be an Azents User.

`slackapp-260725/ADR-D6` defines the authenticated Slack-to-Azents handoff without
changing these authorization boundaries.

**Affected requirements**: `slackapp-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-7`, `REQ-11`, `REQ-13`.

**Rejected**

- Make every App Workspace-admin-owned. This would remove the Agent-admin-owned
  Single App experience.
- Let an Agent administrator create or manage a Multi App solely because one of their
  Agents is associated with it. This would cross the Workspace-owned lifecycle
  boundary.
- Assign App management permanently to the individual who entered the credentials.
  Ownership must follow current Agent or Workspace administration rather than a
  historical creator.

### slackapp-260725/ADR-D5 — Keep App mode immutable

The management mode of an External Channel connection is fixed when the connection is
created.

- A Single App cannot be promoted, transferred, or retagged as a Multi App.
- Shared use requires an authorized Workspace administrator to create a separate
  Multi App connection through the Workspace experience.
- Existing Single App route, binding, Agent Session, approval, message, and history
  identities are not moved or copied into the new Multi App.
- Creating a Multi App does not alter or remove an existing Single App. The Agent
  administrator must explicitly remove the Single App when it is no longer needed.
- The common internal connection and route implementation does not introduce a mode
  transition state machine.

**Affected requirements**: `slackapp-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-11`, `REQ-12`.

**Rejected**

- Promote a Single App in place while preserving its connection and route identity.
  Although technically feasible, this would blur the separate Agent-owned and
  Workspace-owned product experiences and change lifecycle authority in place.
- Automatically promote a Single App when another Agent is added. This would violate
  the Workspace authorization required to create a Multi App.

### slackapp-260725/ADR-D6 — Extend durable admission to Slack interactions

Slack shortcuts, block actions, modal submissions, and Socket Mode interactive
envelopes use the existing External Channel rule: authenticate the provider, commit
an idempotent durable admission, and only then acknowledge the provider.

- HTTP interaction admission verifies the raw request signature and replay window
  before parsing the form-encoded interaction payload.
- Socket Mode interaction admission requires the currently owned active connection
  lease and uses the provider envelope identity for acknowledgement and
  deduplication.
- Use a connection-scoped digest of the verified HTTP request body or the Socket Mode
  envelope ID as the transport idempotency identity.
- Persist only a bounded, non-secret interaction projection. Do not retain raw
  payloads, response URLs, tokens, or other provider capability-bearing values.
- Commit an opaque server-side interaction state before acknowledgement. Slack modal
  metadata carries only that opaque identity and is never an authorization source of
  truth.
- Keep the shortcut fast path bounded to durable admission and the provider call
  required to open the modal within Slack's deadline. Source hydration, file work,
  catalog enrichment, and execution remain asynchronous.
- Apply modal submissions as a single durable state transition. Duplicate callbacks
  return the existing result and cannot select another route or create another Agent
  invocation.
- Expired or invalid interaction state creates no binding, Agent Session, access
  grant, or Agent run. The participant must start a new interaction.
- Use provider view-version fencing for asynchronous modal updates so stale work
  cannot replace newer participant-visible state.
- A Slack-side channel-default action creates an opaque, expiring handoff to an
  authenticated Azents Workspace management action. Slack sender provenance is not
  converted into an Azents User identity.

The conversation admission from `slackapp-260725/ADR-D2`, resource-wide active
binding uniqueness, and invocation idempotency remain the final execution fences
after provider-interaction deduplication.

**Affected requirements**: `slackapp-260725/REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`,
`REQ-9`, `REQ-10`, `REQ-13`.

**Rejected**

- Complete catalog loading, source hydration, authorization, and binding creation
  synchronously inside the provider callback. This would put durable business work
  inside Slack's acknowledgement deadline and amplify retry risk.
- Store authoritative selection or permission state only in Slack modal metadata.
  This would weaken expiry, relationship-change, authorization, and duplicate
  callback fences.
- Acknowledge an interaction before its idempotent admission is committed. A process
  failure after acknowledgement could otherwise lose the participant action.

### slackapp-260725/ADR-D7 — Enable Multi Apps only after mode-aware rollout

Multi App creation is enabled only after additive schema migration and complete
deployment of mode-aware API and worker runtimes.

1. **Additive schema foundation**
   - Add immutable App mode and backfill every existing connection as a Single App.
   - Preserve every existing connection, route, resource, binding, Agent Session,
     approval, message, credential, and history identity.
   - Add the association, conversation admission, interaction admission, channel
     default, and resource-wide binding constraints required by the accepted
     decisions.
   - Validate existing Single App invariants and fail the new migration on ambiguous
     data rather than infer or rewrite ownership.
   - Do not modify an executed migration and do not permit Multi App creation in this
     phase.
2. **Mode-aware runtime**
   - Deploy every API and worker path that reads App mode, validates a Single App's
     sole route, and routes a Multi App only through a binding, channel default, or
     durable participant selection.
   - Remove every connection-only `limit(1)` routing dependency before Multi App data
     can exist.
   - Deploy mode-specific management, removal, interaction, authorization, and
     delivery behavior while keeping Multi App creation unavailable.
3. **Multi App product enablement**
   - Enable Workspace Multi App APIs and UI only after every runtime instance is
     mode-aware.
   - Regenerate OpenAPI specifications and Python and TypeScript clients through
     their generators before frontend use.
   - Permit zero or multiple Multi App routes only in this final phase.

Existing Agent-scoped management remains the formal Single App product surface rather
than a legacy compatibility fallback.

Before Multi App creation, an application rollback may return to the prior runtime
because only Single App-compatible data exists. After any Multi App or multi-route
data exists, rollback to a connection-only routing runtime is prohibited. Operators
must stop new Multi App mutations and apply a forward fix without downgrading or
stamping the production database.

**Affected requirements**: `slackapp-260725/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`,
`REQ-9`, `REQ-11`, `REQ-12`, `REQ-13`.

**Rejected**

- Enable schema, multi-route creation, old and new runtime code, generated clients,
  and UI in one rolling deployment. An older worker could select an arbitrary route
  from a Multi App.
- Build Multi Apps in separate shadow connection and routing tables. This would
  duplicate provider, authorization, binding, and delivery lifecycles contrary to
  the shared-model decision.

### slackapp-260725/ADR-D8 — Use only a bold Agent name and optional icon override

Agent presentation in Slack remains minimal and does not introduce a separate visual
identity system.

- Begin every Agent-authored Slack output with the current Agent name in bold as its
  first visible content.
- Begin the provider fallback text with the same Agent name so notifications and
  non-Block-Kit presentation retain the identity.
- When the current Agent has an image, the image resolves to a provider-safe URL, and
  the connection has Slack message-customization capability, override that outbound
  message's icon with the Agent image.
- If the image or capability is unavailable, use the Slack App's default bot icon and
  continue delivery without degradation or setup failure.
- Do not override the Slack bot username or create another bot user.
- Do not add an Agent banner, `Azents Agent` label, connection notice, description,
  access badge, or presentation snapshot. Resolve the current canonical Agent name
  and image for each outbound delivery.
- Include Slack message-customization capability in new App setup guidance and
  capability validation, but do not require an existing App to reinstall or
  reauthorize solely for Agent imagery.

**Affected requirements**: `slackapp-260725/REQ-5`, `REQ-6`, `REQ-10`, `REQ-12`,
`REQ-13`, `REQ-14`.

**Rejected**

- Add persistent context labels, connection banners, descriptions, or binding-time
  presentation snapshots. These add repeated visual structure beyond the requested
  Agent distinction.
- Override the Slack bot username together with the icon. The provider bot name
  remains the stable App identity.
- Require existing Apps to gain message-customization scope before they can continue
  delivering messages.

## Consequences

- Existing dedicated connections and routes migrate in place as Single Apps owned
  through their current Agent administrator set.
- Every new connection receives an immutable Single App or Multi App management mode
  from its creation surface.
- Supporting shared use after Single App setup requires a separate Multi App rather
  than a connection ownership transition.
- Multi Apps add mode-aware cardinality and Workspace management without creating a
  second provider or execution pipeline.
- Single App routing resolves its sole eligible route, while Multi App routing
  requires a channel default or participant selection.
- New-selection queries must consider App mode and route availability.
- Connection-only lookup can no longer select one route with `limit(1)`.
- Inbound processing must persist the route-neutral provider resource and source
  message before resolving a default or waiting for participant selection.
- Message persistence and route-scoped pending-context projection become separate
  steps connected by the conversation admission.
- Binding creation must replace the current per-route active uniqueness with a
  resource-wide active uniqueness fence.
- App–Agent removal becomes an impact-projected lifecycle transition rather than a
  route-row deletion.
- Single App Agent removal disconnects the whole connection; Multi App Agent removal
  affects only that route and its bindings.
- Single App and Multi App management require separate API and UI entry points even
  though they operate on the same internal connection and route records.
- Existing HTTP signature verification and durable event admission become shared
  primitives for Events API and interactive HTTP payloads.
- The Socket Mode client must admit and acknowledge interactive envelopes in addition
  to its current Events API envelopes.
- Provider interaction admission, conversation admission, authorization, and binding
  remain distinct retry-safe lifecycle stages.
- Multi App creation requires a later enablement release after all mode-aware
  runtimes are deployed and verified.
- Once Multi App data exists, deployment rollback cannot reintroduce the old
  connection-only route lookup.
- Outbound Slack message and file delivery share one minimal Agent-name rendering
  wrapper and an optional icon override capability.
- Connection capability snapshots must distinguish message customization from
  ordinary message posting so missing scope remains a safe fallback.
