---
title: "Session Workspace Navigation Design"
created: 2026-09-12
updated: 2026-09-12
tags: [frontend, session]
document_role: primary
document_type: design
snapshot_id: panel-260912
---

# Session Workspace Navigation Design

References: [Requirements](../requirements/panel-260912-session-workspace.md),
[ADR](../adr/panel-260912-session-workspace.md).

## Design Authority

Revision: 1.

| Mechanism | Authority | Classification |
| --- | --- | --- |
| M1: stable Chat entry with URL-selected supporting panel | REQ-1, REQ-2; ADR-D1 | decided |
| M2: desktop split and mobile single-column panel | REQ-3, REQ-5; ADR-D2 | decided |
| M3: measured tab overflow cues and keyboard access | REQ-4; ADR-D2 | required |
| M4: existing feature components and embedded terminal | REQ-6; ADR-D2 | decided |
| M5: Storybook plus browser and unit verification | REQ-7 | required |

## Mechanisms

`useSessionPanelState` owns URL selection, panel visibility, selected task deep
links, and the desktop split ratio. `ChatSessionView` hosts a persistent Chat
surface and one supporting panel. The header exposes one panel toggle.

`SessionSidePanel` connects a DOM-measurement hook to a prop-driven presentation.
The mobile tab strip measures client/scroll width and scroll position; arrows
appear only toward additional content. Keyboard arrows, Home, and End select
and reveal tabs. Desktop retains a vertical list. Panel layout, rather than each
feature, is responsible for available content width.

Context, Subagents, Channels, and Scheduled Tasks retain their existing content
and data containers without repeated page headers. Workspace content remains one
mounted instance; its files, metrics, and settings are selected by outer panel
navigation. The terminal retains one host and connection owner while its outer
presentation is bounded by the supporting panel.

## Removal and Replacement

| Removed surface | Authority and replacement | Absence verification |
| --- | --- | --- |
| Page-wide session tabs and non-Chat route dispatch | REQ-1; M1 | header has no tab strip; route returns Chat entry |
| Runtime-only mobile Drawer | REQ-2/3; M2 | no Drawer in ChatSessionView |
| ChatView-owned workspace split | REQ-2/5; M2 | ChatView is conversation-only |
| Separate session terminal dock/focused page replacement | REQ-2/6; M4 | terminal is embedded, does not replace Chat |
| Repeated supporting-page session headers | REQ-1/2; M1/M4 | one session header |

Existing feature internals, authorization, API clients, runtime protocol, and
file browser list/preview navigation retain their existing authority.

## Test Strategy

- Primary Web E2E: extend the existing Runtime browser journey to cover mobile
  panel open/close, Context URL selection, full-width content, directional tab
  cues, preserved composer input, and return to Runtime/metrics operations.
- Existing Web-suite infrastructure provides product-created user, workspace,
  model selection, Runtime, session, Selenium browser, and worktree Web images.
  No new fixture, live provider credential, or direct database write is needed.
- Storybook/browser matrix: 390x844 and 320x640 mobile, 1440x960 desktop,
  workspace content, terminal embedding, overflow, panel toggling, and drafts.
  Use actual shared providers, native DPR 1 captures, and inspect final PNGs.
- Unit tests cover recognized panel routes, query transition cleanup, and tab
  boundary calculations. Run localization tests, format, lint, typecheck, and
  Next.js production build.
- Required CI owns Web E2E execution and its standard JUnit/log/screenshot
  artifacts. Missing runtime/browser prerequisites fail or block that suite;
  local Storybook success does not claim service-backed E2E success.

## Design Approval

- Mode: requester-approved direct implementation.
- Decision owner: requester for product scope; implementing Agent for equivalent
  component wiring.
- Date: 2026-09-12.
- Approved revision: 1.
- Authority set: M1, M2, M3, M4, M5.
- Scope: outer session navigation, panel placement, and preserved existing
  functionality; refine visual details in Storybook and deliver a PR.
