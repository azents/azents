---
title: "Discord Tracker Title-List Relocation Decision"
created: 2026-10-07
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: tracker-261007
---

# tracker-261007/ADR: Discord Tracker Title-List Relocation

- Requirements: [tracker-261007/REQ](../requirements/tracker-261007-title-list-relocation.md)
- Mode: Collaborative, bounded implementation request
- Decision owner: Requester

## Context

The previous [tracker-260907/ADR-D1](tracker-260907-task-only-edit.md) required both
any task-snapshot change and a conversational message to relocate the Tracker.
The requester replaces that criterion with title-list changes only, independently
of reply presence. The existing canonical transition and provider-effect lifecycle
already support removal followed by notification-suppressed standalone creation.

## D1. Use the ordered task-title list as the relocation criterion

**Authority:** `tracker-261007/REQ-1`, `REQ-2` and the direct implementation request.

Discord compares the titles of explicitly supplied tasks against the pre-transition
canonical title list. A difference selects existing removal-before-create relocation;
otherwise the retained host is updated. Message presence does not affect this choice.
The comparison uses existing order and normalized task titles. Work-level titles,
IDs, statuses, details, output, and sources are excluded.

This supersedes the relocation criterion in `tracker-260907/ADR-D1`; that historical
snapshot remains unchanged. Keeping its message gate would violate REQ-1, while
comparing whole task models would violate REQ-2. No new material technical choice is
needed beyond the requester's fixed policy change.

## Consequences and Risks

- Title changes can move the Tracker without an accompanying reply.
- Completion, reopening, and task comments keep the Tracker's position.
- Existing failed/ambiguous removal can prevent replacement; later explicit progress
  updates remain the convergence mechanism under REQ-3.
- State, revision fences, provider permissions, notification flags, Slack behavior,
  and finish/ignore boundaries remain unchanged. No migration or fallback is added.
