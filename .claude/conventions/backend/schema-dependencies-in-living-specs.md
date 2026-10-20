---
title: "When changing persisted table structure or resource dependencies, update the owning Living Spec in the same PR with keys, relationships, delete behavior, and cleanup ownership."
---

# Keep Schema Dependencies in Living Specs

- Update the owning `docs/azents/spec/` document with table purpose, identifying keys, relevant constraints, relationship direction, FK `ON DELETE` actions, and lifecycle-significant non-FK references.
- Identify cleanup responsibility, ordering/completion gates, and shared or retained historical resources. Use a Mermaid relationship diagram where it clarifies dependencies.
- Verify against current models and migrations; use the migrated PostgreSQL catalog for constraint-behavior changes. Set `last_verified_at` only for evidence actually checked.
- Keep current structure in Living Specs, not historical Requirements/ADR/Design. Unchanged unrelated domains do not need a bulk schema rewrite.

## Bad

Remove a Runtime FK without documenting whether its historical references are deleted or preserved.

## Good

Document the retained historical Runtime ID, removed ownership constraint, cleanup owner, and deletion-completion gate alongside the schema change.
