---
title: "Chat Text File Preview Design"
created: 2026-07-24
updated: 2026-07-24
implemented: 2026-07-24
tags: [chat, attachment, frontend, backend, security]
document_role: primary
document_type: design
snapshot_id: preview-260724
---

# Chat Text File Preview Design

- Snapshot: `preview-260724`
- Requirements: [`preview-260724/REQ`](../requirements/preview-260724-chat-text-file-preview.md)
- ADR: [`preview-260724/ADR`](../adr/preview-260724-chat-text-file-preview.md)

## Scope and Traceability

| Requirement | Decision | Design mechanism |
| --- | --- | --- |
| `preview-260724/REQ-1` | `preview-260724/ADR-D1` | Classify Markdown from normalized media type and filename, then render the stored preview with GFM in the existing attachment viewer |
| `preview-260724/REQ-2` | `preview-260724/ADR-D1` | Extend creation-time text recognition with conservative filename rules and keep plain text escaped, pre-wrapped, and scrollable |
| `preview-260724/REQ-3` | `preview-260724/ADR-D1` | Preserve strict UTF-8 and control-character validation, exclude known binary media types from filename promotion, and omit raw HTML execution |
| `preview-260724/REQ-4` | `preview-260724/ADR-D1` | Reuse the current modal shell, history integration, navigation controls, metadata, and original download URL |

## Current Behavior and Gaps

Exchange-file creation calls a single text-preview classifier. It accepts textual media types and safe UTF-8 `application/octet-stream` payloads, rejects invalid UTF-8 and disallowed control characters, and stores at most 2,000 characters. The chat transport exposes that stored value as `FileAttachment.textPreview`.

`FileAttachmentList` currently treats any non-empty `textPreview` as generic text. Empty valid text is treated as unsupported because selection uses a truthiness check. `AttachmentPreviewViewer` renders text in a monospaced code surface and has no Markdown variant. Browser-native handling remains visible when users follow an original-file download URL, and Safari does not provide a useful native Markdown preview.

The current data boundary already supplies the filename, media type, safe bounded text, availability, file identity, and original download URL needed by the accepted Requirements.

## Proposed Architecture

### Creation-time text recognition

`ExchangeFileService` remains the only owner of Exchange text-preview admission. Its preview helper will accept the sanitized filename in addition to bytes and media type.

The classifier will:

1. normalize the declared media type without parameters;
2. accept the existing textual media types and structured suffixes;
3. accept `application/octet-stream` after content validation;
4. accept common text, source code, log, structured-data, configuration, and build filenames through a conservative extension and exact-filename allowlist only when the declared type is empty or explicitly generic/unknown;
5. decode strictly as UTF-8;
6. reject Unicode control characters other than tab, line feed, and carriage return; and
7. preserve the existing 2,000-character preview bound and truncation marker.

All specific non-text media types, including archive, executable, office-document, font, audio, video, and image types, remain ineligible for filename-assisted promotion. The final UTF-8 and control-character checks remain mandatory for every accepted path.

No database, API, event, or generated-client schema changes are required. New attachments receive the improved stored preview through the existing `preview_summary` field.

### Frontend preview classification

`FileAttachmentList` will classify available Exchange attachments into:

- image;
- Markdown;
- plain text; or
- unsupported.

Markdown identification will use normalized `text/markdown` media type or the common `.md`, `.markdown`, and `.mdx` extensions. A present `textPreview`, including an empty string, is required for both Markdown and text rendering. Missing preview metadata continues to select the unsupported guidance rather than fetching original bytes.

The preview descriptor will carry Markdown as an explicit variant instead of making `AttachmentPreviewViewer` reinterpret generic text.

### Markdown rendering

The existing attachment modal remains the primary workspace and retains its header, navigation, metadata, download action, mobile full-screen behavior, and desktop bounds.

Markdown content will render in the scrollable content area using the repository's existing `react-markdown` and GFM dependencies. The attachment renderer will:

- support headings, paragraphs, lists, task lists, blockquotes, links, fenced code, tables, and horizontal rules;
- use document-oriented spacing instead of the compact chat-bubble presentation;
- open links in a separate browsing context with `noopener noreferrer`;
- ignore embedded raw HTML;
- avoid Mermaid or other executable/custom renderers; and
- represent Markdown images without automatically loading remote image resources.

Plain text keeps the monospaced pre-wrapped surface. Both variants remain bounded by the stored preview summary.

## State and Failure Handling

The existing attachment availability and viewer state model remains unchanged.

- Available attachment with a stored preview: open Markdown or text preview synchronously.
- Available attachment without a stored preview: show unsupported-preview download guidance.
- Empty valid text preview: open a valid empty text or Markdown preview.
- Expired or unavailable attachment: preserve current disabled/unavailable behavior.
- Invalid Markdown syntax: render the valid parseable subset as text content; it does not block the viewer.
- Truncated preview: display the existing truncation marker included in stored content.

No new loading, retry, network error, or object-storage state is introduced.

## Security and Permissions

Preview admission remains inside the existing Exchange-file creation and ownership boundary. The browser receives only the already-projected bounded preview text and the existing authorized download URL.

The Markdown path does not enable raw HTML or script execution. URL sanitization remains owned by `react-markdown`; links open with isolation attributes, and remote Markdown image sources are not fetched automatically. Text rendering continues to escape file content.

## Rollout and Compatibility

This is one focused frontend and backend PR with no migration or feature flag.

- Newly created attachments use filename-assisted text recognition.
- Existing attachments that already contain `preview_summary` gain Markdown rendering immediately.
- Existing attachments without `preview_summary` remain unsupported because `preview-260724/ADR-D1` rejects on-demand rereading and backfill.
- Reverting the change restores generic text rendering and the previous media-type-only admission behavior without affecting stored files or original downloads.

## Test Strategy

### E2E primary verification matrix

| Scenario | Browser evidence |
| --- | --- |
| Markdown attachment | Storybook browser interaction opens the tile and asserts a heading, GFM table, link, code block, metadata, navigation shell, and download control inside the dialog |
| Empty text attachment | Storybook browser interaction opens the tile and asserts the viewer opens rather than unsupported guidance |
| Unsupported binary attachment | Existing Storybook state continues to show unsupported guidance and download access |
| Mobile layout | Existing full-screen responsive modal behavior is retained; the Markdown story uses the same viewer component and responsive CSS |

The Storybook browser interactions are the primary deterministic UI evidence because the changed behavior begins after canonical attachment projection and does not require a live model or provider. A full session Selenium fixture would duplicate attachment creation and projection behavior already covered by backend tests while adding unrelated authentication and session orchestration.

### Backend verification

Targeted `ExchangeFileService` tests will cover:

- recognized text filename with an empty or generic/unknown media type;
- specific non-text media types, including vendor document types, with a text-looking filename remaining unsupported;
- Markdown media type;
- generic safe UTF-8 content;
- invalid UTF-8, disallowed controls, and truncation.

### Frontend verification

- Storybook interaction coverage will verify Markdown selection and rendering from a real `FileAttachmentList`.
- The viewer story will cover the standalone Markdown surface and safe link behavior.
- TypeScript format, lint, typecheck, and build checks will cover descriptor exhaustiveness and styling.

### Fixtures and prerequisites

All fixtures are static and contain no credentials. No provider, object-storage, or live browser OAuth prerequisite is required for the primary verification. CI should fail on any deterministic Storybook interaction, backend unit test, lint, typecheck, or build failure; there are no optional live tests in this snapshot.

## Feasibility

| Requirement or decision | Result | Evidence |
| --- | --- | --- |
| `preview-260724/REQ-1` | Feasible | Attachment projection already includes filename, media type, and bounded text; `react-markdown` and GFM are existing dependencies |
| `preview-260724/REQ-2` | Feasible | Exchange-file creation owns preview admission and can use filename metadata without schema changes |
| `preview-260724/REQ-3` | Feasible | Existing strict UTF-8 and control-character checks are reusable; renderer does not need raw HTML |
| `preview-260724/REQ-4` | Feasible | The existing viewer shell already owns navigation, history, responsive layout, metadata, and download controls |
| `preview-260724/ADR-D1` | Feasible | No new API, persistence, authorization, migration, or asynchronous viewer state is required |

## Remaining Non-Blocking Risks

- The explicit filename allowlist will require maintenance as new textual ecosystems appear.
- A 2,000-character stored preview may truncate large documents before later sections.
- Attachments created before safe preview summaries were stored remain unsupported until a future on-demand or backfill snapshot is approved.
