---
title: "Image Generation Model Selection Implementation Plan"
created: 2026-09-10
updated: 2026-09-10
tags: [agent, workspace, image-generation, model-catalog, implementation]
---

# Image Generation Model Selection Implementation Plan

## Authority

- [Requirements](../requirements/image-260910-generation-model-selection.md)
- [ADR](../adr/image-260910-generation-model-selection.md)
- [Approved Design revision 2](../design/image-260910-generation-model-selection.md)
- Approved mechanisms: `M1` through `M11`
- Design delta: `None`

## Delivery Shape

One cohesive PR delivers the schema, stored catalog, public API, Agent and Workspace
validation, runtime defense, localized settings UI, deterministic tests, generated
clients, Living Spec promotion, and plan cleanup. The feature is one vertical contract:
splitting schema/API from save and runtime enforcement would temporarily expose an
authority that no user flow can safely consume.

## Workstreams

1. Add purpose-aware catalog lifecycle, integration configuration fencing, image entries,
   migration, and repository coverage (`M1`, `M2`, `M5`, `M6`, `M10`).
2. Add the registry, OpenAI discovery, stored read/sync API, and deterministic projection
   coverage (`M3`, `M6`, `M7`).
3. Add canonical built-in config round-trip, Agent and Workspace save validation, and
   runtime pre-dispatch defense (`M4`, `M5`, `M7`, `M8`).
4. Regenerate OpenAPI clients and implement the catalog-driven localized settings
   experience (`M7`, `M9`).
5. Add deterministic E2E, focused regressions, Living Spec updates, immutable snapshot
   implementation dates, and remove temporary plans (`M11`).

## Integration Boundaries

- Existing conversation catalogs explicitly use `purpose=conversation`.
- Image entries never use conversation entry schema.
- Provider discovery remains in Integration/Catalog services.
- Agent and Workspace settings persist only semantic built-in config.
- Runtime validation occurs before provider dispatch.
- Generated-image storage and transcript paths are unchanged.

## Validation

- Migration and repository tests.
- Focused backend catalog, settings, runtime, and provider-lowering tests.
- Generated public OpenAPI and Python/TypeScript clients.
- Azents Web format, lint, typecheck, unit tests, and Storybook interaction coverage.
- Deterministic required E2E for default, explicit, unavailable, recovery, generation
  fencing, and provider boundaries.
- `/spec-review`, final independent review by `implementation-reviewer`, and complete
  Design Authority/removal audit.

## Removal and Cleanup

- Remove the frontend static registry and manual unavailable flag.
- Replace name-only built-in serialization with complete config round-trip.
- Remove the local absolute Storybook filesystem override.
- Delete `.agent-visual-requirements.md` and the temporary research note.
- Delete this plan and the phase plan after validated spec promotion.

## Blockers

None. Optional live OpenAI execution is not a required CI prerequisite.
