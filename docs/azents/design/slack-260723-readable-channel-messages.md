---
title: "Readable Slack Channel Messages Design"
created: 2026-07-23
implemented: 2026-07-23
tags: [slack, external-channel, frontend, engine, delivery]
document_role: primary
document_type: design
snapshot_id: slack-260723
---

# Readable Slack Channel Messages Design

- Snapshot: `slack-260723`
- Requirements: [`slack-260723/REQ`](../requirements/slack-260723-readable-channel-messages.md)
- ADR: [`slack-260723/ADR`](../adr/slack-260723-readable-channel-messages.md)

## Scope and Traceability

| Requirement | Decision | Mechanism |
| --- | --- | --- |
| `REQ-1` | `ADR-D4` | Concise ExternalChannelMessage summary, body-preserving expansion, modal metadata inspector |
| `REQ-2` | `ADR-D1`, `ADR-D4` | Slack reference lookup, revision mappings, rendering substitution, sender ID detail |
| `REQ-3` | `ADR-D1` | Canonical event payload mapping and model-visible identity mapping section |
| `REQ-4` | `ADR-D2` | `markdown_text` reply delivery and Block Kit operational payload renderers |
| `REQ-5` | `ADR-D3` | Slack length constants in Tool schema and provider-bound commit validation |

## Current Gap

Inbound Slack normalization keeps raw sender/channel IDs and stores no reference mappings. Existing data records already support a principal display name and resource labels, but input projection currently receives no resolved values. The UI displays all source metadata in the expanded message. Slack delivery sends all replies and operational messages as plain `text`.

## Inbound Identity Resolution

`SlackConversationClient` will expose bounded lookups for conversations and users. The event processor resolves the current channel and sender, then parses a bounded number of Slack user/channel references from each delivered message. It records resolved values in a `reference_mappings` JSON object attached to the immutable revision. The raw body, provider message key, and original IDs remain canonical.

Each mapping has separate `users` and `channels` maps keyed by the provider ID. The processor treats reference lookup as enrichment: transient lookup failures preserve ingestion and use the provider ID as fallback. Required membership/access lookup remains authoritative for an invocation.

Hydration shares a per-run bounded lookup cache so thread pages do not repeat provider lookups for the same reference.

## Projection and Agent Context

Input-buffer projection moves the revision mapping into `ExternalChannelMessagePayload`. Model renderers keep raw body text and append one deterministic mapping table for the contiguous external turn. The table includes mappings present in the batch, which covers the sender, the current resource, and message references. UI metadata serializes the mapping as JSON and the web client substitutes supported Slack user/channel reference syntax only for visual rendering.

## Delivery

The explicit `channel_action` boundary remains unchanged.

- Reply intents persist Markdown text and invoke Slack `chat.postMessage` with `markdown_text`.
- Progress intents persist task data and render deterministic Block Kit header/section blocks with fallback `text`. Progress updates use `chat.update` with the same Block Kit payload.
- Access request intents render a Block Kit approval message whose primary action is a URL button.
- The delivery adapter validates Slack Markdown text length before issuing a provider request. The Tool input schema uses the same current Slack maximum; provider-bound commit validation is the future dialect extension point.

## UI

`ExternalChannelMessage` keeps an accessible disclosure control. Its summary has the Slack icon, sender display name, text preview, and status label only. Its expanded content contains the complete substituted body, the original-message link, and a detail button. The modal includes provider, resource, sender as `Name (short-ID)`, author type, authorization, lifecycle, timestamps, and revision data.

## Failure Handling

- Missing scopes, invalid credentials, and unavailable conversations retain the existing connection health behavior where the authoritative operation requires them.
- Enrichment lookup failures do not delete or alter inbound messages; unresolved references display raw IDs.
- A malformed persisted mapping is ignored by UI rendering rather than preventing message display.
- Over-limit Tool input fails validation or commit validation before any Slack request.

## Test Strategy

### E2E primary verification

Deterministic external-channel E2E will assert that an inbound Slack message yields readable source metadata, a `markdown_text` reply request, Block Kit progress payloads, and an approval button payload. The fake Slack provider will record non-secret request shapes only.

### Unit and component verification

- Slack API adapter tests cover channel/user lookup, reference extraction, Markdown and Block Kit payloads, and button actions.
- Event processor/repository/input-buffer tests cover persisted mappings and model context.
- Storybook interaction tests cover timeline summary, expanded original link, and modal metadata.
- TypeScript unit tests cover mapping parsing and safe visible-text substitution.

### CI policy

Run targeted Python and TypeScript checks locally, then require the repository PR CI—including deterministic and web-surface E2E—to pass before declaring the goal complete.

## Rollout and Rollback

The added revision mapping is nullable and old projected messages render with existing ID fallbacks. Reverting the feature preserves raw canonical bodies and provider action identity. No provider credential or public API migration is required.
