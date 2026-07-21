---
title: "Full-stack Local Test Environment — Stage 2 (LLM Pipeline) Historical Requirements Reconstruction"
created: 2026-04-08
implemented: 2026-04-08
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: llm-260408
historical_reconstruction: true
migration_source: "docs/azents/design/llm-pipeline.md"
---

# Full-stack Local Test Environment — Stage 2 (LLM Pipeline) Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `llm-260408`
- Source: `docs/azents/design/llm-260408-llm-pipeline.md`
- Historical source date basis: `2026-04-08`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

With Stage 1a/1b/1c, agent can now perform **clean state → infra+devserver start → user/workspace/agent seed** in one flow. Stage 2 verifies that LLM pipeline (Engine Worker → LLM provider → broker → ws) runs end-to-end by **opening WebSocket chat session, sending one message, then observing event stream**.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

```python
import os
from seed import auth, workspace, llm, agent
from live import chat, matchers

## Supporting Scenarios

```python
import os
from seed import auth, workspace, llm, agent
from live import chat, matchers

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
