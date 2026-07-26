---
title: "Discord Agent App Routing Implementation Plan"
created: 2026-07-26
updated: 2026-07-26
tags: [discord, external-channel, implementation, backend, frontend, infra, e2e]
---

# Discord Agent App Routing Implementation Plan

- Snapshot: `discord-260726`
- Requirements: [discord-260726/REQ](../requirements/discord-260726-agent-app-routing.md)
- ADR: [discord-260726/ADR](../adr/discord-260726-agent-app-routing.md)
- Design: [discord-260726/DESIGN](../design/discord-260726-agent-app-routing.md)
- Stack prefix: `discord`

## Summary

This plan delivers customer-owned Discord Single and Multi Apps through the canonical
External Channel domain. It adds Discord-specific provider adapters and a dedicated
Gateway Worker while preserving the existing Slack contract during phased migration.

PostgreSQL remains canonical for connection, route, admission, resource, binding,
authorization, Session, work, action, and delivery state. The Discord Gateway, signed
HTTP interaction callbacks, worker wake-ups, and transient interaction tokens only
transport or wake durable work.

## Delivery Rules

- Every branch is stacked on the immediately previous branch and is opened before CI
  monitoring begins.
- Existing applied migrations are immutable. Every new revision is generated with
  `alembic revision` and receives Docker-backed migration coverage where it changes
  retained External Channel state.
- API schemas originate in source models. OpenAPI and generated Python and TypeScript
  clients are regenerated; generated files are never edited manually.
- Discord creation remains rollout-disabled until the required provider-aware readers,
  Gateway Worker deployment, callback base URL, deterministic fake, and essential E2E
  coverage are complete.
- Live Discord credentials, guilds, `live_external`, and production certification are
  explicitly out of scope for this snapshot.

## Stack

| PR | Branch role | Scope | Depends on | Primary validation |
| --- | --- | --- | --- | --- |
| 1/14 | Design baseline | Approved Requirements, ADR, Design, and generated docs index | `main` | Snapshot validation and docs hooks |
| 2/14 | Implementation plan | This plan and stack/validation contracts | 1/14 | Snapshot validation and docs hooks |
| 3/14 | Provider foundation | Provider enum, tagged Discord contracts, ingress profile, configuration/App-claim/lease and delivery-part schema foundation, adapter registry seams | 2/14 | Migration round trips, repository invariants, Slack regression |
| 4/14 | Connection management | Discord Single/Multi setup contracts, validation, management API, permissions, OpenAPI/client generation, rollout-disabled lifecycle | 3/14 | API/service tests, generated-client drift, management regression |
| 5/14 | Gateway Worker | Dedicated Worker entrypoint/deployment, claim capacity, generation fences, session checkpoint, Resume/Identify/gap health, deterministic Gateway fake | 4/14 | Lease/checkpoint tests and fake protocol tests |
| 6/14 | Interactions and routing | Ed25519 endpoint, PING, message command, selector controls, opaque handoffs, route-resolved thread provisioning, approval continuation | 5/14 | Signed ingress, routing race, thread reconciliation tests |
| 7/14 | Messages and files | Gateway normalization, history hydration, metadata-only attachments, explicit inbound download, permission and Message Content health | 6/14 | Message/revision, hydration, file authority, capability tests |
| 8/14 | Delivery bundles | Ordered reply/control/progress parts, nonce-aware Discord writes, Channel Work projection pages, outbound files, cleanup outcomes | 7/14 | Bundle planning, partial/unknown, file batching, Slack delivery regression |
| 9/14 | Web surfaces — credential replacement | Shared management credential-replacement surface, generated client integration, authority/secret-redaction states | 8/14 | Component tests and management regression |
| 10/14 | Web surfaces — Single connection forms | Agent-owned Discord Single setup and repair form | 9/14 | Component tests and focused Web checks |
| 11/14 | Web surfaces — Multi connection forms | Workspace-owned Discord Multi setup and repair form | 10/14 | Component tests and focused Web checks |
| 12/14 | Deterministic E2E validation | Discord fake integration, essential product E2E, validation evidence, responsible fixes | 11/14 | Required deterministic E2E matrix |
| 13/14 | Spec promotion | `/spec-review`, living-spec updates, snapshot implementation marker after complete verification | 12/14 | Spec review and final behavior comparison |
| 14/14 | Cleanup | Remove temporary plans and compatibility readers after the stack is complete | 13/14 | Full regression and stale-reference search |

## Phase Dependencies and Boundaries

### Provider foundation

The foundation phase introduces provider-neutral data needed by all later phases before
any active Discord routing exists:

- `discord` provider identity and credential/configuration tagged unions;
- explicit ingress profile rather than a single user-selected transport value;
- explicit connection configuration generation and current App-identity claim;
- provider-neutral ingress lease with generation, required configuration/claim fence,
  checkpoint, and gap state;
- resource provisioning intent; and
- delivery part and Channel Work projection-part persistence.

Slack readers remain supported during compatibility migration. No Discord credentials,
callback endpoints, or Gateway sessions are activated in this phase.

### Connection management

The management phase establishes the separate Agent-owned Single and Workspace-owned
Multi product contracts. It adds setup state, secret redaction, provider validation,
identity immutability, compatible credential replacement, App claim conflict handling,
route/default impact previews, and generated clients. It preserves the current
permission boundary: Workspace Owner and Manager manage Multi Apps; Agent
administrators manage only their Single Apps.

### Gateway and ingress routing

Gateway and interaction phases create the two Discord ingress paths:

- a dedicated leased Worker for Gateway message Dispatches; and
- direct API HTTP ingress for signed interactions.

Every safely handled Gateway Dispatch advances resumable sequence state. Canonical
admissions use a bounded session-and-sequence event key and retain normal resource and
message idempotency. HTTP interaction tokens remain request-local and never enter
PostgreSQL, logs, broker payloads, or retry queues.

Thread provisioning occurs after route selection and before access continuation. A root
message uses its deterministic prospective thread identity for create ambiguity
reconciliation. A failed or unknown provision never creates a binding or Session.

### Messages, files, and delivery

The message phase adds Discord normalization, Message Content health, bounded history,
attachment metadata, and explicit download. The delivery phase lowers one canonical
reply or Channel Work snapshot into ordered Discord parts. Every part intent commits
before a provider call. Discord Create Message calls use a deterministic bounded nonce
with `enforce_nonce=true` where available; ambiguity outside the bounded provider
window becomes `unknown` and is not replayed.

### Web and validation

Web work starts only after stable management API contracts exist. Essential E2E drives
public/admin APIs, real Azents processes, the deterministic Discord fake, and the
Gateway Worker without direct product-table writes. Validation is a feature delivery
phase, not a live-provider test substitute.

## Data, API, and Runtime Impact

| Area | Planned changes | First phase |
| --- | --- | --- |
| Persistence | Provider enum, configuration generation, App claim, ingress lease/checkpoint, provisioning attempts, delivery parts, work projection parts | 3/14 |
| Provider contracts | Tagged credential/configuration/capability models and explicit adapter registry | 3/14 |
| Public API | Discord Single and Multi setup, repair, route/default, health, and management operations | 4/14 |
| Generated clients | Public OpenAPI dump plus Python and TypeScript regeneration | 4/14 |
| Runtime | Dedicated Discord Gateway Worker and Helm deployment/rollout gate | 5/14 |
| Ingress | Ed25519 interaction endpoint and Gateway Dispatch admission | 5/14, 6/14 |
| Conversation | Message command, selector, thread provisioning, access continuation | 6/14 |
| Files | Attachment metadata, current-URL materialization, outbound multipart planning | 7/14, 8/14 |
| Delivery | Ordered parts, nonce-aware calls, progress pages, cleanup/recovery | 8/14 |
| Web | Credential replacement, separate Single/Multi setup, and repair/management surfaces | 9/14-11/14 |

## Test Strategy

### Required focused coverage

Each implementation phase adds focused tests for its new authority boundary. Required
coverage includes migration preflight/round trip/downgrade safety, App claim uniqueness,
configuration and lease fencing, route/default/binding lock order, signature
verification, component principal scope, Message Content loss, Gateway Resume/gap,
thread create ambiguity, attachment URL refresh, delivery-part order, nonce convergence,
rate limits, file request batching, and unknown provider outcomes.

Every provider-neutral extraction phase includes targeted Slack regression coverage for
unchanged HTTP/Socket ingress, selector, management, progress, and file behavior.

### Essential E2E matrix

| Journey | Required evidence | Phase |
| --- | --- | --- |
| Single App core | Agent-admin setup/activation, sole route, thread provision, access continuation, one immutable binding/Session, follow-up, explicit reply | 12/14 |
| Multi App primary | Workspace setup, two Agents, message command, private selector, access-required selection, retained inbound file, approval, duplicate convergence, binding continuity, explicit outbound file | 12/14 |
| Management and lifecycle | Channel default, default routing, route removal/default invalidation without binding reroute, idempotent disconnect | 12/14 |
| Compact Web setup and repair | Separate Single/Multi entry points, authority boundary, secret redaction, configuring/reconnect guidance | 9/14-12/14 |

### Fixture and prerequisite requirements

The deterministic Discord fake is required before essential E2E because no live Discord
App or guild is part of this snapshot. It must support only the provider contract used
by the feature:

- Gateway HELLO, heartbeat, Identify, Ready, Resume, Dispatch, invalid session,
  reconnect, and close-code behavior;
- Ed25519-signed PING, message command, component, and modal interactions;
- App/bot identity, interaction endpoint configuration, Guild membership, and guild
  command registration;
- thread create/fetch/history, message create/edit/delete, nonce duplicate handling,
  attachment upload/download; and
- rate-limit, rejection, timeout, 5xx, and ambiguous outcome simulation.

Fixture evidence retains operation names, identifiers, part ordinals, byte counts,
acknowledgements, and outcomes only. It excludes tokens, signatures, raw bodies,
message bodies, file bodies, and transient URLs.

## Rollout and CI Gates

Discord creation is disabled until phase 12 evidence passes and every deployed API and
Worker can read provider-aware rows. Enablement additionally requires the Gateway
Worker Deployment, public callback base URL configuration, and current living specs.

CI is complete for a phase only when its affected Python, OpenAPI/client, TypeScript,
Helm, migration, and deterministic E2E checks pass. TypeScript format, lint, typecheck,
tests, and build run sequentially. Docker/image pull failures are reported as explicit
environment blockers and are not treated as product success.

## Spec Impact Candidates

The following living specs are promoted only after verified implementation:

- `docs/azents/spec/domain/external-channel.md`
- `docs/azents/spec/flow/external-channel-provider-ingress.md`
- `docs/azents/spec/flow/external-channel-authorization.md`
- `docs/azents/spec/flow/external-channel-delivery.md`
- `docs/azents/spec/flow/external-channel-lifecycle.md`

## Risks and External Actions

| Risk or external action | Blocking phase | Handling |
| --- | --- | --- |
| No live Discord App/guild | None | Use the deterministic fake; do not add a live prerequisite |
| Gateway library lacks durable Resume state hooks | 5/14 | Use a small protocol wrapper; Identify plus explicit gap reconciliation is the controlled fallback |
| Discord permission overwrite changes | 6/14 onward | Recheck capability at admission, provisioning, history, file, and delivery boundaries |
| Provider file limit varies by target context | 8/14 | Preflight only proven capability; classify unknown provider rejection as controlled failure |
| Provider-neutral schema affects Slack readers | 3/14 onward | Keep compatibility readers, add targeted Slack regression, remove only in 14/14 |
| Deployment callback base URL absent | Discord enablement only | Preserve rollout gate; deterministic E2E remains credential-free |

## Spec Promotion and Cleanup

Phase 13 runs `/spec-review`, compares implementation to the living specs, and updates
verified current behavior. Only after all required validation passes does it set the
same `implemented` date in the Requirements and Design snapshots. The accepted ADR is
not rewritten.

Phase 14 removes this plan and any phase-specific plans, plus temporary compatibility
readers and stale references that are no longer needed after all deployed readers have
migrated. It contains no behavioral refactor.
