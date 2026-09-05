---
title: "Discord Moving Activity Tracker Design"
created: 2026-09-05
updated: 2026-09-05
implemented: 2026-09-05
tags: [discord, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: discord-260905
---

# discord-260905/DESIGN: Discord Moving Activity Tracker

- Snapshot: `discord-260905`
- Document reference: `discord-260905/DESIGN`
- Requirements:
  [`discord-260905/REQ`](../requirements/discord-260905-moving-activity-tracker.md)
- Decisions:
  [`discord-260905/ADR`](../adr/discord-260905-moving-activity-tracker.md)

## Current Behavior and Gaps

Channel Work stores one provider projection part per Tracker page. Discord currently
uses one compact page, creates it as a standalone message, updates that message by
replacing content, Embed, and controls, and deletes the complete message during
cleanup. Replies and progress effects are independent and contain no effect dependency
or prior-result identity reference.

This model cannot host a Tracker on a reply because a progress update would overwrite
the reply body and a progress delete would delete the reply. It also cannot attach to a
reply created earlier in the same Action because the reply message identity is unknown
when the canonical transition is committed.

## Requirement and Decision Traceability

| Requirement | Decisions | Mechanisms |
| --- | --- | --- |
| `discord-260905/REQ-1` | D1, D2, D4, D5 | M1, M2, M3, M7 |
| `discord-260905/REQ-2` | D1, D4 | M1, M2, M4 |
| `discord-260905/REQ-3` | D2, D3, D5 | M2, M3, M5, M7 |
| `discord-260905/REQ-4` | D1, D3 | M1, M4, M6 |

## Architecture and Ownership

Canonical Channel Work continues to own desired progress, its monotonic revision, and
the current provider projection observation. Discord messages remain derived provider
state.

Each projection part gains a host classification:

- `standalone`: the message exists solely for the Tracker and cleanup deletes it;
- `reply`: the message contains durable conversational content and cleanup removes only
  Tracker Embeds and controls.

The Toolkit State schema advances by one version. Existing projection parts are
migrated to `standalone`, matching all behavior before this feature.

## Direct Action Planning

The transition continues to commit before provider I/O. Effect plans gain explicit
ordered dependencies and an optional reference to a prior effect whose delivered
provider message identity supplies the current effect target.

For a Discord message plus progress change:

1. plan every reply part normally;
2. plan removal of the current Tracker, dependent on delivery of every reply part;
3. plan a progress update against the final reply identity, dependent on every reply
   part and confirmed current-Tracker removal;
4. mark the target host as `reply` when the attachment result settles.

When there is no current Tracker, step 2 is omitted. The attachment still depends on
all reply parts. If a reply part is failed, unknown, or not attempted, dependent
Tracker effects are not attempted.

A Discord message without a progress change plans only reply effects. A progress change
without a message uses the existing create/update planner against the current host. A
missing projection creates a standalone host; an existing reply host receives a
partial Tracker-only edit.

Slack planning remains unchanged and always targets `standalone` hosts.

## Discord Provider Mutations

Discord progress create continues to create a standalone Tracker message. Standalone
progress update continues replacing its complete Tracker-owned message.

Reply-host mutations use partial message edits:

- attach or update: omit `content`, replace Tracker Embeds, and replace Tracker controls;
- detach: omit `content`, clear Embeds, and clear Tracker controls.

Omitting content preserves the reply body and attachments. The final reply part is
created without Tracker presentation and is edited only after the relocation
dependencies succeed.

## Effect Settlement and Concurrency

One service instance retains a Binding-keyed process-local lock and serializes the
complete canonical transition plus ordered provider sequence for each Binding.
Parallel Actions for other Bindings remain independent. The Session owner-generation
fence prevents normal concurrent execution by separate Workers; no distributed
provider lock or durable queue is introduced.

Every progress effect is revalidated against the exact Work cycle and expected desired
progress revision immediately before provider I/O. A newer progress transition makes
an older queued progress effect not attempted before it can mutate Discord.

Dependency evaluation occurs in the synchronous ordered Action executor. A dependency
must have a `delivered` outcome. The executor retains provider message identities only
for the lifetime of the current Action and substitutes the referenced final reply
identity into the attachment effect before revalidation and delivery.

Progress settlement records the planned host classification. Failed or ambiguous
attachment retains the known reply identity so a later progress update can attempt a
complete Tracker-only edit. No durable dependency, operation, or retry record is added.

## Failure and Recovery

- Reply failure or ambiguity leaves the previous Tracker unchanged because removal is
  dependency-gated.
- Removal failure or ambiguity prevents attachment and retains the previous projection
  observation.
- Attachment failure after confirmed removal records a failed reply-host projection;
  later progress updates retry a complete edit against the known reply identity.
- Attachment ambiguity records the known reply host as unknown; later progress updates
  overwrite it with the complete latest snapshot.
- Process interruption creates no recovery work. The next progress transition uses the
  persisted projection observation available before interruption.
- Final cleanup deletes standalone hosts and detaches reply hosts only after required
  final reply delivery.

## Migration, Rollout, and Rollback

The data migration validates every Channel Work version-4 payload, adds
`host_kind=standalone` to each projection part, advances both payload and row schema
versions, and increments Toolkit State versions. Downgrade validates version-5 payloads,
removes `host_kind`, and restores version 4.

No configuration or staged runtime mode is added. Rollback after reply-host projections
exist is safe for canonical Work data but the older implementation would interpret the
remaining reply identity as a standalone Tracker and could delete a reply. Therefore
downgrade validation must reject any `reply` host until those projections are cleaned
or reset to a compatible state.

## Observability

Existing ordered provider effect outcomes expose reply, progress removal, and progress
attachment success or failure. Dependency skips use a bounded reason that identifies an
unsatisfied earlier effect without exposing provider identities. No additional durable
attempt telemetry is introduced.

## Test Strategy

### E2E primary verification

Extend the required Discord External Channel journey to verify:

- an initial standalone Tracker exists;
- message plus progress change delivers the reply first, removes the standalone
  Tracker, and attaches one Tracker to the reply;
- a later state-only update edits the same reply-hosted Tracker;
- a message-only update leaves the Tracker on its existing host;
- finish preserves the reply while removing its Tracker;
- provider evidence never contains two Tracker-bearing messages after a completed
  successful relocation.

The deterministic Discord fake supplies message content, Embed, component, edit, and
delete evidence. No live credential is required. Notification preview remains a manual
cross-client observation because the provider API does not expose client notification
rendering.

### Backend verification

- repository plans reply, remove, and attach in dependency order;
- no-current-host relocation plans reply and attach only;
- state-only updates select partial edits for reply hosts and full edits for standalone
  hosts;
- message-only Actions plan no progress mutation;
- failed reply or removal skips dependent effects;
- parallel same-Binding Actions execute without overlapping provider sequences;
- stale revisions are rejected before provider I/O;
- successful, failed, and unknown attachment settlement retains the correct host kind
  and target identity;
- migration upgrade/downgrade validation preserves unrelated Toolkit State and rejects
  reply-host downgrade.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Discord progress is always hosted by a standalone message | `discord-260905/REQ-1`, ADR-D1 | standalone or reply host classification | Channel Work projection state and Discord delivery | repository and migration tests |
| Message plus progress change updates the old Tracker in place | `discord-260905/REQ-1`, ADR-D1 | ordered reply, remove, attach plan | direct Action transition | effect-order tests |
| Discord progress update always replaces message content | `discord-260905/REQ-1`, `REQ-2`, ADR-D4 | reply-host partial edit | Discord SDK delivery adapter | SDK payload tests |
| Discord progress cleanup always deletes the message | `discord-260905/REQ-1`, `REQ-4`, ADR-D1 | detach reply hosts; delete standalone hosts | Discord delivery switch | finish and relocation tests |
| Tracker effects execute without explicit dependencies | `discord-260905/REQ-1`, `REQ-3`, ADR-D2 | process-local delivered-effect dependencies | Channel Action executor | dependency failure tests |

## Design Authority

- Design revision: `2`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Discord projection state distinguishes standalone and reply Tracker hosts | `discord-260905/REQ-1`, `REQ-2`, ADR-D1 | `derived` |
| M2 | Message-plus-progress Actions deliver every reply part before Tracker relocation | `discord-260905/REQ-1`, ADR-D4 | `decided` |
| M3 | Relocation removes the current Tracker before attaching to the final reply part | `discord-260905/REQ-1`, `REQ-3`, ADR-D2 | `decided` |
| M4 | State-only changes update the current host and message-only Actions do not move it | `discord-260905/REQ-2`, ADR-D1 | `required` |
| M5 | Tracker failure remains an immediate best-effort projection outcome repaired by later complete updates | `discord-260905/REQ-3`, ADR-D3 | `decided` |
| M6 | Slack, Scheduled Task, controls, and final-reply gating remain unchanged | `discord-260905/REQ-4`; current External Channel Specs | `existing` |
| M7 | Complete same-Binding Actions are serialized within one service executor while stale progress revisions fail before provider I/O | `discord-260905/REQ-1`, `REQ-3`, ADR-D5; current Session owner-generation authority | `derived` |

## Authority Audit

Every Requirement maps to a material mechanism. Host classification and dependent
process-local effects are necessary consequences of the accepted movement and failure
contracts. No timer policy, durable provider work, duplicate Tracker mode, or second
progress authority is introduced.

Authority result: **pass for Design revision 2**.

## Feasibility Validation

- Channel Work already persists current projection identity and status, and its JSON
  schema has established validated migration patterns.
- The Action executor already runs effects in order and can retain current-call results
  without adding durable provider work.
- Discord replies return exact provider message identity, and the SDK adapter supports
  message edit with an omitted content parameter after a bounded signature change.
- Discord uses one compact Tracker page, so one final reply host represents the complete
  conversational Tracker.
- Existing desired-progress CAS and one-attempt delivery contracts remain reusable.

Feasibility result: **feasible for Design revision 2**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-05`
- Approved Design revision: `2`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6, M7`
- Approved scope: Move Discord conversational Trackers to messages that carry changed
  progress, remove the old Tracker before attaching the new one, preserve at most one
  visible Tracker on the successful path, and recover best-effort on later progress
  updates without changing Slack or Scheduled Task behavior.
