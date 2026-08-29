---
title: "Slack Channel Work Presence and Tracker Parity Decisions"
created: 2026-08-29
tags: [slack, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: slack-260829
---

# slack-260829/ADR: Slack Channel Work Presence and Tracker Parity

- Snapshot: `slack-260829`
- Document reference: `slack-260829/ADR`
- Requirements:
  [`slack-260829/REQ`](../requirements/slack-260829-work-presence-parity.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The completed Discord experience separates execution presence from Tracker
visibility. Every active conversational Work requests typing, while an explicit
invocation starts with a visible Tracker and ordinary all-messages Work remains hidden
until unfinished Todo publication or a later explicit invocation promotes it.

Slack currently creates a visible Tracker for every accepted Work and has no Work
presence lifecycle. Slack also emits a settings-only control after eligible mentions
instead of placing settings access on the visible conversational Tracker.

Slack exposes different provider capabilities for the two already-authoritative
conversation mappings:

- a parent-channel Azents Session can display channel-based AI loading against the
  current trigger message without becoming a thread Session; and
- an exact Slack thread can participate in Slack's Agent Session lifecycle.

Enabling the Slack Agent feature also exposes provider-owned Agent UI, adds required
installation capability, requires reinstallation, and prevents Slack guests from
using the Agent-enabled App. The requester explicitly accepted Agent mode as a
required prerequisite.

## Fixed and Derived Outcomes

- The implemented Discord Work presence and Tracker lifecycle is the product-semantic
  source of truth.
- Slack Resource, Binding, Session, response-mode, history, and final-delivery mapping
  remain unchanged.
- Presence is provider presentation only and never becomes execution, routing,
  connection-health, or delivery authority.
- Channel and thread targets may use different Slack APIs while exposing one visible
  lifecycle.
- Existing provider-neutral routing semantics remain authoritative unless repository
  evidence identifies a Slack-only drift.

## Material Decision Map

- `slack-260829/ADR-D1` — accepted: project channel and thread presence through
  target-appropriate Slack APIs without changing canonical conversation mapping.
- `slack-260829/ADR-D2` — accepted: require Slack Agent mode for thread presence and
  provide no silent compatibility fallback.
- `slack-260829/ADR-D3` — accepted: reconcile Slack presence from canonical Work under
  dedicated per-connection ownership.
- `slack-260829/ADR-D4` — accepted: make Slack Tracker lifecycle and actions match
  Discord and remove settings-only invocation messages.
- No material decision remains pending.

## slack-260829/ADR-D1: Use target-appropriate Slack presence APIs

### Decision

- Parent-channel Work uses Slack's channel-based AI loading status anchored to the
  message that created the current Work cycle.
- Thread Work uses Slack Agent Session status on the exact retained thread.
- The parent-channel anchor is presentation metadata only. It does not create or
  select an Azents thread Resource, Binding, Session, or reply target.

### Rejected alternatives

- Treat every channel Work as a Slack Agent Session: rejected because it would change
  the current parent-channel conversation experience.
- Use one compatibility status method for every target: rejected because the
  requester selected native Agent Session lifecycle for exact thread Bindings.
- Use legacy RTM typing: rejected because modern Slack Apps may not use RTM methods.

### Consequences

- The two provider calls differ, but active/idle Work presence is semantically
  identical.
- Thread status can be unavailable on Workspaces where Slack Agent functionality is
  not enabled.

## slack-260829/ADR-D2: Require Slack Agent mode without fallback

### Decision

Slack setup declares the App as an Agent and requires the corresponding installed
scope. Runtime `feature_disabled` or other confirmed Agent Session rejection is a
presence failure only. Azents does not fall back to the channel-based compatibility
method for thread Work.

The provider-owned Agent Messages surface is configured read-only because Azents App
Home and direct-message ingress are outside this snapshot.

### Rejected alternatives

- Store an App configuration token and export the manifest during validation:
  rejected because it introduces a short-lived management credential and still does
  not prove Workspace Agent feature availability.
- Silently fall back after `feature_disabled`: rejected because it hides an invalid
  required installation and creates two thread-presence contracts.
- Disable Agent mode and use compatibility status for thread Work: rejected by the
  requester's explicit selection.

### Consequences

- Existing installations require manifest update and reinstallation.
- Slack's provider-owned Agent entry point becomes visible.
- Slack guest users cannot use the Agent-enabled App.
- Runtime inability to present thread presence never rolls back Work, Tracker, or
  replies.

## slack-260829/ADR-D3: Reconcile presence under a dedicated Slack connection lease

### Decision

One External Channel Gateway owner claims a dedicated presence lease for each active
Slack connection, decrypts that connection's Bot token, and reconciles current
provider status from canonical Channel Work.

Work stores only the Slack status anchor and initiating participant required to
reconstruct provider presence. The manager retains process-local observed state,
renews channel loading before provider expiry, restores active presence after
handover, and clears finished Work.

### Rejected alternatives

- Only send status during ingress and `channel_action`: rejected because long-running
  Work would lose channel loading and process failure could leave thread status stale.
- Run an unfenced scanner on every Gateway replica: rejected because duplicate
  provider calls would amplify rate-limit and failure behavior.
- Persist provider status as execution authority: rejected because canonical Work
  already owns the lifecycle.

### Consequences

- The connection schema gains bounded presence-lease fields.
- Channel Work Toolkit State advances to a new schema version with the provider
  coordinates needed for recovery.
- Presence failures are retried only by future reconciliation from current Work.

## slack-260829/ADR-D4: Match Discord Tracker and settings lifecycle

### Decision

Slack uses the same visibility, promotion, identity, action, and cleanup semantics as
Discord:

- explicit invocation starts visible;
- ordinary all-messages Work starts hidden;
- unfinished Todo publication or a later explicit invocation promotes monotonically;
- one Tracker identity renders the complete latest snapshot;
- visible conversational Trackers expose `View session` and
  `Conversation settings`;
- settings-only invocation controls are removed; and
- delivered final reply gates Tracker deletion.

Slack continues to lower checking Work to `task_card` and planned Work to `plan`.

### Rejected alternatives

- Keep Slack Tracker-always-visible behavior: rejected because Tracker chrome would
  continue serving as a typing substitute.
- Keep settings-only messages: rejected because the visible Tracker becomes the
  recurring settings entry point, matching Discord.
- Retain completed Plans after final reply: rejected because Activity Trackers are
  temporary Work projections, not durable results.

### Consequences

- Slack and Discord differ only in native presentation components and presence API.
- Scheduled Task and non-conversational control presentation remain unchanged.

## Message Routing Audit Boundary

The implementation audits provider-neutral invocation, response-mode, exact Binding
precedence, self-message exclusion, history scope, and final target selection. Any
Slack-only drift in those contracts is corrected in this snapshot.

The current Spec's provider-specific Slack parent-channel fan-in and thread Resource
representation are retained and are not classified as drift.
