---
title: "Chat Text File Preview Requirements"
created: 2026-07-24
updated: 2026-07-24
implemented: 2026-07-24
tags: [chat, attachment, frontend]
document_role: primary
document_type: requirements
snapshot_id: preview-260724
---

# Chat Text File Preview Requirements

- Snapshot: `preview-260724`
- Document reference: `preview-260724/REQ`

## Problem

Chat attachments that contain readable text can open as unsupported files in the browser instead of being readable inside Azents. Markdown files are affected even when their media type identifies them as Markdown, and other source code, configuration, and plain-text files may also lack a useful preview when their media type is missing or inaccurate.

## Primary Actor

An Azents chat user who opens a file attachment from a conversation.

## Primary Scenario

The user opens a Markdown attachment from a chat message and sees its readable, formatted content inside the Azents attachment viewer while retaining access to download the original file.

## Supporting Scenarios

- The user opens a plain-text, source code, log, or configuration attachment and reads its original text inside the attachment viewer.
- A readable text attachment with an inaccurate or generic media type remains previewable when its filename or content provides sufficient evidence that it is text.
- The user opens a binary attachment and receives the existing download guidance instead of corrupted text.

## Goals

- Make Markdown attachments readable as formatted Markdown in the existing attachment preview experience.
- Make common readable text, source code, log, and configuration attachments previewable as text.
- Preserve original-file download access for every available attachment.
- Keep binary content out of text and Markdown rendering.

## Non-Goals

- Previewing archives, executables, media, or other binary formats as text.
- Adding rich syntax highlighting or editable file views.
- Changing attachment storage, retention, authorization, or model-input behavior.
- Replacing native image preview behavior or adding PDF document rendering.
- Rendering active content embedded in an attachment as trusted application content.

## Requirements

### REQ-1. Formatted Markdown preview

An available Markdown attachment must open in the Azents attachment viewer as formatted Markdown.

**Acceptance criteria**

- A file identified as Markdown by a supported media type or common Markdown filename extension opens in the attachment viewer.
- Headings, lists, links, code blocks, tables, and other supported Markdown constructs are rendered as readable document content.
- Opening the preview does not navigate the user to a browser-native unsupported-file screen.
- The user can still download the complete original Markdown file.

### REQ-2. Broad readable-text preview

An available attachment that is reasonably identifiable as readable text must open in the Azents attachment viewer as safely escaped original text.

**Acceptance criteria**

- Common plain-text, source code, log, structured-data, and configuration filename extensions are previewable.
- Textual media types remain previewable even when the filename has no recognized extension.
- A generic or inaccurate media type does not prevent preview when the file is otherwise identifiable as readable text.
- Text preserves line breaks and remains scrollable on mobile and desktop.
- The user can still download the complete original file.

### REQ-3. Binary safety and fallback

The preview experience must not interpret binary content as text or Markdown.

**Acceptance criteria**

- Invalid text content and content containing binary control data use the existing unsupported-preview guidance.
- Archive, executable, and other known binary file types are not promoted to text preview solely because of an ambiguous filename or media type.
- Preview rendering does not execute scripts or trusted active content from the attachment.

### REQ-4. Consistent attachment navigation

Markdown and text previews must retain the existing attachment viewer controls and navigation behavior.

**Acceptance criteria**

- Close, previous, next, file metadata, and download controls remain available.
- Mobile uses the existing full-screen viewer behavior and desktop uses the existing bounded viewer behavior.
- Browser Back closes the preview according to the existing attachment viewer history behavior.

## Fixed Constraints

- Attachment access must continue to use the existing authenticated and authorized Exchange-file boundary.
- The original file bytes and download behavior must remain unchanged.
- Preview content must remain bounded so unusually large text attachments do not create an unbounded browser payload or UI surface.
- Existing unavailable and expired attachment behavior must remain unchanged.

## Open Assumptions

- The current Exchange-file preview summary can be extended or reclassified without changing attachment ownership or retention semantics.
- Common text filename extensions can be maintained as a conservative allowlist while content validation remains the final binary-safety boundary.

## Confirmation

Confirmed by the requester on 2026-07-24 before ADR and design decisions began.
