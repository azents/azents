---
title: "Chat Attachment Presentation Historical Decision Reconstruction"
created: 2026-07-11
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: chat-260711
historical_reconstruction: true
migration_source: "docs/azents/design/chat-attachment-presentation.md"
---

# Chat Attachment Presentation Historical Decision Reconstruction

- Snapshot: `chat-260711`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/chat-attachment-presentation.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### chat-260711/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Preview renderer contract

The frontend normalizes attachment preview fields into a discriminated preview descriptor.

| Preview kind | Current/future source | Renderer |
| --- | --- | --- |
| Image | Original image or image preview URL | Large contained image with zoom and pan |
| Text | `textPreview` | Scrollable monospaced text surface |
| Document page | Future first-page image preview, using generalized preview metadata | Contained page image with zoom and pan |

The current `FileAttachment` fields already provide `textPreview`, `previewThumbnailUri`, preview media type, dimensions, and generation time. Initial implementation maps those fields into the preview descriptor without changing the backend contract. Future PDF first-page support should publish preview metadata through the same generalized preview boundary rather than adding PDF-specific UI fields.

### Explicit source section: CI execution policy

- Deterministic Storybook build, interaction checks, and attachment E2E tests are required CI checks.
- Tests using only local fixtures must fail CI on any assertion failure; they are never optional skips.
- Future live-provider or live-PDF-generation coverage may run separately and may skip only when its explicitly declared credential or service prerequisite is unavailable.
- A missing standard authenticated workspace, Exchange download route, or required fixture is a failure rather than a skip.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
