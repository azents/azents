---
title: "Discord Activity Tracker Conversation Settings Access Design"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [discord, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: discord-260829
---

# discord-260829/DESIGN: Discord Activity Tracker Conversation Settings Access

- Snapshot: `discord-260829`
- Document reference: `discord-260829/DESIGN`
- Requirements:
  [`discord-260829/REQ`](../requirements/discord-260829-tracker-settings-access.md)
- Decisions:
  [`discord-260829/ADR`](../adr/discord-260829-tracker-settings-access.md)

## Current Behavior and Gaps

Discord Activity Tracker create and update delivery currently append one action row
containing only `View session`. The row is reconstructed from the current canonical
Workspace, Agent, and Session delivery target instead of being persisted in Channel
Work desired state.

Joined-presence delivery already renders both `View session` and `Conversation
settings`. Its settings action signs the current Binding identifier with the existing
`open_binding` Discord settings scope.

Both synchronous mailbox ingestion and durable ingress-queue finalization prepare a
provider-neutral settings-only direct control after an eligible explicit invocation in
an existing Binding. Slack and Discord lower that control separately. The Discord
lowerer posts a dedicated Embed containing only the Conversation settings action.

This leaves the recurring Tracker without settings access while an extra Discord
message provides that access. It also means both Discord ingestion paths must change;
changing only presentation would leave a planned obsolete provider effect.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `discord-260829/REQ-1` | M1 |
| `discord-260829/REQ-2` | M2 |
| `discord-260829/REQ-3` | M1, M3 |
| `discord-260829/REQ-4` | M2, M4 |

## Architecture and Ownership

Channel Work continues to own Tracker visibility, desired progress, revisions, and the
current provider projection identity. Binding and Session delivery targets remain the
authority for provider controls.

Discord Tracker create and update resolve the canonical Session URL exactly as today.
They also require the current target Binding identifier and build the existing signed
`open_binding` custom ID immediately before the provider mutation. The presentation
helper renders one action row with:

1. the canonical `View session` link; and
2. the signed `Conversation settings` component.

Neither value is written into desired progress or provider projection state. A
replacement or retry therefore uses current revalidated target authority.

## Admission and Provider Delivery

The two canonical ingress paths retain their current invocation and Tracker-visibility
rules:

- synchronous mailbox ingestion; and
- durable ingress-queue batch finalization.

Each path prepares the existing settings-only direct control only when the provider is
Slack. Discord invocation admission proceeds directly to active Work creation or
promotion and initial Tracker planning. The Tracker remains post-commit and
non-blocking, as before.

The obsolete Discord `binding_settings_on_demand` lowerer and its dedicated
presentation helper are removed. The shared payload builder and Slack lowerer remain
because Slack behavior is outside this snapshot.

## Settings Interaction and Security

The existing `build_discord_binding_settings_open_custom_id` function remains the sole
component builder. It signs an `open_binding` scope using the current server secret and
Binding identifier. The Discord interaction dispatcher, signature parser, mutation
claim, settings service, actor validation, connection validation, Binding validation,
and stale-control responses remain unchanged.

The Tracker creates no new authority. It provides another current presentation of the
same existing capability.

## Hidden Work, Joined Presence, and Scheduled Tasks

Hidden Discord Work still commits canonical Work progress without a provider Tracker.
No settings-only replacement message is created. A later explicit invocation promotes
the active Work using the current visibility rules; the resulting Tracker contains both
actions.

Joined presence retains both existing actions. Leave presence retains only Session
navigation. Scheduled Task registration, deletion, and Tracker controls use their
existing dedicated renderers and never receive conversation settings.

## State, Migration, and Compatibility

No database, API, event, schema, generated client, configuration, or credential change
is required. No persisted component or legacy fallback is introduced.

Direct controls are process-local one-attempt effects. Removing Discord planning and
lowering therefore requires no durable queue migration or cleanup. Slack planning
remains accepted.

Rollout is the ordinary application deployment. Rollback restores the prior Discord
settings-only message and one-button Tracker without data conversion.

## Failure, Retry, and Recovery

Tracker creation and update keep their existing delivery result, provider identity,
revision fence, one-attempt execution, and reconciliation behavior. An invalid delivery
target or missing Binding identifier fails through the existing invalid-payload path
instead of publishing a partially authorized Tracker.

Component clicks retain current bounded rejection for invalid signatures, stale or
disconnected Bindings, unavailable connections, actor mismatch, and invalid
conversation scope. No new retry or recovery work is created.

## Observability and Operational Risks

Existing provider fake evidence records sanitized action identifiers and safe delivery
categories. This is sufficient to prove both Tracker actions and the absence of an
extra settings-only message without retaining signed custom IDs.

The primary implementation risk is changing only one ingress path or only one Tracker
mutation path. Focused tests cover synchronous and queued admission plus Tracker create
and update. Source absence checks cover the removed Discord-only control.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected evidence |
| --- | --- |
| Initial visible Discord conversational Work | joined presence and Activity Tracker are delivered; the Tracker reports both sanitized action IDs |
| Existing-Binding explicit invocation | one visible Tracker is created or updated and no settings-only Discord delivery is added |
| Hidden all-messages Work | no Tracker and no settings-only message are delivered |
| Late explicit invocation during hidden active Work | exactly one Tracker appears with both actions |
| Slack follow-up invocation | existing Slack settings control behavior remains unchanged |
| Scheduled Task Discord Tracker | existing Scheduled Task controls remain unchanged |

The required public External Channel E2E suite and deterministic Discord provider fake
are the primary acceptance evidence. No live credentials, new fixture, prerequisite
snapshot, or optional skip is required. Required deterministic scenarios must fail
rather than skip when expected action or delivery evidence is absent.

### Focused backend verification

- Discord presentation tests assert the exact two-button action row.
- Discord action-service tests cover both Tracker create and update with a signed
  Binding settings action.
- Mailbox-ingestion and ingress-queue tests prove Discord does not plan the direct
  control while Slack still does.
- Existing Discord settings scope and interaction tests remain the authorization
  regression gate.
- Ruff, configured type checking, focused Pytest, documentation validation,
  pre-commit, and required GitHub CI must pass.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Discord follow-up settings-only direct-control planning | `discord-260829/REQ-2`, `REQ-4` | visible conversational Tracker settings action; Slack plan retained | synchronous and queued ingress conditions | focused tests assert Discord skips and Slack preserves planning |
| Discord `binding_settings_on_demand` delivery branch | `discord-260829/REQ-2` | Tracker create/update component rendering | Discord action-service lowerer | source search finds no Discord lowerer for the control kind |
| Dedicated Discord settings-only presentation helper and tests | `discord-260829/REQ-2` | shared conversational Tracker action-row helper | Discord presentation module | source search finds no helper or settings-only Embed description |
| Existing signed Binding settings scope and interaction handlers | None; retained | `discord-260829/REQ-3` and current External Channel Specs | unchanged settings scope and dispatcher | existing settings tests pass without contract changes |
| Slack direct-control payload and lowerer | None; retained | `discord-260829/REQ-4` | unchanged Slack path | focused Slack admission/action tests pass |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Every Discord conversational Tracker create and update renders Session navigation plus the existing signed Binding settings action from the current delivery target | `discord-260829/REQ-1`, `REQ-3`; current Tracker navigation and settings-scope Specs | `derived` |
| M2 | Both ingress paths stop preparing the settings-only direct control for Discord while retaining it for Slack | `discord-260829/REQ-2`, `REQ-4` | `required` |
| M3 | Existing Discord component parsing and current-state authorization remain the sole settings interaction authority | `discord-260829/REQ-3`; current provider-ingress Spec | `existing` |
| M4 | Hidden Work, joined presence, Slack, and Scheduled Task presentation retain their current lifecycle behavior | `discord-260829/REQ-4`; current delivery and lifecycle Specs | `required` |

## Authority Audit

- Every Requirement maps to one or more mechanisms and deterministic evidence.
- M1 derives presentation from the required combined actions and the existing
  delivery-time navigation/settings authorities without introducing persisted state.
- M2 is the exact provider-scoped removal required by the requester.
- M3 and M4 retain current authoritative behavior and add no optional fallback.
- No unapproved API, persistence, configuration, lifecycle, or authorization mechanism
  is introduced.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

| Area | Result | Repository evidence |
| --- | --- | --- |
| Tracker create/update | Feasible | both Discord progress operations already resolve current Session navigation and receive a Binding-owned provider target |
| Signed settings action | Feasible | joined presence already builds `open_binding` from the same target Binding ID |
| Synchronous admission | Feasible | provider identity is present on the typed ingress locator before direct-control planning |
| Queued admission | Feasible | each typed ingress item carries its provider before settings-trigger selection |
| Hidden Work | Feasible | visibility already suppresses Tracker planning until explicit promotion |
| Slack preservation | Feasible | Slack uses the same payload but a separate provider lowerer |
| Scheduled Tasks | Feasible | Discord Scheduled Task controls use dedicated control renderers |
| Deterministic testing | Feasible | provider fake exposes sanitized delivery category and action identifiers |

No confirmed Requirement is blocked and no material choice remains.

Feasibility result: **feasible for Design revision 1**.

## Assumptions and Non-Blocking Risks

- Every conversational progress target has the Binding identifier already required by
  Work ownership. Missing authority fails closed.
- A Tracker deleted after final reply no longer exposes settings, while joined presence
  and provider-native commands remain available under their existing lifecycle.
- Sanitized provider evidence is sufficient for E2E assertions; signed IDs remain
  intentionally absent from test output.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-29`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: Implement the requester-directed Discord conversational Tracker
  settings action, remove the Discord follow-up settings-only message, preserve the
  existing signed Binding authorization and all explicitly unaffected presentation
  paths, and deliver the change through one focused pull request without further
  intermediate approval stops.
