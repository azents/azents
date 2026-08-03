---
title: "External Channel Activity Tracker Session Navigation Design"
created: 2026-08-03
updated: 2026-08-03
implemented: 2026-08-03
tags: [external-channel, slack, discord, session, backend]
document_role: primary
document_type: design
snapshot_id: external-260803
---

# External Channel Activity Tracker Session Navigation Design

- Snapshot: `external-260803`
- Document reference: `external-260803/DESIGN`
- Requirements: [`external-260803/REQ`](../requirements/external-260803-activity-tracker-session-navigation.md)
- Decisions: [`external-260803/ADR`](../adr/external-260803-activity-tracker-session-navigation.md)
- Mode: Collaborative
- Decision owner: requester

## Current Behavior and Gap

Slack Activity Trackers contain one task-card or plan block. Discord Activity Trackers contain one compact Embed. Initial creation and later updates use the same Channel Work projection identity, but neither presentation contains Session navigation.

The direct provider target already carries the current Workspace handle, Agent ID, AgentSession ID, and Agent identity. Joined and left controls use those fields with the configured Web origin to derive the canonical Session route.

## Requirement Traceability

| Requirements | Mechanism |
| --- | --- |
| REQ-1 | M1 live canonical Session navigation derivation and provider-native controls |
| REQ-2 | M2 identical navigation projection on Tracker creation and update |
| REQ-3 | M3 presentation-only integration with unchanged Work and projection lifecycle |

## Architecture and Ownership

Channel Work remains the source of truth for Tracker content and desired revision. Work projection parts remain the source of truth for the current provider message identity and projection state. No Session URL or provider component is added to either durable record.

At the existing provider delivery boundary, the current effect target is validated and the canonical Session URL is derived from its Workspace, Agent, and Session identity. Provider-native navigation presentation is added to the already rendered Tracker immediately before the one create or update request.

## Provider Presentation

Slack appends one Block Kit `actions` block containing the existing `View session` link button to both progress create and progress update payloads. Existing Agent attribution remains prepended independently.

Discord sends one action row containing the existing `View session` link button with both message creation and message update. Discord's update adapter accepts generated components and includes them in the PATCH body so an updated Tracker has the same complete presentation as a newly created Tracker.

The shared Slack and Discord navigation helpers are also used by Session presence presentation so label, style, and URL shape do not diverge.

## Failure, Security, and Lifecycle

If the current provider target cannot produce a valid canonical Session URL, the Tracker provider request fails through the existing invalid-payload outcome. No fallback URL or partial Tracker without required navigation is sent.

The link grants no authority. Azents Web applies its existing Session access checks when opened. Provider credentials, provider identifiers, and rendered URLs are not logged or persisted.

Tracker creation, update, completion, deletion, projection comparison, provider outcome handling, retry policy, and recovery behavior remain unchanged. Provider delivery remains downstream of committed admission and execution state.

## Migration, Rollout, and Rollback

No database migration, API change, generated client update, configuration change, backfill, compatibility path, feature flag, or new deployment unit is required. Rollback removes the presentation helpers and Discord update component argument.

## Test Strategy

Deterministic unit and provider-adapter tests verify:

- Slack's generated Session navigation action;
- Discord's generated Session navigation component;
- joined and left controls continue using the shared navigation presentation;
- Discord create and update requests preserve generated components; and
- Tracker delivery construction requires and applies the canonical Session URL for both create and update paths.

Focused backend tests and the full Python quality checks are the CI authority. No live Slack or Discord credential is required, no product database is mutated directly, and no Web Surface E2E is added.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Derive the canonical Session URL from current provider-effect Workspace, Agent, and Session authority and render provider-native navigation | REQ-1 and the existing Session navigation contract | `derived` |
| M2 | Include the same navigation control in both Tracker create and update requests | REQ-2 | `required` |
| M3 | Keep Channel Work, projection state, authorization, and lifecycle unchanged | REQ-3 and the current External Channel delivery spec | `existing` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Tracker presentation without Session navigation | REQ-1 and REQ-2 | M1 and M2 complete provider-native Tracker presentation | Slack and Discord progress delivery only | Create and update tests require `View session` |
| Duplicate provider-specific Session link literals | M1 consistency requirement | Shared provider-native navigation helpers | Session presence and Tracker presentation | Presence and Tracker tests assert the same label and URL shape |
| Durable state, API, configuration, and generated surfaces | None | Existing authority remains unchanged under M3 | None | Diff and schema/API audit show no such changes |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-03`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3`
- Approved scope: add canonical `View session` navigation to initial and updated Slack and Discord Activity Trackers without changing durable state, authorization, lifecycle, or execution dependencies.
