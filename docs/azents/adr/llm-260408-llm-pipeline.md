---
title: "Full-stack Local Test Environment — Stage 2 (LLM Pipeline) Historical Decision Reconstruction"
created: 2026-04-08
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: llm-260408
historical_reconstruction: true
migration_source: "docs/azents/design/llm-pipeline.md"
---

# Full-stack Local Test Environment — Stage 2 (LLM Pipeline) Historical Decision Reconstruction

- Snapshot: `llm-260408`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/llm-pipeline.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### llm-260408/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: (optional) low-level stream control

for ev in chat.stream(session, "Again"):
    print(ev["type"])
    if ev["type"] == "run_complete":
        break
```

### Explicit source section: Decision Summary

See Discussion #2378 for detailed rationale.

| # | Point | Decision |
|---|---|---|
| §2 | WebSocket vs browser | **C — separate Stage 2 ws, Stage 4 browser** |
| §3.1 | module granularity | **B — new top-level `live` package** |
| §3.2 | sync/async | **A — sync-only** (`websockets.sync`) |
| §3.3 | event collection | **C — `collect` primary + `stream` low-level in parallel** |
| §3.4 | timeout/failure | default 60s, `ChatTimeout(collected_events=...)`, `ChatConnectionError` |
| §3.5 | LLM API key | **A — caller passes explicitly** (Stage 1c pattern) |
| §3.6 | matcher | **C — raw + matcher in parallel** |
| §3.7 | image | **C — text first, add image phase within same Stage 2** |
| §3.8 | preflight `llm-api-key-set` | **C — preflight WARN + chat failure message in parallel** |

### Explicit source section: Architecture

```mermaid
flowchart LR
    Agent([Agent]) -->|seed| Seed[seed.*]
    Seed -->|User, Workspace,<br/>Integration, Agent| Obj[(domain objects)]

    Agent -->|chat.start_session| Chat[live.chat]
    Obj --> Chat

    Chat -->|1. chat_v1_issue_ws_ticket| Public[Public API :8010]
    Public -->|ticket| Chat

    Chat -->|2. ws connect<br/>/chat/v1/sessions/<br/>{session_id}?ticket=| WS[WebSocket]
    WS --> Worker[Engine Worker]
    Worker --> LLM[LLM Provider]
    LLM --> Worker
    Worker --> Broker
    Broker -->|run_started,<br/>content_delta,<br/>text_item,<br/>run_complete, ...| WS
    WS --> Chat

    Chat -->|collect → list[dict]| Agent
    Agent -->|matchers.*| Matchers[live.matchers]
    Matchers --> Agent

    Chat -.->|import error path| Errors[live.errors]
    Errors -.->|ChatTimeout, ChatConnectionError| Agent
```

Break existing e2e `create_chat_session` flow (ticket issue → ws connect → send init message → session polling) into building blocks and place into `start_session`; separate event stream collection into `collect`/`stream`.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
