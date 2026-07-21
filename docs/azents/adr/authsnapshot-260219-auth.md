---
title: "nointern-web Authentication System Historical Decision Reconstruction"
created: 2026-02-19
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: authsnapshot-260219
historical_reconstruction: true
migration_source: "docs/azents/design/auth.md"
---

# nointern-web Authentication System Historical Decision Reconstruction

- Snapshot: `authsnapshot-260219`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/auth.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### authsnapshot-260219/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture Overview

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

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
