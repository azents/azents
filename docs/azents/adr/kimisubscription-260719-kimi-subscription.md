---
title: "Kimi Subscription Provider Historical Decision Reconstruction"
created: 2026-07-19
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: kimisubscription-260719
historical_reconstruction: true
migration_source: "docs/azents/design/kimi-subscription-provider.md"
---

# Kimi Subscription Provider Historical Decision Reconstruction

- Snapshot: `kimisubscription-260719`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/kimi-subscription-provider.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### kimisubscription-260719/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Validated Upstream Contract

The design was validated against MoonshotAI/kimi-cli commit `4a550effdfcb29a25a5d325bf935296cc50cd417` (version 1.49.0).

| Concern | Upstream contract |
|---|---|
| OAuth host | `https://auth.kimi.com` |
| Public client id | `17e5f671-d194-4dfb-9706-5516cb48c098` |
| Device authorization | `POST /api/oauth/device_authorization` |
| Device and refresh token | `POST /api/oauth/token` |
| Runtime base URL | `https://api.kimi.com/coding/v1` |
| Account model listing | `GET /models` |
| Subscription usage | `GET /usages` |
| Required identity headers | `X-Msh-Platform`, `X-Msh-Version`, `X-Msh-Device-Name`, `X-Msh-Device-Model`, `X-Msh-Os-Version`, `X-Msh-Device-Id` |

### Explicit source section: Provider and Credential Contracts

Add `LLMProvider.KIMI_OAUTH` and `LLMModelDeveloper.MOONSHOT`.

Encrypted integration secrets:

```json
{
  "type": "kimi_oauth",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-07-19T20:00:00Z",
  "device_id": "..."
}
```

Plain integration config:

```json
{
  "type": "kimi_oauth",
  "connection_method": "device",
  "status": "connected",
  "connected_at": "2026-07-19T19:00:00Z",
  "last_refreshed_at": "2026-07-19T19:00:00Z",
  "last_failed_at": null,
  "last_failure_reason": null
}
```

The generic integration response may expose config but never secrets.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
