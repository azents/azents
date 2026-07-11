---
title: "Chat Attachment Presentation Implementation Plan"
created: 2026-07-11
updated: 2026-07-11
tags: [frontend, chat, attachments, testing]
---

# Chat Attachment Presentation Implementation Plan

## Summary

Implement the approved [Chat Attachment Presentation](chat-attachment-presentation.md) design without changing Exchange storage, authorization, retention, upload, or download APIs.

## PR Stack

1. **Design** — record the approved presentation matrix, interaction rules, preview capability model, and verification strategy.
2. **Implementation plan** — define delivery boundaries, dependencies, validation, fixtures, and spec impact.
3. **Presentation implementation** — introduce compact attachment strips, dynamic overflow fades, Agent galleries and mixed groups, the shared preview viewer, localized controls, and deterministic Storybook states.
4. **Validation and spec promotion** — run frontend quality checks and native-scale mobile/desktop visual verification, compare behavior against the design and current spec, fix drift, and promote the verified UI contract to the living spec.
5. **Cleanup** — remove this temporary implementation plan after the implementation and living spec are current.

Each branch depends on the preceding branch. The stack merges front-to-back.

## Data, API, and Runtime Boundaries

- No backend, database, OpenAPI, runtime, or storage changes are required.
- Existing `FileAttachment` availability, thumbnail, text preview, dimensions, and download identifiers remain the input contract.
- Original-file availability and preview capability remain independent.
- The frontend derives presentation from message origin and the complete attachment composition.

## Validation by Phase

### Design and planning

- Validate documentation frontmatter and the generated documentation index.
- Confirm non-goals against the File Exchange Storage living spec.

### Presentation implementation

- Run azents-web formatting, lint, type checking, and Storybook build.
- Cover composer strips, user strips, Agent image counts, mixed groups, unavailable files, image preview, and text preview with deterministic stories.
- Verify keyboard activation, localized control labels, focus restoration, drag/click separation, download isolation, and responsive viewer behavior.

### Validation and spec promotion

- Render Storybook at native mobile and desktop viewport sizes with application-equivalent providers, font, theme, and device scale.
- Inspect start, middle, and end overflow masks; compact tile geometry; one-to-five-plus image layouts; mixed groups; mobile full-screen preview; and desktop modal preview.
- Record commands, viewport details, observed gaps, and fixes in the PR description.
- Run spec review and update the File Exchange Storage UI contract only after implementation behavior is verified.

## E2E Primary Validation Matrix

| Surface | Required cases |
| --- | --- |
| Composer | one and multiple files, upload/error state, remove action, overflow start/middle/end |
| User and input buffer | image, text, mixed attachments, unavailable attachment, drag without activation |
| Agent output | one, two, three/four, and five-plus images; non-image strip; mixed group |
| Viewer | image fit/zoom/pan/download/close, text scroll/download/close, focus restoration |
| Responsive | native mobile full-screen overlay and desktop bounded modal |
| Accessibility | keyboard open/close/download/zoom and localized accessible labels |

## Fixtures and Prerequisites

- Reuse static chat attachment fixtures and Storybook providers for deterministic component coverage.
- Use portrait, landscape, mixed media, long UTF-8 text, unavailable, and preview-missing attachment snapshots.
- No live model provider, external credential, or backend schema change is required.
- Full authenticated upload/download E2E depends on the standard testenv workspace and object-storage fixture. If that environment is unavailable, Storybook interaction and native-scale browser verification remain required, and the missing integration prerequisite is reported rather than silently skipped.

## Blockers and External Actions

No implementation blocker is known. Authenticated end-to-end download verification requires the standard local/CI test environment; absence blocks only that integration row, not deterministic presentation verification.

## Spec Impact Candidates

- Role/composition presentation matrix.
- Compact strip geometry and dynamic overflow affordance.
- Agent gallery and mixed-group behavior.
- Capability-based shared preview viewer and responsive shell.
- Unavailable original and preview fallback behavior.

## Rollout and Cleanup

The frontend replacement is immediate and has no compatibility mode. After validation, update `docs/azents/spec/flow/file-exchange-storage.md`, mark the design implemented, and delete this temporary plan in the final cleanup PR.
