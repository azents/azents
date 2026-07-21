---
title: "Subagent Model Override Policy Historical Decision Reconstruction"
created: 2026-07-17
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: override-260717
historical_reconstruction: true
migration_source: "docs/azents/design/subagent-model-override-policy.md"
---

# Subagent Model Override Policy Historical Decision Reconstruction

- Snapshot: `override-260717`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/subagent-model-override-policy.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### override-260717/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Model settings contract

Extend both input and stored `SelectableModelSettings` shapes:

```json
{
  "context_window_tokens": null,
  "max_output_tokens": null,
  "builtin_tools": [],
  "subagent_enabled": true,
  "subagent_guidance": null
}
```

Semantics:

- `subagent_enabled` controls only explicit `model_target_label` selection by `spawn_agent`.
- Input omission defaults `subagent_enabled` to `true`.
- `subagent_guidance` is nullable and limited to 500 characters.
- Omitted, null, empty, or whitespace-only guidance normalizes to null.
- Stored settings and API responses always contain both fields explicitly.
- Guidance is Agent-owner-authored parent-model routing guidance. It is not part of the child task or child system prompt.

The existing settings object is deliberately used rather than adding an option-level policy object. This keeps model editing, Workspace defaults, copy behavior, API mapping, and generated clients on one model-settings contract. Session inference state receives a redundant copy of the fields, but that copy is not authoritative for subagent routing.

### Explicit source section: Store a separate option-level policy object

Rejected in favor of the existing model settings contract and UI. The Session snapshot receives a small unused copy, while routing remains authoritative from the current Agent settings.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
