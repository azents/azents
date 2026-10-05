---
title: "Normalized Usage Retention Requirements"
created: 2026-10-05
implemented: 2026-10-05
tags: [engine, usage, performance]
document_role: primary
document_type: requirements
snapshot_id: usage-261005
---

# Normalized Usage Retention

## Primary Outcome

Model calls retain useful normalized accounting without indefinitely retaining provider-native usage receipts. The earlier exploratory purpose of retaining unknown provider response shapes no longer justifies storing full receipts for every call.

## Requirements

### REQ-1 — Retain normalized accounting

Preserve input, output, total, cache-read, cache-write and reasoning token quantities, truthful nullable costs and cost provenance. Successful output, applied model routes and compaction behavior remain unchanged. Unknown evidence must remain unknown rather than become a fabricated zero.

### REQ-2 — Remove durable native usage receipts

New usage records and usage projections do not retain or expose native raw usage or adapter-private hidden parameters, including item attribution. Raw receipt inspection and retrospective reinterpretation are intentionally no longer supported through durable usage records.

### REQ-3 — Preserve normalization and pricing

Provider-specific parsing and pricing still consume receipt evidence before it is discarded. Cache TTL, media quantities and unavailable-cost behavior must not regress.

### REQ-4 — Respect existing data and deployment boundaries

Existing normalized accounting remains readable. Physical deletion of historical receipts, live DB mutation and deployment are outside this implementation request. No generic receipt archive, retention setting or replacement cache is introduced.

## Acceptance

- Provider normalization and pricing tests preserve the prior numerical/null outcomes.
- Usage serialization and public schemas omit receipt fields, even when reading old records containing those extras.
- Context and chat usage displays continue to use normalized values.
- Focused and full backend validation plus generated-client frontend checks pass.

## Requester Confirmation

The requester explained the original exploratory retention purpose, reviewed the proposal to discard receipts after normalization/pricing, and explicitly requested removal on 2026-10-05. This document records that already-confirmed scope; the temporary repository request note was created before code changes.
