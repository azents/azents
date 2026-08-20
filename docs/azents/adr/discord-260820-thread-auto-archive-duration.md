---
title: "Discord Thread Automatic Archive Duration Decisions"
created: 2026-08-20
tags: [architecture, discord, external-channel, persistence, api]
document_role: primary
document_type: adr
snapshot_id: discord-260820
---

# discord-260820/ADR: Discord Thread Automatic Archive Duration

- Snapshot: `discord-260820`
- Document reference: `discord-260820/ADR`
- Requirements:
  [`discord-260820/REQ`](../requirements/discord-260820-thread-auto-archive-duration.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Discord connection configuration currently retains the target Guild in the
connection-owned `provider_config` JSON object, while every Azents-created Discord
Thread uses a hard-coded 60-minute automatic archive duration. Single and Multi Apps
already expose the redacted connection configuration through their management
projections. Their existing credential-edit operations replace credentials and reset
Discord callback, Gateway, identity, capability, and health authority before
reactivation.

The confirmed Requirements add one administrator-managed policy shared by every route
on a connection. Existing connections must become one day, new connections must default
to one day, duration-only changes must preserve connection operation, and only later
Thread creation may observe a changed value.

## Fixed and Derived Outcomes

- Supported values are the closed Discord set `60`, `1440`, `4320`, and `10080`
  minutes.
- The selected value is required connection configuration and is shared by all routes,
  Bindings, Resources, and Sessions that use that connection.
- Existing rows are migrated to `1440`; new setup initially supplies `1440`.
- Thread creation reads the current connection value immediately before the provider
  operation.
- Reused and already created Threads are not edited.
- Agent settings retain read-only presentation for Workspace-owned Multi Apps.
- The Select includes no helper or explanatory text below it.

## Material Decision Map

| ID | State | Decision |
| --- | --- | --- |
| `discord-260820/ADR-D1` | Accepted | Keep the duration in the connection-owned typed provider configuration |
| `discord-260820/ADR-D2` | Accepted | Add a policy-only management mutation that preserves Discord operational authority |
| `discord-260820/ADR-D3` | Accepted | Backfill every Discord connection to one day and require the field after migration |

## Agent-Owned Implementation Categories

The Design may choose equivalent local details without additional requester decisions:

- endpoint and request-model names;
- repository helper names and SQL statement composition;
- literal aliases and UI value/label helper structure;
- form-state and save-button placement within the existing Single and Multi management
  surfaces;
- migration statement layout and test fixture identifiers; and
- exact unit, route, generated-client, and Storybook test organization.

These choices cannot copy the policy to routes or conversations, require credentials
for a policy-only change, change existing Threads, accept unsupported values, or reset
Discord callback, Gateway, identity, capability, or health state.

## Accepted Decisions

### discord-260820/ADR-D1 — The connection configuration is the sole policy authority

The automatic archive duration is stored beside the target Guild in the Discord
connection's typed, non-secret provider configuration. Every route and Binding on that
connection reads the same value; no copy is stored on an Agent route, participation
setting, Resource, Binding, Session, or provider thread record.

The management API continues to expose the redacted connection configuration, allowing
Single and Multi App surfaces to render the current selection. Runtime code decodes the
JSON configuration into the Discord-specific typed model before making policy
decisions.

Affected requirements: `discord-260820/REQ-1`, `discord-260820/REQ-2`, and
`discord-260820/REQ-3`.

Rejected alternatives:

- Store the value on each Agent route. This allows routes on one Multi App to diverge
  and violates connection-wide behavior.
- Snapshot the value onto each Resource or Binding. This makes later connection changes
  ineffective for new Threads created from existing conversation state and creates
  multiple policy authorities.
- Use a deployment-wide setting. This prevents independent connection administration.

### discord-260820/ADR-D2 — Duration updates use a non-secret policy mutation

Single and Multi App management receive a dedicated full-value mutation for the
Discord Thread duration. It locks and validates the requested active Discord
connection, updates only the typed non-secret provider configuration and normal
management generation timestamp, and returns the redacted connection projection.

The mutation does not replace encrypted credentials, Application or Guild identity,
configuration-generation fences, callback selectors, Application claims, Gateway
leases, capabilities, health, routes, Bindings, or Sessions. Multi App mutation uses
its current management generation as an optimistic concurrency fence so a stale
Workspace editor cannot overwrite newer connection management state. Single App
mutation uses the existing Agent-admin ownership boundary.

Affected requirements: `discord-260820/REQ-3` and `discord-260820/REQ-4`.

Rejected alternatives:

- Reuse complete Discord credential replacement. This requires secrets and deliberately
  invalidates operational authority that the policy change must preserve.
- Mutate configuration client-side only until another credential edit. This does not
  persist the requested policy and cannot affect provider operations reliably.
- Add a generic raw JSON patch endpoint. This weakens provider-specific validation and
  introduces ambiguous omitted/null semantics for unrelated configuration fields.

### discord-260820/ADR-D3 — Migration establishes one required post-deployment shape

A forward data migration adds `thread_auto_archive_duration_minutes: 1440` to every
Discord connection's `provider_config`, preserving its existing fields. New setup
requests also provide a validated value, with product clients selecting `1440` by
default.

After migration, Discord connection configuration requires the field and rejects values
outside the supported closed set. Runtime and management code do not maintain a legacy
missing-field fallback; the migration is the compatibility boundary.

Affected requirements: `discord-260820/REQ-1` and `discord-260820/REQ-2`.

Rejected alternatives:

- Leave historical JSON unchanged and scatter a one-day fallback across readers. This
  keeps two persisted shapes and can mask incomplete migrations indefinitely.
- Backfill only active connections. Disconnected history is still a connection record
  and should retain a valid typed configuration if read by management or diagnostics.
- Keep the current one-hour value for historical rows. This conflicts with the required
  existing-connection default.

## Risks and Consequences

- Updating a Multi App's management timestamp may cause an already-open destructive
  impact confirmation to fail its generation fence and require reload. This is the
  intended stale-editor behavior.
- A malformed historical Discord `provider_config` would make the migration or typed
  decode fail rather than silently inventing provider identity. Migration tests must
  cover field preservation and the expected current shape.
- Thread creation has more call sites than initial provisioning. Every path that can
  create a Thread must carry the same typed connection policy, while reuse paths remain
  mutation-free.
