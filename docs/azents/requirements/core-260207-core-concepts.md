---
title: "nointern Core Concepts Historical Requirements Reconstruction"
created: 2026-02-07
implemented: 2026-03-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: core-260207
historical_reconstruction: true
migration_source: "docs/azents/design/core-concepts.md"
---

# nointern Core Concepts Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `core-260207`
- Source: `docs/azents/design/core-260207-core-concepts.md`
- Historical source date basis: `2026-02-07`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern is an **Agent Builder SaaS** where users can **create AI agents only with a system prompt and tool set** and use them together as a team in messaging platforms such as Slack.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Geonwoo: "@agent find empty calendar time and schedule code review"

Session: (Slack #backend, Geonwoo) → Token Resolution:
  Google Calendar query → Geonwoo personal integration (Geonwoo OAuth)
  Jira PR list          → team integration (read-only)
  Calendar event create → Geonwoo personal integration (Geonwoo OAuth)
  Teammate A calendar   → inaccessible (no A token)

## Supporting Scenarios

Geonwoo: "@agent find empty calendar time and schedule code review"

Session: (Slack #backend, Geonwoo) → Token Resolution:
  Google Calendar query → Geonwoo personal integration (Geonwoo OAuth)
  Jira PR list          → team integration (read-only)
  Calendar event create → Geonwoo personal integration (Geonwoo OAuth)
  Teammate A calendar   → inaccessible (no A token)

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

```python
MAX_TEAM_DEPTH = 3

def can_create_sub_team(parent_team: Team) -> bool:
    return parent_team.depth < MAX_TEAM_DEPTH
```

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
