---
title: "Agent Profile Image Historical Decision Reconstruction"
created: 2026-04-21
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: profile-260421
historical_reconstruction: true
migration_source: "docs/azents/design/agent-profile-image.md"
---

# Agent Profile Image Historical Decision Reconstruction

- Snapshot: `profile-260421`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/agent-profile-image.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### profile-260421/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decision Summary (Discussion #2830)

| # | Decision |
|---|---|
| P1 | Give up Discord per-agent avatar (keep Bot API) |
| P2 | avatar is public information + unguessable hash in URL (`secrets.token_hex(16)`) |
| P3 | Scope is Agent only in this iteration |
| P4 | Default avatar: web uses client initials, Slack omits `icon_url` |
| P5 | Discard original image and store thumbnails only |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
