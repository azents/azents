---
title: "ADR-0100: Label-Based Model Targets"
created: 2026-07-09
tags: [architecture, agent, backend, frontend]
---

# ADR-0100: Label-Based Model Targets

## Context

Azents previously stored Agent main and lightweight models as direct `AgentModelSelection` snapshots. That kept runtime simple, but it did not provide a durable abstraction for a curated set of models that can be reused by Agent settings, future per-run chat selection, future subagent model selection, and future dynamic model routing.

Provider model identifiers are not a good UI or policy boundary for those future features. Exposing raw provider models everywhere would make chat and delegation surfaces depend on full provider catalogs and would require repeated catalog resolution at run start.

Azents also needs to preserve snapshot-based runtime behavior. Runtime should use saved, resolved model snapshots and should not query model catalogs, provider listing APIs, or Workspace defaults during run start.

## Decision

Use label-based model targets for Agent and Workspace model settings.

Agents store an ordered selectable model option list. Each option contains:

- a user-visible label, unique within that list;
- a resolved `AgentModelSelection` snapshot.

Agents also store `main_model_label` and `lightweight_model_label`. Those labels select entries from the Agent-owned list. Existing `model_selection` and `lightweight_model_selection` columns remain as denormalized effective runtime snapshots resolved from the selected labels.

Workspace model settings use the same pattern for defaults:

- `default_selectable_model_options`
- `default_main_model_label`
- `default_lightweight_model_label`
- denormalized effective default snapshots in the existing direct default fields

The ordered list is stored as a JSONB array. The first entry is the deterministic fallback when a selected label is missing. Lists are capped at 10 entries. Labels are trimmed, non-empty, case-sensitive, unique within the list, and bounded to 80 characters. Application validation owns these invariants.

Submit paths resolve every option's model input through stored model catalog projection and save the resulting snapshots. Runtime receives only effective snapshots and never resolves labels.

## Rejected options

### Keep only direct model snapshots

This preserves the current runtime contract but does not create a reusable constrained target list for chat, subagents, or routing. Every future surface would need to expose provider/catalog selection again or invent a separate target abstraction later.

### Store options as a JSON object keyed by label

A JSON object naturally enforces label keys but loses deterministic user-controlled order. Order is part of the fallback contract, so an array is a better fit.

### Create a separate normalized model option table

A table would support stronger database constraints and references, but the list is intentionally small, whole-list replacement is the API contract, and ordering is important. A table adds migration and query complexity before the product needs per-option independent lifecycle or audit history.

### Resolve labels at runtime

Runtime label resolution would couple run start to Agent settings, Workspace defaults, or model catalog reads. That would violate the runtime boundary and make runs sensitive to catalog state that changed after the Agent was saved.

## Consequences

- Agent model choices now have stable user-facing labels that can be referenced by future run, subagent, and routing features.
- Runtime remains snapshot-based and isolated from catalog reads.
- Reordering the option list changes fallback behavior while preserving selected labels that still exist.
- Label rename is represented as whole-list replacement; clients should update selected labels during explicit rename flows, and the server falls back to the first option when labels disappear.
- The database cannot enforce label uniqueness inside JSONB arrays, so application validation and tests must remain the enforcement boundary.
- Existing direct snapshot API fields remain as transition compatibility and effective response fields, but new product behavior should use selectable options and labels.
