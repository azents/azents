---
title: "Chat Text File Preview"
created: 2026-07-24
tags: [chat, attachment, frontend, architecture, security]
document_role: primary
document_type: adr
snapshot_id: preview-260724
---

# Chat Text File Preview

- Snapshot: `preview-260724`
- Requirements: [`preview-260724/REQ`](../requirements/preview-260724-chat-text-file-preview.md)

## Context

Exchange-file creation already stores a bounded `preview_summary` when the original bytes are valid UTF-8 text without disallowed control characters. Chat projection exposes that value as `textPreview`, and the attachment viewer renders it as escaped monospaced text. The current viewer does not distinguish Markdown from ordinary text. When a preview summary is unavailable, file activation can fall back to the download URL, which leaves browser-native handling to decide whether the file can be displayed.

The accepted Requirements add formatted Markdown, broader filename-assisted text recognition, and continued binary safety without changing file ownership, retention, authorization, or original-download behavior.

## Decisions

### preview-260724/ADR-D1. Extend the existing stored preview boundary

**Affects:** `preview-260724/REQ-1`, `preview-260724/REQ-2`, `preview-260724/REQ-3`, `preview-260724/REQ-4`

Reuse the creation-time safe UTF-8 validation and bounded preview summary as the only text body supplied to the attachment viewer. Extend creation-time recognition with a conservative filename allowlist for common text, source code, log, structured-data, and configuration files when the declared media type is empty or explicitly generic/unknown. The frontend classifies the stored preview as Markdown or plain text from the attachment filename and normalized media type.

Markdown rendering uses the existing viewer shell and a non-HTML Markdown pipeline. Ordinary text remains escaped and pre-wrapped. Empty valid text remains a supported preview, while missing preview metadata retains the unsupported-download guidance. Existing attachments created without a preview summary are not reread or backfilled in this snapshot.

**Rejected:** An authenticated on-demand preview API could recover older attachments and serve longer previews, but it would add an authorization-sensitive original-file read path, object-storage traffic, generated-client changes, and asynchronous viewer states that are unnecessary for the accepted bounded-preview requirements.
