---
title: "Compacted Event Retention Decisions"
created: 2026-10-13
tags: [retention, conversation, backend]
document_role: primary
document_type: adr
snapshot_id: retention-261013
---

# Compacted Event Retention Decisions

Authority: [retention-261013/REQ](../requirements/retention-261013-compacted-events.md).

## D1. Age from first compaction displacement

- Reference: `retention-261013/ADR-D1`
- Accepted by the requester on 2026-10-13.
- Requirements: REQ-2, REQ-3.

Retention age starts at the successful compaction that first moves an event behind the model-input head. Repeated compaction preserves this original age. Event creation age was rejected because an old event could otherwise disappear immediately after a recent compaction.

The default is Unlimited, as explicitly revised by the requester. No installation or upgrade starts deleting historical events without an administrator selecting a finite policy.

This decision requires durable displacement evidence independent of subsequent summary deletion. The existing event row remains the source of truth; recording its first displacement timestamp is the local persistence implementation. Historical displacement timestamps can be recovered from the ordered retained summary events. Existing file-reference cleanup and active Run input ownership remain authoritative before permanent event deletion.
