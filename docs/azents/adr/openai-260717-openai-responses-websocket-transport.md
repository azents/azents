---
title: "OpenAI Responses WebSocket Transport Historical Decision Reconstruction"
created: 2026-07-17
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: openai-260717
historical_reconstruction: true
migration_source: "docs/azents/design/openai-responses-websocket-transport.md"
---

# OpenAI Responses WebSocket Transport Historical Decision Reconstruction

- Snapshot: `openai-260717`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/openai-responses-websocket-transport.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### openai-260717/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Transport Architecture

```mermaid
flowchart TD
    Transcript[Canonical event transcript] --> Lowerer[OpenAIResponsesLowerer]
    Lowerer --> Request[Complete OpenAIResponsesRequest]
    Request --> Guard[NativeRequestSizeGuard]
    Guard --> Eligibility{WebSocket eligible?}
    Eligibility -->|No| HTTP[Official SDK HTTP stream]
    Eligibility -->|Yes| Socket[Execution-owned Responses WebSocket]
    Socket --> Events[Official SDK Responses events]
    HTTP --> Events
    Events --> Normalizer[OpenAIResponsesOutputNormalizer]
    Normalizer --> Live[Live projections]
    Normalizer --> Durable[Durable output after exact terminal]
    Socket -->|Transport failure| Sticky[SessionRunner HTTP-only state]
    Sticky --> FailedRun[Shared failed-Run retry]
    FailedRun --> HTTP
```

### Explicit source section: CI policy and skip/fail rules

- Unit and backend integration tests are mandatory and fail the PR on any error.
- Deterministic E2E remains mandatory where selected by the existing CI workflow.
- Live external tests run only through the repository's opt-in live workflow or maintainer authorization.
- An explicitly requested live run fails when credentials or prerequisite snapshots are missing; optional nightly runs may report prerequisite-not-ready as skipped.
- A terminal event other than the accepted exact typed boundary fails the live test rather than being accepted heuristically.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
