---
title: "Provider Account Linking Decisions"
created: 2026-09-13
tags: [architecture, external-channel, identity, oauth, security]
document_role: primary
document_type: adr
snapshot_id: identity-260913
---

# identity-260913/ADR: Provider Account Linking

- Snapshot: `identity-260913`
- Document reference: `identity-260913/ADR`
- Requirements:
  [`identity-260913/REQ`](../requirements/identity-260913-provider-account-linking.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The current account-linking implementation starts from a signed Slack or Discord
interaction, creates a Workspace-scoped origin, stages an Azents User and auth-Session
candidate, verifies a one-time code in the original provider interaction, and requires
the same browser Session to confirm the candidate. Active link uniqueness includes the
Workspace, and native linked-user model settings look up the link in that Workspace.

The confirmed Requirements replace this with provider authorization initiated from
Azents Web, make provider identity ownership global to the Azents User, retain
resource-specific authorization at every action, preserve guest behavior, migrate only
unambiguous legacy ownership, and remove the native-code flow without a compatibility
fallback.

## Fixed and Derived Outcomes

- The active identity source of truth is global to the Azents User and provider
  identity. Workspace, Agent, Channel, Session, connection, principal, and conversation
  records are not link owners.
- Discord identity is provider-global. Slack identity retains Slack team context.
- A User may own multiple identities from the same provider, while one active provider
  identity may have only one Azents User owner.
- Provider authorization uses only identity scopes: Slack OpenID and profile identity,
  and Discord identify identity. Email and provider API action scopes are excluded.
- A successful connection is bound to the same live Azents auth Session that started it
  and has durable single-use completion semantics. Redis cannot be required for
  correctness.
- Provider access, ID, and refresh credentials are not retained after identity
  verification.
- The Slack and Discord OAuth client configurations are independent Admin-managed
  System Settings Sections with encrypted write-only secrets, optimistic mutation,
  metadata-only audit, no environment bindings, and effective-generation fencing.
  Either Section may identify the same provider App already used by External Channels;
  no identity-only App is required.
- Native Slack and Discord connection controls are direct Web URLs. Their current
  signed start components, origin creation, deferred updates, code modals, provider
  proof, status polling, and second confirmation are removed.
- Existing guest authorization and the current linked-user target authorization checks
  remain separate. Link lookup becomes global, but current User, Workspace, Session,
  Agent, Binding, principal grant/block, and model authority are still revalidated for
  each action.
- The installed Slack SDK supplies supported OpenID token and user-info operations.
  Discord.py has no authorization-code client surface, so the implementation must use
  an established OAuth client library rather than inventing provider protocol code.
- Deterministic provider fakes are the required product-verification boundary; live
  end-user credentials are not a required CI prerequisite.

## Material Decision Map

| ID | State | Decision |
| --- | --- | --- |
| `identity-260913/ADR-D1` | Accepted | Manage canonical Slack and Discord OAuth client credentials in independent Admin System Settings Sections and allow existing provider Apps |
| `identity-260913/ADR-D2` | Accepted | Persist one-time OAuth attempts and complete them through the authenticated Azents Web callback boundary |
| `identity-260913/ADR-D3` | Accepted | Convert legacy Workspace links into one global link lifecycle with an explicit one-way cutover |

## Agent-Owned Implementation Categories

The Design may choose equivalent local details without additional requester decisions:

- endpoint, request, response, service, repository, and helper names;
- OAuth attempt TTL within a short bounded window, random-token length, hashes, and
  internal status names;
- exact provider client adapter boundaries and typed response payload names;
- database index names, migration statement layout, batching syntax, and local query
  composition that preserve accepted ownership and migration semantics;
- UI component composition, icons, loading presentation, and localized wording that
  preserve the confirmed workflow and availability states;
- provider-fake route names, fixture identifiers, test module layout, and evidence file
  names; and
- implementation phase boundaries within one focused PR.

These choices cannot add a second link authority, retain provider tokens, require
Redis, weaken auth-Session binding or single-use completion, broaden provider scopes,
restore provider code entry, expose conflict ownership, or change existing guest and
target authorization.

## Accepted Decisions

### identity-260913/ADR-D1 — Admin-managed canonical provider OAuth Apps

Slack and Discord account authorization each use an independent compiled System
Settings Section. Each Section stores the canonical OAuth client identity and
encrypted client secret required for that provider, exposes redacted readiness through
Admin API and Admin Web, activates an optimistic locally valid mutation directly, and
appends metadata-only audit events. The Sections have no environment bindings, so
deployment variables and Workspace connection credentials cannot override the
administrator-owned source of truth.

The administrator may enter credentials for the same Slack App or Discord Application
already used by External Channels. The provider App is reused as an OAuth client, but
the System Setting remains the canonical instance-wide configuration and does not copy,
reference, or become owned by any Workspace connection. Discord OAuth returns the same
provider-global user ID observed by Discord interactions. Slack OAuth identity is
matched by Slack team ID and user ID, which is the same provider-team scope used by
Slack interactions.

The provider callback URL is derived from the configured Azents Web URL and shown to
the administrator for provider registration. Completeness and local shape determine
configured readiness; real authorization and identity exchange failures remain
sanitized provider-flow failures. Changing a Section advances its effective
generation, invalidates attempts started under the prior generation, and does not
rewrite existing global identity links.

Affected requirements: `identity-260913/REQ-1`, `identity-260913/REQ-3`,
`identity-260913/REQ-5`, `identity-260913/REQ-8`, and
`identity-260913/REQ-9`.

Rejected alternatives:

- Require separate identity-only Slack and Discord Apps. Provider identity is stable
  across Apps in the required provider scope, so a separate App adds operator work
  without improving ownership proof.
- Store OAuth client secrets only in deployment settings. This conflicts with the
  required Admin-managed product authority and prevents in-product mutation and audit.
- Read OAuth client secrets from each Workspace External Channel connection. Current
  connection credentials do not contain them, Web account settings has no canonical
  Workspace connection, and connection ownership would create a second identity
  authority.
- Trust a provider-native interaction ID and a transferable Web link without provider
  OAuth. The URL would become a bearer identity credential and could connect the
  provider identity to a different logged-in Azents User.

### identity-260913/ADR-D2 — OAuth attempt and authenticated callback boundary

Each Connect operation creates one short-lived PostgreSQL OAuth attempt containing a
hash of an opaque state token, the initiating User and auth Session, provider, effective
System Setting generation, exact redirect URI, optional provider-supported PKCE
verifier, expiry, and terminal completion state. The plaintext state is returned only
in the authorization URL and is never durable.

The provider redirects to a protected Azents Web server route. That route uses the
current HTTP-only Azents auth cookies to call an authenticated backend exchange
operation with the authorization code and state. The repository atomically claims the
matching unexpired attempt for the same User, auth Session, provider, redirect URI, and
effective configuration generation before provider exchange. Completion then stores
only the verified global identity link and terminal attempt metadata. Provider tokens
remain request-local and are discarded.

An exchange or identity failure terminalizes the claimed attempt and returns sanitized
restart guidance. A missing, tampered, expired, consumed, wrong-provider,
wrong-auth-Session, or stale-configuration attempt creates no link. PostgreSQL is the
only correctness source; Redis and process-local state are not required.

Affected requirements: `identity-260913/REQ-1`, `identity-260913/REQ-5`,
`identity-260913/REQ-8`, and `identity-260913/REQ-9`.

Rejected alternatives:

- Put the complete attempt only in encrypted OAuth state and rely on the provider code
  being single-use. This cannot authoritatively consume or cancel the state, reject a
  second code created from a copied authorization URL, or fence configuration changes.
- Send the provider directly to a Public API callback with a new temporary browser
  cookie/session protocol. This duplicates Main Web authentication and creates another
  cross-origin browser security boundary.
- Store attempt state in Redis or process memory. Either would make an optional or
  restart-sensitive subsystem part of the identity correctness boundary.

### identity-260913/ADR-D3 — Global link migration and one-way cutover

The existing `external_account_links` table becomes the sole global link lifecycle.
Its Workspace field is renamed to nullable `legacy_workspace_id`, retains only
historical provenance, and no longer participates in ownership or cascade deletion.
The migration replaces Workspace-scoped active uniqueness with global
provider/identity-scope/provider-user uniqueness and removes the active
User/provider/scope constraint so one User can own multiple identities from the same
provider.

For every active legacy identity group whose rows all name one User, the migration
keeps the deterministic earliest linked row active and terminally revokes redundant
rows with a migration reason. For a group that names multiple Users, it terminally
revokes every row with a migration-conflict reason and creates no global owner. A later
provider OAuth proof may create the one active global row. New links always have null
legacy Workspace provenance. Existing model draft and immutable mutation FK references
continue to point to retained rows and their snapshots remain unchanged.

The requester confirmed that the current target deployment has no rows in these
tables, so its data phase is expected to be a no-op. The migration still preserves the
general transformation because the schema already exists on `main` and another
installation may have executed it.

The same release drops candidate and origin tables after link transformation. The new
application removes candidate/code routes, native handlers, Web confirmation pages,
generated clients, and scheduled cleanup. Old binaries are unsupported after the
migration and must be drained before the migrated schema becomes writable. Rollback is
database backup restoration or a forward fix, never a legacy runtime mode.

Affected requirements: `identity-260913/REQ-3`, `identity-260913/REQ-4`,
`identity-260913/REQ-6`, `identity-260913/REQ-7`, and
`identity-260913/REQ-8`.

Rejected alternatives:

- Create a separate global-link table and retain the current table as legacy history.
  This creates two link identity domains, requires new or polymorphic FKs, and leaves a
  second table that must never regain runtime authority.
- Delete and recreate every link because the known deployment is empty. The schema has
  already merged into the open-source repository, so a fail-safe migration must not
  silently discard rows in another installation.
- Maintain an expand/contract period in which old and new link flows are both
  writable. This conflicts with required browser-code removal and creates ambiguous
  ownership during reconciliation.

## Pending Decision Briefs

No material technical decisions remain pending.

## Risks and Consequences

- Provider redirect URI registration is an operator prerequisite. Incomplete provider
  configuration must disable only that provider and remain explicit in Web and native
  presentation.
- A global identity migration changes persistence and every linked-user lookup. The
  Design must prove absence of Workspace-scoped lookup and obsolete candidate/origin
  surfaces after cutover.
- A one-way migration must retain enough immutable snapshots or legacy provenance for
  existing model-setting audit rows to remain interpretable.
- Required E2E provider fakes must model authorization, token exchange, identity lookup,
  cancellation, malformed response, conflict, expiry, replay, and auth-Session
  substitution without retaining or printing secret values.
