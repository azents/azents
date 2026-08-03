---
title: "External Channel Activity Tracker Session Navigation"
created: 2026-08-03
tags: [external-channel, slack, discord, session, architecture]
document_role: primary
document_type: adr
snapshot_id: external-260803
---

# External Channel Activity Tracker Session Navigation

- Snapshot: `external-260803`
- Document reference: `external-260803/ADR`
- Requirements: [`external-260803/REQ`](../requirements/external-260803-activity-tracker-session-navigation.md)
- Mode: Collaborative
- Decision owner: requester

## Context

Slack and Discord Activity Trackers are rendered from canonical Channel Work and delivered through process-local provider effects. The current Tracker presentation contains work status but no Session navigation. Existing joined and left controls already derive a canonical `View session` destination from the current Workspace, Agent, and Session carried by the provider target.

Tracker navigation must not add persisted URLs, another projection owner, a separate provider message, or a dependency from provider delivery to mailbox admission, Session wake-up, or Agent execution.

## Fixed and Derived Outcomes

- Every initial and updated Slack or Discord Tracker contains one `View session` navigation control.
- The destination is the existing canonical Agent Session route.
- The URL is derived from current provider-effect authority rather than copied into Channel Work or projection state.
- Slack uses a Block Kit action and Discord uses a link button component.
- Provider failure and Tracker lifecycle behavior remain unchanged.
- Discord update requests explicitly retain the same navigation component.

## Decision Backlog

None. The confirmed Requirements, existing canonical Session URL contract, and current process-local provider-effect architecture determine the implementation direction without an unresolved material product or architecture choice.

## Accepted Decisions

No additional material decision is introduced by this snapshot. Local helper names, test placement, and equivalent provider-payload construction remain implementation details.
