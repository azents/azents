---
title: "Slack/Discord Integration-Wide E2E Test Environment Historical Requirements Reconstruction"
created: 2026-04-11
implemented: 2026-04-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: integrations-260411
historical_reconstruction: true
migration_source: "docs/azents/design/integrations-e2e.md"
---

# Slack/Discord Integration-Wide E2E Test Environment Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `integrations-260411`
- Source: `docs/azents/design/integrations-260411-integrations-e2e.md`
- Historical source date basis: `2026-04-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Stage 4 (browser/web QA) of `testenv/nointern` made standalone UI flows of nointern-web automatable. On top of that, build an integrated test environment that can automatically verify **the whole Slack/Discord integration surface** — OAuth installation, user account linking, channel binding, messages/slash commands/interactions, files, agent toolkit permissions.

Scope expanded during Discussion from only initial OAuth (#2453 initial body) to **the entire integration surface**. First implementation target is **Slack**, and Discord follows same pattern after Slack completion.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

- After implementing new Slack feature, before PR merge — run `testenv/nointern/scenarios/integrations/TC-INT-SLACK-*.md` scenario once to confirm no regression.
- After modifying Slack OAuth code in nointern backend — immediately verify with Phase 2 OAuth scenario.
- After changing bot response flow — verify with Phase 3 message scenario.

## Supporting Scenarios

- After implementing new Slack feature, before PR merge — run `testenv/nointern/scenarios/integrations/TC-INT-SLACK-*.md` scenario once to confirm no regression.
- After modifying Slack OAuth code in nointern backend — immediately verify with Phase 2 OAuth scenario.
- After changing bot response flow — verify with Phase 3 message scenario.

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
