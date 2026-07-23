---
title: "Readable Slack Channel Messages"
created: 2026-07-23
tags: [slack, external-channel, frontend, agent, architecture]
document_role: primary
document_type: adr
snapshot_id: slack-260723
---

# Readable Slack Channel Messages

- Snapshot: `slack-260723`
- Requirements: [`slack-260723/REQ`](../requirements/slack-260723-readable-channel-messages.md)

## Context

The existing external-message projection persists provider IDs and exposes its full metadata in the timeline. Slack delivery uses plain text for both conversational and operational output. The accepted requirements require readable presentation while retaining provider-safe action identity.

## Decisions

### slack-260723/ADR-D1. Retain canonical IDs and persist resolved reference mappings alongside revisions

**Affects:** `slack-260723/REQ-2`, `slack-260723/REQ-3`

Store the original Slack message body and sender/provider identity unchanged. Resolve the sender, current channel, and bounded in-body Slack user/channel references at provider processing time, then persist a bounded ID-to-display-name mapping with the immutable message revision.

The Agent and UI consume the same mapping. Presentation replaces references only at rendering time; Agent context contains both the original IDs and mappings.

**Rejected:** Replacing IDs inside the canonical body would lose actionable provider identity. Resolving only in the browser would require exposing Slack lookup capability and would not provide Agent context.

### slack-260723/ADR-D2. Use Slack Markdown for conversational replies and Block Kit for Azents operational messages

**Affects:** `slack-260723/REQ-4`

Use Slack's `markdown_text` field for Agent-authored conversational replies. Use Block Kit with a top-level accessible fallback `text` field for progress, authorization, and other Azents-generated operational messages. Use a URL button for approval actions.

**Rejected:** Sending all output as `markdown_text` leaves operational state visually unstructured. Sending both Markdown and Block Kit conflicts with Slack's message payload rules.

### slack-260723/ADR-D3. Enforce text limits at the Tool schema and delivery boundary

**Affects:** `slack-260723/REQ-5`

Expose the supported Slack Markdown maximum in the `channel_action` Tool schema and validate the value again against the bound provider before committing delivery. The provider-bound validation remains authoritative for future provider/channel dialects.

**Rejected:** Schema-only enforcement does not protect persisted delivery from malformed or legacy inputs. A generic lowest-common-denominator limit would unnecessarily constrain provider-specific capabilities.

### slack-260723/ADR-D4. Separate concise timeline summary from inspectable metadata

**Affects:** `slack-260723/REQ-1`, `slack-260723/REQ-2`

The timeline summary contains only the provider icon, sender, text preview, and status. Expanded content retains the body and original-message link. A modal detail view contains provider metadata, including the sender name plus abbreviated provider ID.

**Rejected:** Showing all metadata in the expanded card impairs mobile scanning and displaces message content.
