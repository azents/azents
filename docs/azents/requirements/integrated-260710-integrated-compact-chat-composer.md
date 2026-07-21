---
title: "Use a Compact Integrated Chat Composer Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: integrated-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0110-integrated-compact-chat-composer.md"
---

# Use a Compact Integrated Chat Composer Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `integrated-260710`
- Source: `docs/azents/adr/integrated-260710-integrated-compact-chat-composer.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current chat composer places attachment and Send/Stop controls outside the textarea on its left and right. That row has no remaining horizontal space for per-prompt model and reasoning-effort controls, especially on mobile. Adding another external control row would also consume scarce vertical viewport space when the mobile keyboard is open.

The composer already has a Goal/Todo preview attached above the input. The redesign must preserve its session-context role, distinguish it from prompt-scoped inference controls, and avoid turning the lower viewport into a stack of persistent bars. Mobile Safari also zooms focused form controls whose rendered text is smaller than 16 CSS pixels, so the textarea font size cannot be reduced to make the layout fit.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

This consumes excessive vertical space and obscures the distinction between session context and prompt settings.

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
