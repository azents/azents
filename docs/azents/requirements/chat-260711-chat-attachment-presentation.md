---
title: "Chat Attachment Presentation Historical Requirements Reconstruction"
created: 2026-07-11
implemented: 2026-07-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chat-260711
historical_reconstruction: true
migration_source: "docs/azents/design/chat-attachment-presentation.md"
---

# Chat Attachment Presentation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chat-260711`
- Source: `docs/azents/design/chat-260711-chat-attachment-presentation.md`
- Historical source date basis: `2026-07-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Chat attachments currently use unrelated presentation rules depending on where and how they appear. Pending composer attachments are cards, message images are free-form inline previews, text files are expandable rows, and generic files are plain download rows. Mixed attachment sets therefore look like unrelated elements, consume unpredictable vertical space, and behave differently before and after sending.

The redesign must make attachment presentation coherent without weakening the intent of Agent-produced images, which are usually sent for immediate viewing rather than merely as downloadable files.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Establish one visual language for attachment tiles across the composer and sent messages.
- Keep user-originated attachment history compact, including user-originated images.
- Preserve prominent inline viewing for Agent-originated image output.
- Keep mixed Agent image and non-image output visually grouped.
- Bound vertical growth when many attachments are present.
- Generalize preview handling so image, text, and future document previews share one viewer shell.
- Preserve download access and unavailable/expired states.
- Provide deterministic Storybook and E2E coverage for mobile and desktop layouts.

## Non-goals

- Changing Exchange attachment storage, authorization, retention, or download APIs.
- Implementing PDF preview generation in the first delivery phase.
- Changing how files are supplied to the model as FilePart content.
- Redesigning the Agent Workspace file browser.
- Treating image MIME type alone as sufficient evidence that an image should be shown prominently.

## Requirements

- CI requires only the standard authenticated E2E workspace fixture and object-storage/download test configuration.
- Do not require external provider credentials or live image generation.
- Capture the seeded attachment manifest and viewport configuration in test diagnostics so failures can be reproduced.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
