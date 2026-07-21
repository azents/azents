---
title: "Agent Model Selection Options Historical Decision Reconstruction"
created: 2026-07-09
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: selection-260709
historical_reconstruction: true
migration_source: "docs/azents/design/model-selection-options.md"
---

# Agent Model Selection Options Historical Decision Reconstruction

- Snapshot: `selection-260709`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/model-selection-options.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### selection-260709/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Concept: selectable model option

Add an ordered JSON-backed selectable model list to Agents and Workspace model settings.

Each selectable model option has:

- `label`: user-visible unique label within the list.
- `model_selection`: normalized `AgentModelSelection` snapshot.

The list is an array, not an object, because order matters for fallback and UI. Label uniqueness is enforced in the application layer.

Example:

```json
[
  {
    "label": "default",
    "model_selection": {
      "llm_provider_integration_id": "int_...",
      "provider": "openai",
      "model_identifier": "gpt-5",
      "model_display_name": "GPT-5",
      "model_developer": "openai",
      "model_family": "gpt-5",
      "normalized_capabilities": {},
      "model_snapshot": {},
      "source_metadata": null,
      "last_refreshed_at": "2026-07-09T00:00:00Z"
    }
  }
]
```

### Explicit source section: Resolved decisions

- Store selectable model options as JSONB arrays, not separate tables or JSON objects.
- Enforce unique labels in the application layer after trimming whitespace.
- Treat labels as case-sensitive display identities after trimming.
- Cap both Agent and Workspace selectable model lists at 10 entries.
- Retain existing direct snapshot columns as denormalized effective runtime/default snapshots owned by Agent and Workspace settings services.
- Use the first ordered option as deterministic fallback when a selected label is missing.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
