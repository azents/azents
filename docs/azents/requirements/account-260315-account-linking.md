---
title: "External Platform Account Linking Historical Requirements Reconstruction"
created: 2026-03-15
implemented: 2026-03-15
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: account-260315
historical_reconstruction: true
migration_source: "docs/azents/design/account-linking.md"
---

# External Platform Account Linking Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `account-260315`
- Source: `docs/azents/design/account-260315-account-linking.md`
- Historical source date basis: `2026-03-15`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Design feature that links external platform user IDs such as Slack/Discord with nointern user ID. After linking completes, bot can identify the user on mention and provide personalized responses plus per-user OAuth toolkit usage.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

When user mentions nointern bot for first time in Slack/Discord, user receives account link nudge by DM and links account.

```mermaid
sequenceDiagram
    actor U as User (Slack/Discord)
    participant Bot as nointern bot
    participant Server as Nointern Server
    participant Web as Nointern Web
    participant OAuth as Platform OAuth

    U->>Bot: @nointern mention
    Bot->>Server: message handling
    Server->>Server: resolve_user_id() → None
    Server->>Server: has_previous_sessions() → false
    Server->>U: DM nudge "Link your account to get personalized responses" [Link]

    Note over Bot: Bot handles response anonymously (keep existing behavior)

    U->>Web: Click button → landing page

    alt logged in + workspace member
        Web->>OAuth: Platform OAuth authorize (scope: identify)
        OAuth->>U: auth screen
        U->>OAuth: approve
        OAuth->>Web: callback (code)
        Web->>Server: POST /callback {code, state}
        Server->>OAuth: code exchange → obtain platform_user_id
        Server->>Server: create_link(platform_user_id, installation_id, user_id)
        Server-->>Web: link complete
        Web->>U: "Linked!" screen
    else logged out
        Web->>Web: preserve returnTo
        Web->>U: redirect to login page
        U->>Web: login complete
        Web->>OAuth: Platform OAuth authorize
        Note over Web,OAuth: then same flow as above
    else no account
        Web->>U: "Ask workspace admin for invitation"
    end
```

## Supporting Scenarios

When user mentions nointern bot for first time in Slack/Discord, user receives account link nudge by DM and links account.

```mermaid
sequenceDiagram
    actor U as User (Slack/Discord)
    participant Bot as nointern bot
    participant Server as Nointern Server
    participant Web as Nointern Web
    participant OAuth as Platform OAuth

    U->>Bot: @nointern mention
    Bot->>Server: message handling
    Server->>Server: resolve_user_id() → None
    Server->>Server: has_previous_sessions() → false
    Server->>U: DM nudge "Link your account to get personalized responses" [Link]

    Note over Bot: Bot handles response anonymously (keep existing behavior)

    U->>Web: Click button → landing page

    alt logged in + workspace member
        Web->>OAuth: Platform OAuth authorize (scope: identify)
        OAuth->>U: auth screen
        U->>OAuth: approve
        OAuth->>Web: callback (code)
        Web->>Server: POST /callback {code, state}
        Server->>OAuth: code exchange → obtain platform_user_id
        Server->>Server: create_link(platform_user_id, installation_id, user_id)
        Server-->>Web: link complete
        Web->>U: "Linked!" screen
    else logged out
        Web->>Web: preserve returnTo
        Web->>U: redirect to login page
        U->>Web: login complete
        Web->>OAuth: Platform OAuth authorize
        Note over Web,OAuth: then same flow as above
    else no account
        Web->>U: "Ask workspace admin for invitation"
    end
```

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
