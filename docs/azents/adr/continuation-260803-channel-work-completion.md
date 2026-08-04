---
title: "External Channel Continuation Work Completion"
created: 2026-08-03
tags: [external-channel, agent, architecture]
document_role: primary
document_type: adr
snapshot_id: continuation-260803
---

# External Channel Continuation Work Completion

- Snapshot: `continuation-260803`
- Requirements:
  [`continuation-260803/REQ`](../requirements/continuation-260803-channel-work-completion.md)

## Context

The earlier `channel-260803` snapshot coupled silent Work completion to a broader
External Channel selective-response interpretation and proposed a generic typed turn
provenance model. The requester clarified that `ignore` has one purpose: finish active
Channel Work during `external_channel_continuation` so no later continuation is
scheduled.

Mailbox items already distinguish `external_channel_continuation` and carry the active
binding IDs. The execution loop must preserve that scope through Tool-result follow-up
without granting it to initial invocation or other inputs.

## Decision

### `continuation-260803/ADR-D1` — Carry only continuation binding scope

**Affects:** `continuation-260803/REQ-1`, `continuation-260803/REQ-2`

The run boundary carries an ephemeral set of binding IDs originating only from
`external_channel_continuation`. No generic ordinary/external/mixed provenance type is
introduced.

`None` means no new actionable input and preserves the active scope through a
Tool-result follow-up. An empty set means new actionable input without exclusive
continuation authority and clears the active scope. A non-empty set authorizes
`ignore` only for those continuation bindings. Combining continuation input with any
other actionable input produces an empty set.

The Toolkit conditionally exposes `ignore` from that set, and the service revalidates
the selected binding. Eligibility is not reconstructed from transcript history or
persisted.

This replaces the unimplemented generic turn-provenance and selective-response
mechanisms described by `channel-260803`; its binding-specific Toolkit State decision
remains unchanged.

## Consequences

- Initial External Channel invocation cannot invoke `ignore`.
- The execution engine carries one narrow capability scope rather than classifying all
  model turns.
- Tool follow-up remains safe for multi-step continuation handling.
- New or mixed actionable input clears continuation-only completion authority.

## Rejected Alternatives

- **Generic turn provenance:** rejected because `ignore` does not depend on a general
  ordinary/external input classification.
- **Initial invocation eligibility:** rejected because the operation exists to end
  continuation, not to decide whether an incoming message deserves a response.
- **Transcript reverse-search:** rejected because the typed continuation mailbox item
  already owns the relevant binding scope.
