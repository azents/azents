---
title: "Streaming Responsibility Migration — From Handler to Worker Historical Decision Reconstruction"
created: 2026-03-14
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: streaming-260314
historical_reconstruction: true
migration_source: "docs/azents/design/streaming-responsibility-migration.md"
---

# Streaming Responsibility Migration — From Handler to Worker Historical Decision Reconstruction

- Snapshot: `streaming-260314`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/streaming-responsibility-migration.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### streaming-260314/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decisions

| Item | Decision | Reason |
|------|------|------|
| API Client injection | Worker queries installation + caches client | keep message lightweight |
| History Fetching | performed in Worker | keep handler as thin layer |
| Discord message ID storage | Worker directly stores in DB | callback pattern unnecessary |
| Stop button | received via Input queue, adapter manages control message | same as existing stop path |
| Deployment unit | directly add Slack/Discord SDK dependencies to Worker | same pyproject currently used |
| Migration | big-bang switch | simpler implementation than gradual migration |
| poll_fn | remove SessionRunner internal queue; adapter provides poll_fn | consistent message handling including enrichment |
| Web event delivery | WebSocketBroadcast (Redis Pub/Sub) | multi-tab support, broadcast semantics needed |
| Installation cache invalidation | invalidate cache on 401 then re-query | avoid unnecessary DB query, same pattern as GitHub toolkit |

### Explicit source section: Relationship with `event-architecture-review.md`

Section E (multi-interface) in `event-architecture-review.md` decided Adapter pattern:

> Adapter responsibility: Message → channel-specific format conversion, Streaming policy, auth/permission mapping

This design is concrete implementation of that decision. Differences:
- Event architecture assumed Message View (DB based) → Adapter flow
- This design uses **direct delivery** of Engine event → Adapter
- Message View layer can be added during event architecture refactor (separate work)

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
