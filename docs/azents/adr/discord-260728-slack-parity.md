---
title: "Discord External Channel Slack Parity ADR"
created: 2026-07-28
tags: [discord, slack, external-channel, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260728
---

# Discord External Channel Slack Parity ADR

- Snapshot: `discord-260728`
- Document reference: `discord-260728/ADR`
- Requirements: [Discord External Channel Slack Parity Requirements](../requirements/discord-260728-slack-parity.md) (`discord-260728/REQ`)
- Prior decisions: [Discord Agent App Routing ADR](discord-260726-agent-app-routing.md) (`discord-260726/ADR`)

## Context

The current Discord adapter has provider ingress, Gateway fencing, basic message/file
delivery, and partial multi-page progress persistence. It does not complete several
Slack-equivalent journeys. The gaps are adapter-orchestration gaps, not a need for a
second External Channel domain: Slack and Discord already share canonical connections,
routes, resources, admissions, bindings, access records, invocation batches, Channel
Work, delivery attempts, and lifecycle fences.

The requester fixed the product rule: Slack behavior is the semantic source of truth and
all P0 through P2 parity work is in scope. Consequently, this ADR records derived
implementation decisions only. It does not introduce a new user-visible policy choice.

## Decisions

### D1. Reuse the canonical External Channel domain

**Decision**: Discord parity reuses the current connection, route, resource,
conversation-admission, interaction, binding, access, invocation-batch, Channel Work,
delivery, and lifecycle records. Provider-specific code translates Discord ingress and
presentation at adapter boundaries only.

**Rationale**: `discord-260728/REQ-1` through `REQ-8` require the same authorization,
immutable binding, durable delivery, and lifecycle outcomes as Slack. Creating a
parallel Discord Session, grant, binding, or work model would create behavior drift and
weaken the current canonical fences.

**Rejected alternative**: A Discord-specific conversation or execution domain. It would
duplicate authorization and lifecycle state and contradict the fixed Slack-equivalence
constraint.

### D2. Treat Discord interactions as transient presentations of durable claims

**Decision**: A verified Discord message command, component, autocomplete, or modal
submission commits only safe durable interaction and source-scope facts before its
initial response. The service immediately produces the required Discord-native selector
or acknowledgement response from the request-local capability, while route selection,
authorization, and execution remain durable-domain operations.

**Rationale**: `discord-260728/REQ-1`, `REQ-2`, and `REQ-7` require durable,
idempotent routing without storing Discord interaction tokens, signatures, or raw
payloads. The existing Slack interaction claim boundary is the reference contract.

**Rejected alternative**: Persisting interaction tokens or moving interaction execution
to the Gateway worker. Both would make transient provider capabilities durable authority
and violate the current ingress boundary.

### D3. Use one deterministic Discord thread as the conversation boundary

**Decision**: A root-message conversation uses the source message's one Discord thread;
an already-threaded conversation uses that existing thread. Thread provisioning occurs
only after a route is resolved, including before an approval control is delivered.
Resource labels retain separate source, parent, root, existing-thread, and delivery
channel identities.

**Rationale**: `discord-260728/REQ-3` requires the same immutable thread-scoped
conversation semantics as Slack. Route-first provisioning prevents selector-cancelled
source messages from producing unrelated threads while ensuring approval, Session link,
replies, progress, files, and cleanup all target the same thread.

**Rejected alternative**: Parent-channel delivery or requiring users to create a thread
first. Both break Slack-equivalent isolated-conversation behavior.

### D4. Reconcile Discord history through the existing bounded hydration contract

**Decision**: Discord thread/source-channel history uses the current resource hydration
cursor, high-watermark, reconciliation boundary, canonical revision, and activation
fencing contract. A provider adapter translates Discord pages into the existing
normalized-message persistence path.

**Rationale**: `discord-260728/REQ-4` requires context equivalence and no loss from
out-of-order or post-trigger events. Discord cannot bypass hydration merely because its
ingress uses Gateway rather than Slack callbacks.

**Rejected alternative**: Immediate activation with only the triggering Gateway event.
It drops prior context and creates behavior that is observably weaker than Slack.

### D5. Lower canonical Channel Work through existing Discord page projection state

**Decision**: Discord initial checking, Session link, progress create/update/delete,
final cleanup, and confirmed-deletion recovery use the existing durable delivery ledger
and Discord `ExternalChannelWorkProjectionPart` page planner. Event processor activation
and lifecycle paths must enqueue the same canonical work/projection intents rather than
using Slack-only helpers.

**Rationale**: `discord-260728/REQ-5` requires the same work lifecycle while Discord
uses bounded pages instead of a single Slack Block Kit message. Existing page projection
state already provides per-page ownership and delivery reconciliation.

**Rejected alternative**: A best-effort Discord status message outside Channel Work.
It would lose durable recovery, completion gating, and management visibility.

### D6. Expose Multi App management through provider-correct public surfaces

**Decision**: Discord receives the same public management operations as Slack. Shared
management services remain provider-neutral; API paths, OpenAPI operations, generated
clients, tRPC procedures, Workspace routes, and UI labels become provider-aware.

**Rationale**: `discord-260728/REQ-6` requires an administrator to manage Discord as a
first-class integration rather than through Slack-named endpoints.

**Rejected alternative**: Continue calling Slack-named operations for Discord. That is
not a provider-correct public contract and blocks client/UI parity.

### D7. Require end-to-end evidence before claiming parity

**Decision**: Completion requires deterministic Discord E2E coverage for the full
participant and administrator journeys, not only signature, Gateway checkpoint, or
primitive delivery tests.

**Rationale**: `discord-260728/REQ-8` defines observable parity. Unit tests cannot
prove cross-boundary thread targeting, authorization release, Session wake, progress
projection, and generated-client/UI behavior together.

**Rejected alternative**: Marking parity complete from adapter unit tests. The audit
showed that primitives can exist while the user-visible journey remains disconnected.

## Consequences

- No alternative authorization, Session, binding, work, or lifecycle model is added.
- No interaction token, raw signature, raw provider payload, credential, or attachment
  URL crosses the current durable redaction boundary.
- Discord resource labels and interaction projections may be extended additively; the
  canonical persistence graph remains the source of truth.
- Existing Slack flows remain unchanged while shared orchestration is generalized only
  where necessary to admit Discord.
- API schema and generated client changes are required for Discord Multi management.
- Current living specifications that describe unimplemented Discord parity behavior
  must be re-verified against the final implementation rather than treated as evidence
  of completion.
