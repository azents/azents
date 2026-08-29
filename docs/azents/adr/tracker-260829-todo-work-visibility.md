---
title: "Discord Todo Work Activity Tracker Visibility Decisions"
created: 2026-08-29
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: tracker-260829
---

# tracker-260829/ADR: Discord Todo Work Activity Tracker Visibility

- Snapshot: `tracker-260829`
- Document reference: `tracker-260829/ADR`
- Requirements:
  [`tracker-260829/REQ`](../requirements/tracker-260829-todo-work-visibility.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The implemented `discord-260828` snapshot made Discord Tracker visibility
mention-gated for the complete Work cycle. The later `discord-260829` snapshot
preserved hidden Work while adding settings access to visible Trackers.

The requester clarified the intended product contract: an ordinary all-messages input
may start without a Tracker, but an Agent-authored unfinished Todo list must make the
Tracker visible. Current Channel Work already owns the canonical ordered task list and
provider projection lifecycle.

## Fixed and Derived Outcomes

- Initial non-mention checking Work may remain hidden.
- A valid task-bearing `continue` transition contains at least one unfinished task.
- That canonical transition promotes hidden Work to visible before provider effects are
  planned.
- Visibility remains monotonic for the Work cycle.
- Existing create, update, missing-message replacement, cleanup, settings-action,
  typing, Slack, and Scheduled Task behavior remains authoritative.

## Material Decision Map

No unresolved material decision remains. `tracker-260829/REQ-1` directly requires
unfinished Todo publication to make the Tracker visible. Channel Work is already the
sole task and projection authority, so deriving promotion inside its canonical
transition introduces no competing source of truth.

## Superseded Scope

This snapshot supersedes only the visibility portions of:

- `discord-260828/REQ-3` that prevented task changes from publishing a hidden Tracker;
  and
- `discord-260829/REQ-4` that required Tracker-hidden Todo Work to remain without a
  Tracker.

Typing presence, late-mention promotion, settings authorization, and every other
accepted decision in those snapshots remain unchanged.

## Consequences

- Discord participants see the plan whenever the Agent declares unfinished work.
- Brief ordinary inputs that never publish a Todo can remain without Tracker chrome.
- Todo publication and explicit mention are independent monotonic promotion triggers.
- No migration, provider API change, configuration, fallback, or new recovery path is
  required.
