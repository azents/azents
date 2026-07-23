---
title: "Slack Activity Tracker Lifecycle"
created: 2026-07-23
tags: [slack, external-channel, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: tracker-260723
---

# Slack Activity Tracker Lifecycle

- Snapshot: `tracker-260723`
- Document reference: `tracker-260723/ADR`
- Requirements: [`tracker-260723/REQ`](../requirements/tracker-260723-slack-activity-lifecycle.md)

## Context

The implemented `slackops-260723` snapshot added Activity Tracker projection but did
not record the requester-defined responding-message lifecycle. The Tracker must exist
before model-controlled progress, survive normal completion, and recover from
confirmed external deletion while preserving the existing commit-before-call and
at-most-once delivery boundaries.

## Decisions

### tracker-260723/ADR-D1. One work-cycle-owned provider identity

**Affects:** `tracker-260723/REQ-1`, `REQ-2`, `REQ-5`

Ingress creates Channel Work and its initial Tracker intent in the same transaction
that releases the invocation batch. The work cycle owns the retained provider message
identity. Checking, working, and completed presentations are full Block Kit states
that update that identity and always include the Session URL.

**Rejected:** Model-created initial progress cannot acknowledge work immediately and
omits work cycles without tasks. Reusing one identity across work cycles makes
independent work history ambiguous.

### tracker-260723/ADR-D2. Gate retained completion on final-reply delivery

**Affects:** `tracker-260723/REQ-3`

A finish action durably commits the final reply and completion update intents in
provider execution order. The final reply is attempted first. The completion update
is attempted only when the reply has a durable `delivered` result, including when an
existing action is resumed. Normal completion retains the Tracker; lifecycle cleanup
remains the only ordinary deletion path.

**Rejected:** Updating completion before the reply can tell Slack that an answer is
complete when no answer arrived. Deleting on completion removes the requested result.

### tracker-260723/ADR-D3. Recreate only after confirmed provider absence

**Affects:** `tracker-260723/REQ-4`

A matching Slack deletion event or confirmed `message_not_found` update clears the
retained identity and commits one replacement create intent. If the desired work
revision advances while replacement creation is in flight, the delivered replacement
is followed by one durable update to the latest desired revision. Failed or ambiguous
mutations remain terminal and are not retried.

**Rejected:** Leaving a confirmed deletion unrepaired hides later progress. Blind
retry after timeout can duplicate messages. Posting a new message for every update
abandons the single-identity lifecycle.
