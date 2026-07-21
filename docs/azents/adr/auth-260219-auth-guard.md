---
title: "nointern-web Login Guard Historical Decision Reconstruction"
created: 2026-02-19
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: auth-260219
historical_reconstruction: true
migration_source: "docs/azents/design/auth-guard.md"
---

# nointern-web Login Guard Historical Decision Reconstruction

- Snapshot: `auth-260219`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/auth-guard.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### auth-260219/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
sequenceDiagram
    participant U as User
    participant L as Landing page
    participant W as /workspaces (Server Component)
    participant LR as LoginRequired
    participant LP as /login
    participant V as /login/verify

    U->>L: Click "Start with email"
    L->>W: Navigate to /workspaces
    W->>W: getInitialAuthState() - check cookie
    alt no cookie (unauthenticated)
        W->>LR: render <LoginRequired />
        LR->>U: Show login required UI
        U->>LP: Click login button (/login?next=/workspaces)
        LP->>V: Send email verification code and navigate (pass next param)
        V->>W: Auth success → redirect to next param
    else cookie exists (authenticated)
        W->>U: Render workspace list
    end
```

### Explicit source section: Key Design Decisions

1. **Dual-client pattern**: Separate `refreshClient` (no interceptor) and `client` (with interceptor) to prevent infinite loop.
2. **Proactive refresh**: Refresh 5 minutes before expiry to minimize 401 errors.
3. **resHeaders pattern**: Set Set-Cookie through tRPC `resHeaders` instead of `cookies()` API (tRPC compatibility).
4. **No encryption needed**: Unlike azents, use only httpOnly cookie without encryption (no COOKIE_SECRET required).

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
