---
title: "Retire Legacy Platform GitHub App Bindings"
created: 2026-07-20
tags: [architecture, backend, frontend, github, configuration, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: legacy-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0175-retire-legacy-platform-github-bindings.md"
---

# [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-192): Retire Legacy Platform GitHub App Bindings

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-193) introduced nullable Platform GitHub App identity bindings so an installation that existed before identity binding could be claimed or reconnected safely. That transition state added nullable installation rows, nullable encrypted Toolkit credential fields, Admin claim-or-leave decisions, Public reconnect reasons, and Main Web guidance.

The deployment has one Platform GitHub App installation and no pre-binding installations. Continuing to retain that transition state makes the product appear broken and leaves supported behavior coupled to a migration path that no longer exists.

## Decision

Platform GitHub App identity is mandatory for every persisted installation row and Platform Toolkit credential. The server resolves the current Platform App at Toolkit create, update, and unsaved connection-test boundaries, then writes its App ID itself. Clients do not select or supply the durable identity.

The database enforces `github_user_installations.platform_app_id NOT NULL` and one uniqueness rule on `(user_id, platform_app_id, installation_id)`. The application contains no startup normalization, retired credential decoder, unbound-row query, or user-selectable claim path.

The product no longer exposes an unbound legacy state. Admin confirmation actions and impact counts for unbound resources are removed. Public Toolkit authorization state retains only `app_identity_changed` for a persisted binding that differs from the effective Platform App. That mismatch remains fail-closed and requires reconnection because it can represent a genuine App replacement.

## Consequences

- Managers do not see a legacy-binding reconnect warning or choose whether to claim records.
- New Platform Toolkit credentials always contain the server-resolved App ID, including unsaved connection tests.
- Deployments must not contain pre-invariant installation rows or Platform Toolkit credentials before this schema revision is applied.
- A real Platform GitHub App replacement still disables affected Toolkit authorization until reconnection refreshes its installations.

## Alternatives Considered

### Keep the claim-or-reconnect transition indefinitely

Rejected because there are no supported pre-binding installations and the UI presents the retained transition state as an actionable operational failure.

### Keep a one-time startup normalization

Rejected because it retains acceptance of retired data formats and makes the database invariant weaker than the product contract.

### Treat an unbound credential as matching any effective App at runtime

Rejected because it would retain an implicit fallback and allow an unverified credential to cross an App identity boundary.

## Migration provenance

- Historical source filename: `0175-retire-legacy-platform-github-bindings.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
