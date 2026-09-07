---
title: "Discord Conversation Settings Select Controls Design"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, settings, backend, testenv]
document_role: primary
document_type: design
snapshot_id: settings-260907
---

# settings-260907/DESIGN: Discord Conversation Settings Select Controls

- Snapshot: `settings-260907`
- Document reference: `settings-260907/DESIGN`
- Requirements:
  [`settings-260907/REQ`](../requirements/settings-260907-discord-select-controls.md)
- Decisions:
  [`settings-260907/ADR`](../adr/settings-260907-discord-select-controls.md)

## Current Behavior and Gaps

The shared Discord settings response service renders connected parent settings as two rows of paired buttons and connected-thread settings as one paired-button row. Each button's signed custom ID encodes both the setting scope and the chosen value. A successful mutation replaces the settings surface with a terminal confirmation and clears all components.

Discord interaction decoding already retains one bounded `selected_value` for String Select interactions, but settings dispatch currently discards it. The settings response also lacks Session navigation even when canonical participation resolution has an exact connected Binding.

Slash commands, message commands, joined-presence actions, and Activity Tracker actions already converge on the same settings service. Replacing that shared renderer therefore provides one consistent settings surface without modifying each entry point separately.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `settings-260907/REQ-1` | M1, M2 |
| `settings-260907/REQ-2` | M2, M3 |
| `settings-260907/REQ-3` | M4 |
| `settings-260907/REQ-4` | M1, M5 |

## Architecture and Ownership

Canonical participation settings remain the source of truth for location, response mode, active Binding, route, actor authorization, and mutation generation fences. Discord presentation remains an ephemeral projection.

Participation resolution adds an optional provider-neutral Session navigation target only when its resolved Binding belongs to the authorized route. The target contains the current Workspace handle, Agent ID, and Binding-owned Session ID. The Discord settings renderer combines that target with the configured Web origin through the existing canonical Session URL builder. No URL or component payload is persisted.

## Select Presentation

Connected parent settings render three ordered component rows when Session navigation is available:

1. one String Select with placeholder `Where to respond` and options `This channel` and `Threads`;
2. one String Select with placeholder `When to respond` and options `When mentioned` and `Every message`; and
3. one link button labeled `View session`.

Connected-thread settings omit the location row. Settings without one exact Session omit the navigation row. Each Select requires exactly one value and marks the canonical current option as the default.

Every entry point uses the same response builder. First-time setup continues to render `Answer in this channel` and `Answer in threads` buttons because it is a one-time deferred continuation decision.

## Signed Scope and Selected Values

Connected-setting custom IDs encode a signed operation category rather than one action per possible value:

- parent location selection;
- parent response-mode selection; and
- thread response-mode selection.

The signed scope retains the origin interaction plus the current setting or Binding identity and generation fence. Discord's authenticated interaction payload supplies one selected value. Dispatch passes that value to the settings service, which validates a closed value set for the signed operation category before resolving or mutating canonical state.

Setup button actions retain their existing action-specific signed IDs and deferred handoff path. Open and open-Binding scopes remain unchanged.

## Mutation Response

A connected-setting selection uses the existing canonical parent or thread mutation. After commit, the service returns interaction response type 7 with the complete settings data rebuilt from the committed settings snapshot. The updated Select default provides immediate state feedback and leaves every applicable control available for a subsequent change.

Setup selection retains the existing terminal confirmation and deferred original-message continuation. Error and stale-control responses retain their current bounded component-clearing behavior.

## Session Navigation Projection

The participation service resolves Workspace and Agent identity during the existing authorized actor read. It derives navigation only when:

- an active connected Binding exists;
- the Binding belongs to the authorized route; and
- the current Workspace and Agent remain available.

Thread settings satisfy the exact-Binding condition by construction. Parent settings may omit navigation when the parent has no connected Binding, including a Threads-configured parent. Switching an active parent from Channel to Threads disconnects the parent Binding and causes the refreshed settings response to remove the Session link.

## State, Migration, Compatibility, and Rollback

No database, public API, event schema, generated client, provider credential, configuration, or durable interaction state changes. Existing ephemeral connected-settings buttons are replaced without a legacy fallback. Setup buttons and settings opener components remain compatible because their signed actions do not change.

Rollback restores paired buttons and terminal mutation confirmations. No data conversion is required.

## Failure, Retry, and Recovery

Missing, multiple, empty, or unsupported Select values fail through the existing invalid or unavailable settings response boundaries and do not mutate canonical state. Signed scope validation, origin validation, current setting/Binding generation checks, actor authorization, and connection validation remain mandatory.

A missing or invalid Web origin omits View session without blocking settings. Mutation cleanup plans retain their current one-attempt execution after the canonical commit. Re-rendering failure does not add retry or persisted recovery work.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected evidence |
| --- | --- |
| Open connected thread settings through a reconciled Discord command | one response-mode Select with the current default and one View session link |
| Select a new thread response mode | canonical Binding changes and the same ephemeral response is updated with refreshed Select and navigation controls |
| Open parent settings with a connected parent Binding | location Select, response-mode Select, and exact Session link are present |
| Open parent settings without a connected Binding | both Selects are present and Session navigation is absent |
| Open settings through Tracker or joined presence | the same shared connected-settings controls are returned |
| Open first-time setup | existing two setup buttons and deferred continuation remain unchanged |

The deterministic Discord provider fake records sanitized settings control roles and selected-default values without retaining signed custom IDs or full provider payloads. Required External Channel E2E exercises a reconciled command, a real signed Select interaction, canonical mutation, refreshed response, and exact Session path. Required scenarios fail rather than skip.

### Focused backend verification

- Settings-scope tests cover new operation-category codes, size bounds, parsing, and selected-value mapping.
- Discord interaction and HTTP tests require selected values for Select scopes and pass them to the settings service.
- Settings-service tests assert exact parent, thread, navigation, setup, re-render, stale, and all-entry-point behavior.
- Participation tests cover exact authorized navigation projection and omission without a Binding.
- Existing setup, cleanup-plan, Tracker/presence opener, Slack, and authorization tests remain regression gates.
- Ruff, configured type checking, focused Pytest, documentation validation, pre-commit, the full backend suite, required E2E, and GitHub CI must pass.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Connected parent and thread value-specific settings buttons | `settings-260907/REQ-1` | one String Select per independent setting axis | shared Discord settings renderer and signed scope action set | source and payload tests contain no connected-setting value buttons or value-specific action codes |
| Terminal connected-settings success confirmation that clears components | `settings-260907/REQ-2` | refreshed canonical settings response after commit | parent and thread mutation responses | service and E2E tests require updated Select controls after mutation |
| Settings surface without Session navigation | `settings-260907/REQ-3` | conditional canonical View session link | participation projection and Discord settings response | parent/thread payload tests cover presence and omission conditions |
| First-time setup buttons and deferred handoff | None; retained | `settings-260907/REQ-4` and current setup lifecycle | unchanged setup actions and confirmation | existing setup service, HTTP, and E2E tests remain green |
| Existing Tracker, presence, slash-command, and message-command settings openers | None; retained | `settings-260907/REQ-1`, `REQ-4` | unchanged open scopes feeding the shared renderer | opener tests prove every path resolves the same settings response |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Every connected Discord settings entry point uses one shared renderer with one String Select per independent setting axis | `settings-260907/REQ-1`; `settings-260907/ADR-D1` | `decided` |
| M2 | Signed operation-category scopes pair with one validated selected value from the authenticated Discord interaction | `settings-260907/REQ-1`, `REQ-4`; `settings-260907/ADR-D3` | `decided` |
| M3 | Successful connected-setting mutations update the original ephemeral response with the complete committed settings surface | `settings-260907/REQ-2`; `settings-260907/ADR-D2` | `decided` |
| M4 | Participation resolution projects exact Binding-owned Session navigation and Discord derives the canonical Web URL at render time | `settings-260907/REQ-3`; `settings-260907/ADR-D4` | `decided` |
| M5 | First-time setup retains action-specific buttons, deferred continuation, and terminal confirmation | `settings-260907/REQ-4`; `settings-260907/ADR-D5`; current External Channel Specs | `required` |

## Authority Audit

- Every Requirement maps to an approved mechanism and deterministic evidence.
- M1 and M2 implement the confirmed component model without altering setting semantics.
- M3 is required to keep multiple independent Selects usable in one settings visit.
- M4 exposes only an exact current Session and creates no alternative navigation authority.
- M5 preserves the explicitly unaffected pre-Session lifecycle.
- No unapproved persistence, API, configuration, provider, Slack, or compatibility mechanism is introduced.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

| Area | Result | Repository evidence |
| --- | --- | --- |
| Shared entry-point rendering | Feasible | slash command, message command, Tracker, and joined-presence open scopes converge on `DiscordSettingsResponseService` |
| String Select payload | Feasible | the existing Discord Agent selector already renders type-3 components with one bounded value |
| Selected-value ingress | Feasible | `DiscordInteractionEnvelope.selected_value` already validates and retains at most one value |
| Signed scope | Feasible | current settings custom IDs encode signed origin and setting/Binding generation fences within 100 characters |
| Immediate mutation | Feasible | parent and thread services already commit one selected axis per component interaction |
| Refreshed response | Feasible | component interactions already support response type 7 message updates |
| Session navigation | Feasible | active settings resolution has Binding Session identity and authorized Agent/Workspace ownership; the canonical URL builder already exists |
| Deterministic E2E | Feasible | the Discord provider fake delivers signed component interactions and records sanitized interaction evidence |

No confirmed Requirement is blocked and no material choice remains.

Feasibility result: **feasible for Design revision 1**.

## Assumptions and Non-Blocking Risks

- Discord displays each String Select in its own action row; the added vertical height is accepted in exchange for lower button density and clearer grouping.
- A parent location change can legitimately remove Session navigation when it disconnects the parent Binding.
- Existing ephemeral settings responses do not require legacy value-specific button compatibility across deployment.
- Sanitized E2E evidence records component roles and safe enum values only.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: Replace connected Discord Conversation settings choice buttons with shared Select controls across every entry point, refresh the same settings surface after immediate canonical mutations, add exact conditional Session navigation, preserve first-time setup and all authorization/provider boundaries, and deliver the change through one focused pull request without additional intermediate approval stops.
