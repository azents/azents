---
title: "nointern-web Authentication System Historical Requirements Reconstruction"
created: 2026-02-19
implemented: 2026-02-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: authsnapshot-260219
historical_reconstruction: true
migration_source: "docs/azents/design/auth.md"
---

# nointern-web Authentication System Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `authsnapshot-260219`
- Source: `docs/azents/design/authsnapshot-260219-auth.md`
- Historical source date basis: `2026-02-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Next.js web serves as **BFF (Backend For Frontend)**. It safely manages tokens between browser and nointern API.

```mermaid
flowchart LR
    Browser -->|tRPC<br/>cookie sent| NextJS[Next.js Server]
    NextJS -->|@azents/public-client<br/>Bearer token| API[nointern API]
```

**Core principles**:
- Tokens are not exposed to browser JavaScript (httpOnly cookies).
- All token management is handled by Next.js server.
- Client only knows auth state, not token itself.
- Use `@azents/public-client` (OpenAPI generated client).

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
