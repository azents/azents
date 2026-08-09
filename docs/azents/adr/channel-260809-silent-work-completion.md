---
title: "External Channel Silent Work Completion"
created: 2026-08-09
tags: [external-channel, agent, toolkit, architecture]
document_role: primary
document_type: adr
snapshot_id: channel-260809
---

# External Channel Silent Work Completion ADR

- Snapshot: `channel-260809`
- Document reference: `channel-260809/ADR`
- Requirements: [channel-260809/REQ](../requirements/channel-260809-silent-work-completion.md)

## Context

The implemented `channel-260803` and `continuation-260803` snapshots restricted
`channel_action(mode="ignore")` through ephemeral continuation binding scope and
rejected completion while Work contained pending or in-progress tasks. Review of the
request history found no requester decision authorizing either restriction. The
requester has now explicitly required their removal.

This snapshot supersedes those product-contract decisions for current behavior while
preserving the earlier documents as immutable historical records.

## Decisions

### `channel-260809/ADR-D1` — Expose one unconditional Channel Action schema

**Affects:** `channel-260809/REQ-1`, `channel-260809/REQ-4`

Every enabled External Channel Toolkit publishes one provider-compatible top-level
`channel_action` object whose mode is `finish | continue | ignore`. Model-input source
and continuation provenance do not alter the schema and do not authorize the action.
The existing binding and Session resource validation remains the authority boundary.

Rejected alternatives:

- Conditional schemas by initial, continuation, ordinary, or mixed input preserve the
  unsupported restriction and make tool availability depend on transient runtime
  provenance.
- Keeping provenance only as a service-side check leaves a hidden restriction even if
  the schema appears unconditional.

### `channel-260809/ADR-D2` — Treat ignore as an explicit terminal Work decision

**Affects:** `channel-260809/REQ-2`, `channel-260809/REQ-3`, `channel-260809/REQ-4`

For an existing active Work, `ignore` is a terminal Agent decision. It finishes the
Work, clears desired progress, advances the canonical revisions, and produces no
provider effect plan. Current task statuses do not veto that decision. It still
requires an active Work and accepts no message, title, task update, or files.

Rejected alternatives:

- Requiring every task to be completed or failed makes stored planning state override
  the Agent's explicit decision and can schedule an unwanted continuation.
- Deleting task records on completion would discard canonical Work context without a
  user requirement.

## Consequences

- Continuation-scope fields and merge/clear logic become obsolete across mailbox,
  worker, engine, and Toolkit contracts.
- Initial, continuation, ordinary, and mixed turns receive the same tool schema.
- Existing provider response-mode admission remains separate and unchanged.
- Historical `channel-260803` and `continuation-260803` documents describe superseded
  implementation-time decisions and are not current behavior authority.
