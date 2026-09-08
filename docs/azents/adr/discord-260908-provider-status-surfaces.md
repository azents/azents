---
title: "Discord Provider Status Surfaces Decisions"
created: 2026-09-08
tags: [discord, external-channel, channel-work, scheduled-task, architecture]
document_role: primary
document_type: adr
snapshot_id: discord-260908
---

# discord-260908/ADR: Discord Provider Status Surfaces

- Snapshot: `discord-260908`
- Document reference: `discord-260908/ADR`
- Requirements:
  [`discord-260908/REQ`](../requirements/discord-260908-provider-status-surfaces.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Discord already projects active ready conversational Work through its provider-native typing indicator. Explicit mentions additionally make canonical Work Tracker-visible, producing a generic Channel Work card alongside typing. The visibility rule is currently shared with Slack even though Slack uses its Tracker/presence surface differently.

Scheduled Task execution owns a separate Tracker lifecycle, but its initial Discord checking projection reuses the generic Channel Work Embed title and generic running sentence. The immutable Scheduled Task cycle snapshot already contains the Schedule title and complete timing fields, and the existing schedule renderer already provides a human-readable summary.

## Decisions

### discord-260908/ADR-D1. Keep Discord conversational Work hidden until explicit progress publication

Discord message invocation, including an explicit Agent mention, creates or reuses canonical Work with hidden Tracker visibility. Discord typing remains the sole automatic provider-visible activity signal. Slack keeps invocation-derived visible Tracker behavior.

Removing canonical Work is rejected because Work remains the execution, recovery, and explicit progress authority. Disabling typing is rejected because the requester selected typing as the unified automatic signal.

### discord-260908/ADR-D2. Do not promote Discord Work solely from a later mention

A later explicit Discord mention does not monotonically promote existing hidden Work to a visible Tracker. Provider-specific visibility is decided before canonical Work reconciliation, while an explicit Agent `channel_action` progress publication remains authorized to create or update the Tracker.

Retaining mention-based promotion is rejected because it would reintroduce the duplicate card after an earlier ordinary-message cycle.

### discord-260908/ADR-D3. Render a task-specific initial Scheduled Task Embed

The initial Discord Scheduled Task projection uses `Scheduled Task` as the Embed title. Its body contains the Scheduled Task title followed by the human-readable schedule summary derived from the immutable cycle snapshot. Later structured Scheduled Task progress retains its current progress-title and task-list presentation.

Reusing generic Channel Work copy is rejected because it obscures the Schedule identity. Reimplementing cron or timestamp formatting in the Discord renderer is rejected because the existing Scheduled Task schedule renderer is canonical.

## Consequences

- Discord mentions show typing without an automatically created Channel Work card.
- Explicit structured progress can still create a Channel Work Tracker.
- Slack conversational Tracker behavior remains unchanged.
- Initial Scheduled Task cards identify the Schedule and timing directly while retaining existing Session navigation and tracker lifecycle.
- No persistence, API, scheduling, migration, or credential change is required.
