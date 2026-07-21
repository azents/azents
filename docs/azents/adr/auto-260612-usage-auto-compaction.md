---
title: "Usage-based Auto Compaction and Token Estimation Redesign Historical Decision Reconstruction"
created: 2026-06-12
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: auto-260612
historical_reconstruction: true
migration_source: "docs/azents/design/usage-based-auto-compaction.md"
---

# Usage-based Auto Compaction and Token Estimation Redesign Historical Decision Reconstruction

- Snapshot: `auto-260612`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/usage-based-auto-compaction.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### auto-260612/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Auto compaction decision

Auto compaction filter calculates baseline token count by adding:

1. `usage.prompt_tokens` from latest `turn_marker`
2. model-visible token estimate of events after that turn marker

If no latest turn marker exists, use model-visible token estimate of the entire transcript. If baseline token count is at or above `compute_auto_compaction_threshold_tokens(max_input_tokens)`, run append-only compaction. When automatic compaction creates a checkpoint, store `reason: auto_threshold_exceeded` in `compaction_marker` and `compaction_summary` payloads. Explicit `/compact` stores `reason: manual_command` at the same location.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
