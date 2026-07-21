---
title: "Event Architecture Review Discussion Historical Decision Reconstruction"
created: 2026-03-08
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: event-260308
historical_reconstruction: true
migration_source: "docs/azents/design/event-architecture-review.md"
---

# Event Architecture Review Discussion Historical Decision Reconstruction

- Snapshot: `event-260308`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/event-architecture-review.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### event-260308/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Nointern Event Architecture Review Discussion

> Discussion record from 2026-03-08. Based on design in `unified-event-architecture.md`, discusses problems in current structure and improvement direction.

---

### Explicit source section: Decision: Pydantic `BaseModel(frozen=True)` + Discriminated Union

```python
from pydantic import BaseModel, ConfigDict
from typing import Annotated, Literal, Union
from pydantic import Discriminator

class TextEvent(BaseModel):
    """Text event."""
    model_config = ConfigDict(frozen=True)
    type: Literal["text"] = "text"
    content: str
    attachments: list[Attachment] = []

class ToolCallEvent(BaseModel):
    """Tool call event."""
    model_config = ConfigDict(frozen=True)
    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
