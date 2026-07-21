---
title: "Reorder Model Input by Logical Event Order After Compaction"
created: 2026-05-30
tags: [architecture, backend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: compaction-260530
historical_reconstruction: true
migration_source: "docs/azents/adr/0042-compaction-logical-event-ordering.md"
---

# compaction-260530/ADR: Reorder Model Input by Logical Event Order After Compaction

## Status

Accepted.

## Context

Canonical runtime auto compaction is intended to compress old transcript into a summary while preserving recent tail events verbatim. However, the existing implementation appends the compaction summary to the end of the append-only log and moves `model_input_head_event_id` to the summary event. Model input lookup simply reads events after head in id order, so preserved tail events that were physically before the summary can disappear from model input from the next turn onward.

Solving this in lookup logic with branches such as `if compaction summary then recombine events after covered_until_event_id` would make turn construction and model input construction aware of compaction implementation details. Long-running agents add more paths such as resume, retry, reload, manual compaction, auto compaction, and subagent, so such branches are bad for maintainability and correctness.

Also, if the summary includes preserved tail content and the same tail appears again verbatim, duplicate knowledge enters model input. This wastes tokens and makes it harder to judge the latest state when summary and verbatim tail slightly disagree.

## Decision

Auto compaction reorders the model-input logical order of stored canonical events so that a simple lookup sees this order:

1. `CompactionSummary` event
2. preserved tail turns/events
3. future events

To support this, add an ordering key to canonical events separate from physical append order. Model input and transcript lookup consistently sort by this ordering key. Do not add compaction-specific branches to turn construction logic.

The ordering key increases with a fixed gap on sequential append. This gap leaves room to assign intermediate values when adjusting logical order between summary and preserved tail without renumbering the entire transcript every time. The ordering key is stored as DB `BIGINT`, so increasing by 1000 does not create a practical session event-count risk.

Do not include preserved tail turns/events in auto compaction summary generation. The summary replaces only the compacted range. Tail remains verbatim after the summary, and tail content must not be duplicated into summary knowledge.

Manual compaction and fallback compaction remain whole-context compaction without preserved tail. When the user explicitly requests compaction or summary fallback path is used, the whole context is reduced into one summary.

## Consequences

- Model input lookup can read events after `head` in logical order without knowing whether compaction occurred.
- Preserved tail does not disappear from the next turn after auto compaction.
- Knowledge duplication between summary and verbatim tail is reduced.
- DB schema adds a canonical event logical ordering key.
- Compaction implementation becomes responsible for appending summary and moving preserved tail logical order after the summary.
- UI/history lookup must clearly distinguish which order it uses. Model input uses logical order; if needed, physical order for audit/debugging can be viewed through event id or created_at.

## Implementation Plan

1. Add logical ordering key to canonical events and define repository lookup/append defaults.
2. Auto compaction places summary event at the logical position before compacted range and updates ordering key so preserved tail follows it.
3. Lock behavior with tests so preserved tail is excluded from auto compaction summary input. Manual compaction and fallback keep whole-context compaction without preserved tail.

## Migration provenance

- Historical source filename: `0042-compaction-logical-event-ordering.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
