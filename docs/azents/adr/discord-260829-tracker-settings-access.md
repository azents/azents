---
title: "Discord Activity Tracker Conversation Settings Access Decisions"
created: 2026-08-29
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260829
---

# discord-260829/ADR: Discord Activity Tracker Conversation Settings Access

- Snapshot: `discord-260829`
- Document reference: `discord-260829/ADR`
- Requirements:
  [`discord-260829/REQ`](../requirements/discord-260829-tracker-settings-access.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Discord conversational Activity Trackers currently derive their `View session`
component from the current delivery target during both create and update. The Work
desired state does not persist provider navigation controls. A separate direct control
is also prepared for an eligible explicit invocation in an existing Binding and
renders a settings-only Discord message.

The existing Discord settings component already signs an `open_binding` scope from the
Binding identifier. Component admission verifies the signature, and the settings
service revalidates current connection, Binding, conversation, and actor authority.
Slack uses the shared direct-control plan for its own existing settings presentation.

The confirmed Requirements make the visible Discord Activity Tracker the recurring
settings entry point, remove only the Discord settings-only follow-up message, and
preserve Slack, Scheduled Task, hidden Work, joined presence, and existing settings
authorization.

## Fixed and Derived Outcomes

- Discord conversational Tracker creation and update expose the same two actions.
- The settings action uses the current Binding's existing signed `open_binding` scope.
- Discord existing-Binding invocation admission no longer prepares a settings-only
  direct control.
- Slack retains its existing settings-only direct control.
- Hidden Discord Work remains provider-silent until an explicit invocation promotes it.
- Scheduled Task Trackers retain their separate control set.
- No provider component, Session URL, or settings authority is added to persisted Work
  desired state.

## Material Decision Map

No unresolved material decision remains. The placement, removal, provider scope,
authorization behavior, and unaffected paths are fixed by `discord-260829/REQ-1`
through `REQ-4`. Rendering the controls from the current delivery target follows the
existing Tracker navigation ownership and introduces no second viable source of truth.

## Agent-Owned Implementation Categories

The implementation may choose local helper signatures, conditional placement, test
organization, and exact source cleanup without additional requester decisions. These
details cannot persist component IDs, change the settings interaction contract, remove
Slack controls, expose settings on Scheduled Task Trackers, or make hidden Work visible.

## Consequences

- Every visible Discord conversational Tracker becomes a complete recurring
  navigation/settings surface.
- Follow-up explicit invocation produces one fewer Discord control message.
- A stale Tracker component continues to fail through existing signed-scope and
  current-state validation.
- Discord and Slack intentionally diverge in whether a follow-up settings-only direct
  control is prepared.
- There is no migration, rollout flag, compatibility path, retry behavior, or new
  operational state.
