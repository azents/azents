---
title: "Discord Provider Status Surfaces Design"
created: 2026-09-08
updated: 2026-09-08
implemented: 2026-09-08
tags: [discord, external-channel, channel-work, scheduled-task, backend, testenv]
document_role: primary
document_type: design
snapshot_id: discord-260908
---

# discord-260908/DESIGN: Discord Provider Status Surfaces

- Snapshot: `discord-260908`
- Document reference: `discord-260908/DESIGN`
- Requirements:
  [`discord-260908/REQ`](../requirements/discord-260908-provider-status-surfaces.md)
- Decisions:
  [`discord-260908/ADR`](../adr/discord-260908-provider-status-surfaces.md)

## Current Behavior and Gaps

Conversational ingress derives canonical Tracker visibility directly from the provider-native invocation flag. This makes both Slack and Discord explicit invocations visible. Discord Gateway typing independently projects every connected ready active conversational Work, so a Discord mention produces both typing and an initial Channel Work Embed. Batched follow-up admission also treats a later Discord mention as authority to promote hidden Work.

Scheduled Task cycles use their own provider projection state. The initial checking snapshot passes only the Schedule title into the shared Discord progress renderer, which hardcodes the Embed title `Channel Work` and prefixes the body with `Agent is running a scheduled task…`. The cycle snapshot already contains schedule type, scheduled time, cron expression, timezone, and scheduled occurrence.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `discord-260908/REQ-1` | M1, M2 |
| `discord-260908/REQ-2` | M3, M4 |

## Architecture and Ownership

Canonical Channel Work remains created for Discord conversational execution. Only its automatic provider projection eligibility changes. The existing Discord typing registry continues to derive active targets from current connected ready Work without depending on Tracker visibility.

Scheduled Task cycle state remains the authority for Schedule identity and timing. Scheduled Task channel orchestration derives one human schedule summary through the existing schedule renderer and supplies it to the Discord-specific initial projection. The generic conversational progress renderer and Slack Scheduled Task renderer remain unchanged.

## Discord Conversational Visibility

Every provider-neutral visibility boundary becomes explicitly provider-aware:

- Slack returns visible for an explicit invocation and hidden otherwise.
- Discord returns hidden for both explicit mentions and ordinary all-messages admission.
- Batched Discord follow-up admission does not add a mention-triggered mailbox item to the visible-Tracker promotion set.

This affects initial Binding provisioning, existing-Binding direct admission, and queued follow-up finalization. It does not suppress an explicit `channel_action` progress projection, because that path changes desired progress and provider projection independently from ingress-derived automatic visibility.

## Scheduled Task Initial Projection

Scheduled Task orchestration renders the cycle schedule with `render_scheduled_task_schedule` and passes its human `summary` to the Discord Scheduled Task progress renderer.

For the checking state, the Discord renderer emits one Embed:

- title: `Scheduled Task`;
- description line 1: the bounded Schedule title;
- description line 2: the bounded human schedule summary.

The normal conversational checking Embed remains `Channel Work` with `Agent is checking your message`. A Scheduled Task working snapshot continues to use its explicit progress title and compact task description. Existing tracker identity, `View session`, update/create operation selection, and settlement remain unchanged.

## State, Migration, Compatibility, and Rollback

No schema, database row, public API, Toolkit contract, provider credential, or scheduling field changes. Existing hidden Work can still become visible only through explicit progress publication. No legacy fallback preserves mention-created Discord cards.

Rollback restores invocation-derived Discord Tracker visibility and generic Scheduled Task checking copy. No data conversion is required.

## Failure, Retry, and Recovery

Discord typing remains best-effort provider activity under the current lease and connection fences; its failure does not create a Tracker fallback. Canonical Work still exists for execution and recovery.

Incomplete Scheduled Task timing state continues to fail through the existing schedule renderer validation before provider effect preparation. Provider delivery, tracker claim/settlement, retry, and terminal behavior remain unchanged.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected evidence |
| --- | --- |
| Mention the Agent in a connected Discord conversation | typing becomes active while no automatic Activity Tracker delivery is created |
| Complete the mentioned execution | typing clears and the final reply remains deliverable |
| Explicitly publish structured Channel Work | a Tracker can still be created or updated |
| Start a bound one-time Scheduled Task | initial Embed title is `Scheduled Task`; body contains Schedule title then human execution time |
| Start a bound recurring Scheduled Task | initial Embed body contains Schedule title then human recurrence summary |

Required Discord scenarios record sanitized typing and provider delivery categories without retaining authored content or signed controls. Focused backend tests cover provider-specific visibility derivation and exact Scheduled Task payloads.

### Validation

- Ruff and configured type checking for changed backend and E2E modules.
- Focused ingress provisioning, mailbox ingestion, ingress queue, Discord presentation, Scheduled Task channel, and provider fake tests.
- Required Discord mention/typing E2E and Scheduled Task provider presentation E2E where existing fixtures permit deterministic execution.
- Full backend tests, pre-commit, independent review, and GitHub CI.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Discord mention-derived visible Tracker eligibility | `discord-260908/REQ-1` | hidden canonical Work plus Discord typing | provisioning, direct admission, and queued follow-up visibility derivation | unit and E2E evidence require no automatic Activity Tracker for mentions |
| Later Discord mention promotion of hidden Work | `discord-260908/REQ-1` | explicit `channel_action` progress publication | queued mailbox visibility set | batched follow-up test retains hidden visibility |
| Generic initial Scheduled Task `Channel Work` title and running sentence | `discord-260908/REQ-2` | `Scheduled Task`, Schedule title, and human schedule summary | Discord Scheduled Task checking renderer | exact payload tests reject generic copy |
| Slack invocation Tracker visibility | None; retained | current Slack provider behavior | unchanged provider-aware branches | Slack invocation tests remain visible |
| Scheduled Task working progress layout | None; retained | current progress title and task list | non-checking renderer path | existing progress tests remain green |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Discord ingress always requests hidden automatic Tracker visibility while Slack retains invocation-derived visibility | `discord-260908/REQ-1`; `discord-260908/ADR-D1` | `decided` |
| M2 | A later Discord mention does not enter the automatic visible-Tracker promotion set; explicit progress publication remains separate | `discord-260908/REQ-1`; `discord-260908/ADR-D2` | `decided` |
| M3 | Scheduled Task orchestration derives human timing from the canonical schedule renderer | `discord-260908/REQ-2`; `discord-260908/ADR-D3` | `decided` |
| M4 | The Discord checking projection renders `Scheduled Task`, Schedule title, then schedule summary while later progress remains unchanged | `discord-260908/REQ-2`; `discord-260908/ADR-D3` | `decided` |

## Authority Audit

- Every mechanism traces to confirmed requester corrections.
- M1 and M2 change only automatic Discord projection eligibility; canonical Work and explicit publication remain authoritative.
- M3 reuses existing schedule authority and introduces no parallel formatting source.
- M4 is limited to the initial Scheduled Task checking projection.
- No unapproved Slack, persistence, scheduling, API, migration, or terminal-delivery change is introduced.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

| Area | Result | Repository evidence |
| --- | --- | --- |
| Discord typing without Tracker | Feasible | typing target projection reads connected ready active Work without requiring visible Tracker state |
| Initial and direct visibility | Feasible | provisioning and direct mailbox admission already call provider-aware visibility helpers |
| Batched follow-up visibility | Feasible | queued finalization builds an explicit visible-Tracker mailbox key set before Work reconciliation |
| Explicit progress preservation | Feasible | `channel_action` provider projection is separate from ingress-derived initial visibility |
| Scheduled Task schedule summary | Feasible | immutable cycle state contains complete timing fields and `render_scheduled_task_schedule` returns a human summary |
| Scheduled Task card layout | Feasible | Discord scheduled checking rendering already owns one Embed before Session navigation components are appended |

No confirmed Requirement is blocked and no material choice remains.

Feasibility result: **feasible for Design revision 1**.

## Assumptions and Non-Blocking Risks

- Discord typing may be briefly delayed by Gateway polling but remains the chosen automatic signal.
- If typing delivery fails, the system does not create a fallback Channel Work card.
- Schedule summaries follow the existing English human-rendering contract.
- Explicit Agent progress may intentionally create a visible card after a mention.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-08`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: Remove automatic Discord Channel Work cards and mention-based promotion in favor of typing, preserve explicit progress and Slack behavior, and replace generic initial Scheduled Task Discord copy with the Schedule title and human schedule timing.
