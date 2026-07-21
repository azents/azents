---
title: "Home-as-agent-list Reorganization Historical Decision Reconstruction"
created: 2026-04-21
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: home-260421
historical_reconstruction: true
migration_source: "docs/azents/design/home-as-agent-list-2026-04-21.md"
---

# Home-as-agent-list Reorganization Historical Decision Reconstruction

- Snapshot: `home-260421`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/home-as-agent-list-2026-04-21.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### home-260421/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
graph TB
  subgraph "Before"
    H1[/w/handle: placeholder/]
    A1[/w/handle/agents: AgentList + filter/]
    S1[Sidebar: Home + Subagents + Agents inline]
  end

  subgraph "After"
    H2[/w/handle: AgentList + filter/]
    S2[Sidebar: Home + Agents inline]
  end

  H1 -. "Migrate AgentList" .-> H2
  A1 -. "Delete · redirect" .-> H2
  S1 -. "Remove Subagents entry" .-> S2
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
