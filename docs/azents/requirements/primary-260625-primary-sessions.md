---
title: "Primary Agent Sessions and Team-First Multi-Session UX Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: primary-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0074-primary-agent-sessions.md"
---

# Primary Agent Sessions and Team-First Multi-Session UX Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `primary-260625`
- Source: `docs/azents/adr/primary-260625-primary-sessions.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents originally forced an agent-centered single-session model. That decision was intentional.

Single-session benefits:

1. **External communication continuity** — Slack, GitHub, alerts, issue comments, and other external interfaces often participate in one workflow. If every external channel or thread becomes a separate session, context does not naturally move from Slack discussion to code work to PR review and back to Slack. Requiring users to understand and choose session IDs for integrations is not acceptable product UX.
2. **Short-term working context continuity** — Users often perceive the same agent as one contributor. If related alert or PR work is split into multiple hidden sessions, users expect knowledge to transfer but it will not. Long-term memory is not a good substitute for short-term session context sharing because the agent cannot know what another session needs in real time.
3. **Agent as an individual contributor** — The product direction is that an agent becomes an IC-like teammate. It must accumulate feedback from its own work, PR reviews, corrections, and team preferences. Overly ephemeral sessions weaken that feedback loop.

However, the single-session model also creates hard limitations:

1. **Parallelism** — A development agent that can only do one thing at a time is too constrained. Creating many separate agents is not a good substitute because agent creation, runtime resources, configuration, and accumulated expertise are not cheap.
2. **Privacy** — Even for a team agent, not every interaction should be visible to the team. A user may want to ask the same agent a private question, use a different language, draft something before sharing, or use user-specific credentials without putting the conversation in a team transcript.
3. **Scheduled/background work isolation** — Scheduled work should not interrupt an unrelated user conversation in the same transcript.

The target must preserve the continuity benefits of single-session usage while allowing explicit parallel sessions later.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
