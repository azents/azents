---
title: "Discord Bot Role Mention Invocation Design"
created: 2026-08-02
updated: 2026-08-02
tags: [discord, external-channel, architecture, backend, testenv]
document_role: primary
document_type: design
snapshot_id: discord-260802
---

# discord-260802/DESIGN: Discord Bot Role Mention Invocation

- Snapshot: `discord-260802`
- Document reference: `discord-260802/DESIGN`
- Mode: Collaborative

## Inputs

- Requirements:
  [discord-260802/REQ](../requirements/discord-260802-bot-role-mention-invocation.md)
- Architecture decision:
  [discord-260802/ADR](../adr/discord-260802-bot-role-mention-invocation.md)

## Summary

Extend the bounded typed Discord Gateway projection with the Bot ownership identity of
mentioned Discord-managed roles. Discord normalization treats the message as an
explicit invocation when a direct mentioned user or a mentioned managed role resolves
to the connection's validated Bot user identity.

No durable schema, management API, activation state, provider REST call, or shared
ingestion branch changes. The existing provider-neutral invocation path continues to
own setup, response modes, access, canonical mailbox admission, Session wake, Channel
Work, and AgentRun creation.

## Current Behavior and Gap

`DiscordGatewayClient.on_message()` forwards a typed `discord.Message`.
`project_discord_gateway_event()` projects message content, author identity, direct
mentioned users, attachments, channel identity, and thread identity into a bounded
`ExternalChannelTrigger`. `normalize_projected_discord_event()` marks the trigger as
an invocation only when a direct mentioned user ID equals the connection's
`provider_bot_user_id`.

The typed message also resolves mentioned Discord roles. A Bot-managed role carries
provider-owned Bot identity metadata, but the current projection drops role mentions.
The role therefore remains visible in the message body and provider history while the
trigger is classified as an ordinary message.

## Traceability

| Requirement | ADR decisions | Design mechanism |
| --- | --- | --- |
| `discord-260802/REQ-1` | `ADR-D1` | Project managed-role Bot ownership and include it in Discord invocation classification |
| `discord-260802/REQ-2` | `ADR-D1` | Match only provider-declared role owner identity to `provider_bot_user_id` |
| `discord-260802/REQ-3` | `ADR-D1` | Preserve the existing normalized invocation boolean and all downstream shared ingestion |

## Typed Gateway Projection

`_project_discord_sdk_event()` receives the validated connection Bot identity and
reads `message.role_mentions`. For each mentioned role, it checks the public role tags
exposed by the SDK.

- A role without a Bot ownership tag is omitted from the managed-role invocation
  projection.
- A Bot-managed role owned by another Bot is omitted before the collection limit.
- A role owned by the connected Bot contributes only its role ID and owning Bot user
  ID.
- Display name, color, permissions, position, membership, and other role state are not
  projected.
- The existing bounded collection limit applies after exact ownership filtering.

The internal projected message uses a distinct managed-Bot-role field rather than the
provider's raw `mention_roles` ID array. A raw role ID alone is insufficient to prove
Bot ownership.

`project_discord_message()` retains the bounded internal field when it is present.
REST history and Message Command source projections that expose only raw role IDs do
not synthesize ownership and therefore do not independently broaden invocation
classification.

## Normalization and Admission

`normalize_projected_discord_event()` computes invocation as:

```text
direct mentioned user owned by connected Bot
OR
mentioned managed role owned by connected Bot
```

The stored connection Bot identity is required. Missing Bot identity or malformed role
projection produces `invocation=False`.

The normalized message shape and `ExternalChannelTriggerLocator` remain unchanged.
Shared ingestion receives the same boolean it already uses. Consequently:

- initial parent-channel setup can begin from the managed-role mention;
- an existing `mention_only` binding admits the managed-role mention;
- `all_messages` behavior remains unchanged;
- sender eligibility and access checks run normally;
- ordinary prior messages remain bounded history context; and
- conversation-position idempotency remains authoritative.

## Security and Failure Handling

The provider-owned Bot tag is the only new evidence accepted. The adapter never
matches role names or accepts ordinary role membership. Another Bot's managed role has
a different owner identity and remains a non-invocation.

If Guild role state is missing or the SDK cannot resolve the role ID, no managed role
object appears in the typed message. Azents fails closed by classifying the message
using direct user mentions only. It does not fetch Guild roles on the synchronous
ingress path.

Malformed projected role entries are ignored. Existing normalization and transport
failure handling remain unchanged.

## Removal and Replacement

| Existing unit or behavior | Why it becomes obsolete | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Discord invocation classification based only on direct user mentions | It rejects the connected Bot's provider-managed role despite equivalent user intent | Direct user mention or exact managed-role Bot ownership match | Replace the Discord normalization predicate and its focused tests | Search confirms no second Discord invocation classifier remains |
| Dropping every role mention at the typed Gateway projection | The exact managed-role owner identity is required for safe invocation | Bounded managed-Bot-role projection | Add only the minimal role ID and owner Bot ID fields | Projection tests assert no display or permission metadata is retained |

No persistence, API, frontend, generated client, migration, configuration, or legacy
fallback removal is required.

## Test Strategy

### E2E primary verification

Update the deterministic Discord Gateway provider-fake scenario so:

- `GUILD_CREATE` contains the connected Bot's managed role with its Bot ownership tag;
- `MESSAGE_CREATE.mention_roles` contains that role ID;
- the message has no direct Bot user mention; and
- mention-only setup reaches the existing location selection, binding, Session, and
  canonical invocation assertions.

The test uses public setup and management APIs, the real Gateway client, the provider
fake, signed provider interactions, and public Session projections. It performs no
product database writes.

CI must fail rather than skip when the deterministic provider fake is available and
the managed-role message does not reach setup admission. No live Discord credentials
or optional prerequisite snapshot is required.

### Focused backend verification

- SDK projection retains only a managed role's ID and owner Bot ID.
- A role owned by the connected Bot produces `invocation=True`.
- A manually managed or ordinary role produces `invocation=False`.
- Another Bot's managed role produces `invocation=False`.
- Direct user mention behavior remains covered.
- Gateway manager fixtures explicitly include an empty role-mention collection where
  the scenario is unrelated.

### Quality checks

Run focused Ruff, Pyright, backend unit tests, and the deterministic Discord E2E. The
PR CI remains authoritative for the full repository matrix.

## Feasibility

| Requirement | Result | Evidence |
| --- | --- | --- |
| `discord-260802/REQ-1` | Feasible | The pinned typed SDK exposes resolved role mentions and Bot ownership tags before event projection |
| `discord-260802/REQ-2` | Feasible | Invocation can compare the provider-owned role Bot identity with the existing validated connection Bot identity |
| `discord-260802/REQ-3` | Feasible | The shared ingestion contract already consumes one provider-neutral invocation boolean |

## Remaining Non-Blocking Risks

- Discord events with unresolved Guild role state fail closed and require a direct Bot
  mention. The Gateway's Guild role state and deterministic E2E cover the normal
  production path.
- The visible managed role may become unmentionable through Discord permissions; that
  provider-side UX does not change the classification of a successfully delivered
  resolved role mention.
