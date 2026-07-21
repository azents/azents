---
title: "Use Standard Responses for ChatGPT OAuth Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: standard-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0162-use-standard-responses-for-chatgpt-oauth.md"
---

# Use Standard Responses for ChatGPT OAuth Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `standard-260716`
- Source: `docs/azents/adr/standard-260716-standard-responses-for-chatgpt-oauth.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

ChatGPT's account model catalog exposes a `use_responses_lite` metadata field. Azents previously normalized that field into saved model capabilities and used it to select a private Responses Lite request dialect. That dialect moved tools into a developer `additional_tools` input item, moved instructions into developer input, added private compatibility and affinity headers, and changed reasoning and parallel-tool behavior.

Direct device-auth validation against the ChatGPT OAuth backend tested GPT-5.6 Sol, Terra, and Luna. All three models completed standard Responses requests and executed the provider-hosted `web_search` tool. The Responses Lite `additional_tools` dialect completed requests but did not execute hosted web search for any of the three models. Client function calls remained available in both dialects.

Supporting provider-hosted capabilities through Responses Lite would therefore require Azents to implement separate client-side executors coupled to private Codex endpoints and behavior. Responses WebSocket transport is a separate transport concern and does not require the Lite request dialect.

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
