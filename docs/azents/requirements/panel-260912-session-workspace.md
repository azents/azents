---
title: "Session Workspace Navigation Requirements"
created: 2026-09-12
updated: 2026-09-12
implemented: 2026-09-12
tags: [frontend, session]
document_role: primary
document_type: requirements
snapshot_id: panel-260912
---

# Session Workspace Navigation Requirements

## Confirmation and scope

The requester confirmed this behavior on September 12, 2026 and explicitly requested implementation and a PR. The concept mock establishes the outer navigation model; implementation details must be refined using real components in Storybook. This records the confirmed scope, rather than opening another product-approval gate.

## Primary scenario

A user converses with an Agent while inspecting existing session information, files, delegated work, connected channels, scheduled work, and runtime tools without replacing or losing the conversation.

## Requirements

### REQ-1 — Persistent conversation

The main session surface remains Chat. Remove the page-wide Chat/Context/Subagents/Channels/Scheduled Tasks tab strip. Selecting a supporting feature must preserve the conversation, composer draft, timeline state, and active session.

### REQ-2 — Unified supporting panel

Existing non-Chat session features are accessible through one panel that can be opened and closed. This includes files/projects, context and its diagnostics, subagents, channels, scheduled tasks, runtime management, and terminal. Preserve each feature's operations, authorization, session targeting, and existing internal responsive behavior. The work does not introduce a Canvas editor or redesign individual feature contents.

### REQ-3 — Mobile-first direct access

On mobile, the panel contains a single horizontal row of directly selectable feature tabs above full-width feature content. Do not allocate a side-by-side navigation column, introduce a separate function-list/detail navigation stage, or stack a feature-selection overlay over the panel. Do not use a select control. The conversation remains the underlying main surface while the panel is open.

### REQ-4 — Discoverable overflow

When mobile feature tabs overflow, directional visual cues indicate more content. Provide fades and operable scroll arrows only in directions that have additional content. Touch scrolling and keyboard activation remain available; selecting a tab reveals its active position. Avoid document-level horizontal overflow.

### REQ-5 — Desktop supporting work

On desktop, the supporting panel remains next to Chat and provides a visible vertical feature list. Opening, closing, selecting, and resizing the supporting panel preserve existing feature and conversation behavior. No feature selection replaces the main conversation.

### REQ-6 — Preserve feature internals

Limit changes to navigation, placement, and outer panel behavior. In particular, do not replace the mobile file browser with a new list/detail split. Preserve existing diagnostics, subagent navigation, channel management, schedule editing, runtime controls, and terminal interactions. Existing feature state must not be duplicated into inconsistent concurrently mounted panels.

### REQ-7 — Verification and delivery

Use Storybook with actual product components and providers to inspect desktop and narrow mobile states while implementing. Verify tab overflow edges, panel open/close, feature selection, preserved drafts, and existing operations through appropriate tests. Deliver a PR with validation results; merging is not authorized by this request.

## Non-goals

New backend or runtime APIs, a new Canvas editor, new feature-specific UX, additional mobile bottom navigation, and production infrastructure changes.
