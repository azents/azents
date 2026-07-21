---
title: "Agent-Focused Navigation Information Architecture"
created: 2026-06-26
tags: [architecture, frontend, ui, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: navigation-260626
historical_reconstruction: true
migration_source: "docs/azents/adr/0078-agent-focused-navigation-ia.md"
---

# navigation-260626/ADR: Agent-Focused Navigation Information Architecture

## Context

The Agent detail UI uses an Agent-focused shell with its own sidebar/drawer and Agent header. On
mobile, the global app bar plus the Agent header consume too much vertical space for chat. The Agent
sidebar also duplicated Agent section navigation (`Chat`, `Context`, `Settings`) that already belongs
to the Agent header/tab area. This duplication pushed the session list down and made it unclear which
navigation surface owned Agent section switching.

The workspace sidebar and Agent-focused sidebar should also feel like one product. Users move from the
workspace sidebar into an Agent-specific sidebar, so menu naming, grouping, and responsibilities should
stay consistent instead of changing meaning between screens.

## Decision

Use a consistent workspace-to-Agent navigation model with clear ownership boundaries:

- The workspace sidebar owns workspace-level navigation and Agent discovery:
  - workspace overview/home
  - members
  - Agent list/search/create entry points
  - workspace-level utilities such as toolkits, workspace settings, and profile
- The Agent-focused sidebar or mobile drawer owns Agent-level navigation that is not section switching:
  - back to workspace
  - current Agent summary
  - session creation
  - session list and active session selection
  - global actions that are removed from the Agent-focused header
- Agent section navigation (`Chat`, `Context`, `Settings`) stays in the Agent header/tab area on both
  desktop and mobile.
- Do not duplicate `Chat`, `Context`, or `Settings` inside the Agent-focused sidebar or mobile drawer.
- Mobile Agent detail screens should treat the Agent header as the primary top bar.
- Global actions are consistently removed from the Agent-focused header and move into the Agent drawer.
  The header should only keep Agent-task-local controls.
- Do not keep a dedicated WebSocket connection status indicator in the consolidated mobile Agent
  header. Runtime/workspace access may remain available, but the connection indicator is not worth the
  header space.
- Menu names should remain consistent between the workspace sidebar and Agent sidebar. The same concept
  should use the same label, and different concepts should not reuse a label with a different meaning.

## Consequences

- Chat gets more vertical space on mobile because the Agent mobile header can replace or absorb the
  global app bar instead of stacking below it.
- The session list becomes the main content of the Agent drawer/sidebar rather than being pushed below
  duplicated section navigation.
- Desktop and mobile keep the same ownership model: Agent sections are header tabs; Agent sessions are
  sidebar/drawer items.
- Global actions become drawer actions in Agent-focused mobile screens, which reduces header clutter
  but may add one extra tap for account/theme/logout access.
- Future layout work should update the workspace sidebar and Agent sidebar together so grouping and
  menu labels stay aligned.

## Migration provenance

- Historical source filename: `0078-agent-focused-navigation-ia.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
