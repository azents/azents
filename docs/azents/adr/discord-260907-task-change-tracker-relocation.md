---
title: "Discord Task-Change Tracker Relocation Decisions"
created: 2026-09-07
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260907
---

# discord-260907/ADR: Discord Task-Change Tracker Relocation Decisions

- Snapshot: `discord-260907`
- Document reference: `discord-260907/ADR`
- Requirements:
  [`discord-260907/REQ`](../requirements/discord-260907-task-change-tracker-relocation.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The implemented `discord-260905` behavior moves a Tracker onto the final reply whenever
one Action combines a reply with a progress change. The repeated reply attachment,
detachment, and host movement is visually noisy. Discord standalone Tracker creation
is now notification-suppressed, so recurring standalone placement does not require a
counter or reply-host mutation to remain quiet.

## Fixed and Derived Outcomes

- The complete ordered task snapshot before the canonical transition is available for
  exact equality comparison.
- Title-only changes and identical task replacements retain the current host.
- Reply effects precede progress effects in one Action, so a recreated standalone
  Tracker naturally follows any delivered reply.
- Existing reply-host state remains valid persisted projection state until task change
  or terminal cleanup removes it.
- Same-Binding serialization, exact desired-revision validation, and immediate
  best-effort provider outcomes remain unchanged.

## Decisions

### discord-260907/ADR-D1. Use task snapshot equality as the relocation trigger

**Affects:** `discord-260907/REQ-1`, `REQ-2`

Discord relocates the Tracker when and only when an explicitly supplied ordered task
snapshot differs from the canonical task snapshot before the Action. Equality covers
the complete typed task values and their order. No message counter, progress counter,
elapsed-time threshold, heartbeat, or provider-channel activity state is added.

This directly reflects meaningful Plan changes while keeping title refreshes and
identical complete task replacements visually stable.

### discord-260907/ADR-D2. Recreate a silent standalone Tracker after removal

**Affects:** `discord-260907/REQ-1`, `REQ-3`

Task-change relocation removes or detaches the current Tracker and then creates the
latest complete Tracker as a notification-suppressed standalone message. Replacement
creation depends on confirmed removal so the successful path does not intentionally
show two Trackers. If no current host exists, standalone creation proceeds directly.

New reply-host attachment is removed. Existing reply-host projection state is retained
only for in-place unchanged-task updates and safe detach during relocation or cleanup.

## Consequences

- A status, details, output, source, title, identity, or order change inside tasks can
  move the Tracker even when no conversational reply is sent.
- Frequent task updates may still create visible movement; this is intentional
  observation scope before adding a more complex threshold.
- Delete failure leaves the previous Tracker and skips replacement creation.
- Successful delete followed by failed creation can leave no visible Tracker until a
  later progress projection restores it.
- Toolkit State schema version 5 and host classification remain necessary for lazy
  convergence from existing reply-host Trackers; no new data migration is required.
