---
title: "Discord Agent App Routing phase 4: Connection management"
created: 2026-07-26
updated: 2026-07-26
tags: [discord, external-channel, api, backend, openapi]
---

# Discord Agent App Routing phase 4: Connection management

## Scope

This phase adds the provider-tagged management contracts for Discord Single and Multi
Apps on top of the provider foundation. It keeps Discord creation and activation
rollout-disabled: no Gateway session, signed interaction endpoint, command
registration, or provider mutation is enabled here.

## Source documents

- Requirements: `docs/azents/requirements/discord-260726-agent-app-routing.md`
- ADR: `docs/azents/adr/discord-260726-agent-app-routing.md`
- Design: `docs/azents/design/discord-260726-agent-app-routing.md`
- Multi-phase plan: `docs/azents/plans/discord-agent-app-routing-implementation-plan.md`

## Delivery boundaries

- Add explicit Discord Single and Multi setup request contracts containing the Bot
  Token, App identity, and target Guild identity. Secret values must never appear in
  projections, errors, logs, OpenAPI examples, or generated client fixtures.
- Persist Discord connections as `configuring`, using the fixed
  `discord_gateway_http` ingress profile and a provider-tagged non-secret
  configuration. The provider contract validates shape before encryption.
- Add provider-aware creation and replacement service/repository paths without
  changing existing Slack endpoint semantics.
- Preserve ownership: Agent administrators manage Single Apps; Workspace Owners and
  Managers manage Multi Apps. Multi Apps may start with zero routes.
- Expose redacted Discord setup/health state through management projections. A
  configuration replacement increments the connection configuration generation and
  cannot activate Discord before the later rollout gate.
- Add a distinct `external_channel_discord_enabled` deployment gate. Every Discord
  create, validation, or replacement mutation must fail closed while it is disabled.
- Generate the public OpenAPI document and Python/TypeScript clients from source
  models. Do not edit generated output manually.

## Exclusions

- Do not start or deploy a Discord Gateway Worker.
- Do not verify interaction signatures, register application commands, create
  threads, admit messages, create bindings, download files, or deliver replies.
- Do not enable Discord creation in production or use live Discord credentials.
- Do not alter legacy Slack URLs, callback behavior, connection validation, or
  Multi-App rollout semantics.

## Dependencies

- Phase 3 migration `26d36352bece` provides the Discord enum value, ingress profile,
  configuration generation, App claim, and provider-neutral retained state.
- The current merge revision `32c9f7dbbe18` keeps the migration graph at one head.
- Later Gateway and interaction phases consume the persisted configuration generation
  and rollout gate; they own actual Discord identity validation and activation.

## Verification

- Focused provider, credential, connection-service, management-service, and API route
  tests cover malformed Discord setup, secret redaction, Single/Multi authority,
  fixed ingress profile, configuration generation fencing, and disabled rollout.
- Dump OpenAPI and regenerate both public clients.
- Run backend Ruff, formatting, Pyright, and the focused test suite.
- Create the phase PR before checking any stack CI result.
