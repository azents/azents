---
title: "Compacted Event Retention Requirements"
created: 2026-10-13
implemented: 2026-10-13
tags: [retention, conversation, backend]
document_role: primary
document_type: requirements
snapshot_id: retention-261013
---

# Compacted Event Retention Requirements

- Snapshot: `retention-261013`
- Document reference: `retention-261013/REQ`

## Problem

Compaction removes old events from current model input but retains their original transcript indefinitely. Operators need a configurable periodic retention policy for these obsolete events, independent of archived-session retention.

## Primary Context

### Primary System Outcome

Events displaced behind a session's model-input head by successful compaction are permanently removed by scheduled maintenance once their independently configured retention period expires.

## Supporting Scenarios or Effects

- Administrators configure compacted-event retention without changing archived-session retention.
- Current conversation execution and the retained compaction summary remain usable after cleanup.

## Goals

- Bound storage of obsolete pre-compaction events through periodic maintenance.
- Provide a separate retention setting with an Unlimited default.
- Preserve current context and session identity.

## Non-Goals

- Change compaction summary generation or the current model-input contents.
- Delete entire sessions through the compacted-event retention policy.
- Change archived-session retention behavior.
- Introduce history versioning or backups.

## Requirements

### REQ-1. Independent retention control

Compacted-event retention is independently configurable using the same administrator-managed retention approach as archived sessions.

**Acceptance criteria**

- The initial compacted-event retention value is Unlimited, so installation or upgrade does not automatically delete historical events.
- Administrators can select Unlimited or a finite non-negative whole-day retention value.
- Unlimited disables compacted-event expiration; zero makes eligible events available to the next asynchronous cleanup pass.
- Changing compacted-event retention does not change archived-session retention.
- Administrator controls expose the retention value separately from archived-session retention.

### REQ-2. Scheduled expiration

Expired obsolete events are permanently removed by scheduled maintenance, not synchronously during compaction or a settings mutation.

**Acceptance criteria**

- The cleanup participates in the existing scheduler's periodic execution and retry handling.
- Unexpired events are retained.
- Repeated cleanup is safe and does not remove current context.
- Retention age begins when successful compaction first displaces the event behind the model-input head, not when the event was created.
- Later compaction does not restart the retention age of previously displaced events.

### REQ-3. Preserve the live conversation boundary

Cleanup only removes events displaced by successful compaction and preserves events still in current model input.

**Acceptance criteria**

- The current compaction summary/head event and every event at or after it survive.
- A session without successful compaction is not cleaned by this policy.
- Cleanup does not delete or archive the session.
- Concurrent compaction and cleanup preserve a valid current conversation boundary.

## Fixed Constraints

- Default retention: Unlimited.
- Existing archived-session retention behavior remains unchanged.
- No synchronous permanent deletion in settings or compaction operations.

## Open Assumptions

- None.

## Confirmation

The requester confirmed this scope and selected retention from compaction displacement on 2026-10-13, after changing the default to Unlimited. The requester then explicitly authorized implementation.
