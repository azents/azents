---
title: "Chat Attachment Presentation"
created: 2026-07-11
updated: 2026-07-11
tags: [frontend, chat, attachments, ux]
---

# Chat Attachment Presentation

## Problem

Chat attachments currently use unrelated presentation rules depending on where and how they appear. Pending composer attachments are cards, message images are free-form inline previews, text files are expandable rows, and generic files are plain download rows. Mixed attachment sets therefore look like unrelated elements, consume unpredictable vertical space, and behave differently before and after sending.

The redesign must make attachment presentation coherent without weakening the intent of Agent-produced images, which are usually sent for immediate viewing rather than merely as downloadable files.

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

## Current Behavior

`AttachmentPreviewBar` renders pending files as wrapping cards. `FileAttachmentList` independently branches into image thumbnails, expandable text previews, and generic download rows. `MessageBubble` places the same list in differently sized user, assistant, and tool-result containers, so identical attachment data wraps differently by message role.

The current outcomes are inconsistent:

- multiple pending attachments grow the composer vertically;
- user images appear as free-form inline media even though they mainly serve as sent-file history;
- Agent images and generic files use unrelated geometry;
- a mixed set has no shared visual boundary;
- text preview expansion changes message height in place;
- preview interaction is coupled to individual file rendering branches.

## Design Principles

### Intent is role- and composition-dependent

Presentation is selected from both the attachment origin and the complete attachment set. File media type alone does not select the message layout.

- User-originated attachments are compact sent-file records.
- Agent-originated images are visual output intended for immediate inspection.
- Agent-originated non-image files use the same compact file tile language as user attachments.
- Agent-originated mixed sets preserve inline images while grouping all files into one attachment collection.

Agent-originated includes assistant message attachments and user-visible files attached to Agent/tool output. User-originated includes committed user messages and pending input-buffer projections.

### Shared primitives, different composition

All non-prominent attachments use the same `AttachmentTile`. Agent image presentation uses an adaptive gallery. Mixed Agent output combines the gallery and tile strip inside one `AttachmentGroup` rather than inventing a third file-card style.

### Preview is a capability

The viewer selects a renderer from available preview data, not from ad hoc component branches. MIME type may inform labeling and backend preview generation, but the UI opens a preview only when a supported preview capability is present.

## Presentation Matrix

| Origin | Composition | Presentation |
| --- | --- | --- |
| Composer | Any pending files | One horizontal `AttachmentTile` strip |
| User | Any sent files, including images | One horizontal `AttachmentTile` strip |
| Agent | Images only | Adaptive inline image gallery |
| Agent | Non-image files only | One horizontal `AttachmentTile` strip |
| Agent | Images and non-image files | One `AttachmentGroup`: image gallery followed by horizontal `AttachmentTile` strip |

## Attachment Tile

The tile is the shared compact representation before and after sending.

### Geometry

- Fixed width: `200px`.
- Nominal height: `60px`.
- Tiles never wrap; the parent strip scrolls horizontally.
- Thumbnail/icon slot: `40px` square.
- File name is one truncated line.
- Secondary line contains file type and formatted size, or availability/upload status.
- The trailing action occupies a stable slot.

### Content

- Image files use a small cropped thumbnail.
- Other files use a file-type icon.
- Pending composer tiles show upload status and a remove action.
- Sent tiles show preview/download availability and a download action.
- Expired or unavailable files keep name, type, and size metadata while disabling preview and download.

### Horizontal overflow affordance

A transparency mask communicates that more tiles continue off-screen.

- Fade width: `40px`.
- At the initial scroll position, only the right edge fades.
- At an intermediate position, both edges fade.
- At the final position, only the left edge fades.
- No edge fades when the content does not overflow.
- The mask follows scroll position and does not intercept pointer or touch input.
- Native touch scrolling and horizontal wheel/trackpad scrolling remain available.

## Agent Image Gallery

Agent image-only output uses an adaptive gallery because its primary intent is immediate viewing.

### Layout

- One image: render at its natural aspect ratio with `contain`, up to `480px` high.
- Two images: two-column gallery.
- Three or four images: two-column grid.
- Five or more images: show the first four cells and a `+N` affordance in the final visible cell.
- Multi-image cells are square and use `cover`; selecting a cell opens the full preview without cropping.
- Gallery width is bounded by the message content width.

## Agent Mixed Attachment Group

When Agent output contains both images and non-image files, all attachments appear inside one bordered `AttachmentGroup`.

- The image gallery appears first.
- The shared horizontal `AttachmentTile` strip appears below it.
- Group padding and radius use Mantine tokens.
- The group owns the visual boundary; the image and file sections do not add unrelated outer card styles.
- The tile strip retains the same edge-fade behavior as user and composer strips.

## Preview Viewer

`AttachmentPreviewViewer` is a shared shell with a preview renderer selected from preview capability data.

### Common shell

- Fixed header with close, file name, MIME type, size, and download action.
- Preview body owns its own scrolling and zoom behavior.
- Download remains reachable while preview content scrolls or zooms.
- Expired or unavailable content cannot open the viewer.
- Closing returns focus to the tile or gallery cell that opened the viewer.

### Mobile presentation

- Use a full-screen overlay.
- Do not use a bottom Drawer.
- Do not support swipe-to-dismiss because it conflicts with image pan, pinch zoom, long text scrolling, and future document gestures.
- Respect top and bottom safe-area insets.

### Desktop presentation

- Use a large centered Modal with the same header and renderer components.
- Bound the Modal to the viewport while leaving surrounding context visible.
- Escape closes the Modal unless another nested interaction owns Escape.

### Preview renderer contract

The frontend normalizes attachment preview fields into a discriminated preview descriptor.

| Preview kind | Current/future source | Renderer |
| --- | --- | --- |
| Image | Original image or image preview URL | Large contained image with zoom and pan |
| Text | `textPreview` | Scrollable monospaced text surface |
| Document page | Future first-page image preview, using generalized preview metadata | Contained page image with zoom and pan |

The current `FileAttachment` fields already provide `textPreview`, `previewThumbnailUri`, preview media type, dimensions, and generation time. Initial implementation maps those fields into the preview descriptor without changing the backend contract. Future PDF first-page support should publish preview metadata through the same generalized preview boundary rather than adding PDF-specific UI fields.

### Image renderer

- Start at a fitted `100%` view.
- Support pinch zoom and pan on mobile.
- Support visible zoom-out, zoom percentage, and zoom-in controls.
- Keep the image stage dark to distinguish media from the surrounding application.
- Preserve access to the header download action at all zoom levels.

### Text renderer

- Display `textPreview` in a monospaced, pre-wrapped surface.
- Scroll inside the viewer body.
- Preserve UTF-8 text, whitespace, and line breaks.
- Do not expand text inside the chat message itself.

### Future document renderer

- Display a generated first-page preview inside the same viewer shell.
- Reuse image zoom and pan behavior.
- Keep the original document download action in the header.
- Multi-page document navigation is outside the initial PDF preview scope.

## Interaction Rules

- Selecting a prominent Agent image opens its preview.
- Selecting a tile with preview capability opens the shared viewer.
- The tile download action downloads without opening the viewer.
- Selecting a tile without preview capability downloads the file when available.
- Unavailable tiles remain non-interactive except for any future explanatory status affordance.
- Horizontal tile scrolling must not accidentally open a tile after a drag gesture.

## Accessibility

- Tile and gallery-cell accessible names include file name and relevant availability state.
- Close, download, zoom-in, and zoom-out controls use localized accessible labels.
- The viewer traps focus while open and restores focus on close.
- Keyboard users can open tiles, scroll preview text, zoom images, download, and close.
- Status is conveyed through text as well as color.
- Gallery crops do not replace descriptive alternative text in the full viewer.
- Reduced-motion preference disables nonessential viewer transitions.

## Responsive Behavior

- Composer and user tile strips use the available container width and preserve a partial next tile plus fade as the continuation cue.
- Agent galleries switch based on image count, not arbitrary viewport-specific presentation modes.
- Mixed groups keep gallery and tile-strip order on all viewport sizes.
- Desktop may reveal more tiles before scrolling but does not change tile geometry or file information hierarchy.

## Error and Availability Handling

- Original-file availability and preview availability remain independent.
- If preview generation or loading fails but the original is available, retain download and fall back to the compact tile.
- If the original is unavailable, disable viewer and download even if stale preview metadata exists.
- Image load failures show a neutral file thumbnail fallback without collapsing the tile geometry.
- Viewer loading and renderer errors remain inside the viewer shell and preserve close/download actions when valid.

## Implementation Shape

The intended component boundaries are:

- `AttachmentTile`: shared compact file representation.
- `AttachmentStrip`: horizontal scrolling, dynamic edge fade, and drag/click separation.
- `AgentImageGallery`: adaptive image-only gallery.
- `AttachmentGroup`: mixed Agent composition.
- `AttachmentPreviewViewer`: responsive full-screen/Modal shell.
- Preview renderer components for image, text, and future document pages.
- A pure presentation selector that derives the presentation mode from origin and attachment composition.

`AttachmentPreviewBar`, `FileAttachmentList`, `InputBufferBubbleFrame`, and `MessageBubble` should compose these primitives instead of maintaining independent file-type branches.

## Migration and Rollout

1. Introduce shared tile, strip, gallery, group, and preview descriptor primitives with Storybook fixtures.
2. Replace composer attachment wrapping with `AttachmentStrip`.
3. Replace user and input-buffer attachment rendering with compact strips.
4. Replace Agent image-only and mixed rendering with the gallery/group presentation selector.
5. Connect image and text tiles to `AttachmentPreviewViewer`.
6. Remove the old inline text collapse and type-specific list branches.
7. Update the File Exchange Storage living spec after implementation.

No compatibility presentation mode is retained. Existing attachment metadata remains readable through the new presentation selector.

## Alternatives Considered

### One universal tile for every attachment

Rejected because Agent-produced images carry an immediate-viewing intent that a small tile would hide.

### Separate image gallery and file list for mixed Agent output

Rejected because the mixed set would continue to look like unrelated outputs.

### Vertical file lists

Rejected because they reintroduce unbounded message and composer height.

### Bottom Drawer preview on mobile

Rejected because Drawer dismissal gestures conflict with image pan/zoom, text scrolling, and future document interactions.

### MIME-specific viewer components with independent shells

Rejected because navigation, download, availability, focus, and responsive behavior would drift again as new preview formats are added.

## Test Strategy

### E2E primary verification matrix

| Surface | Cases |
| --- | --- |
| Composer | one file, multiple mixed files, uploading, error, remove, overflow/no-overflow, start/middle/end fade states |
| User message | image-only, non-image-only, mixed files, long names, expired/unavailable, horizontal drag without accidental open |
| Agent message | one image, two images, three/four images, five-plus overlay, non-image-only, mixed attachment group |
| Preview viewer | image fit/zoom/pan/download/close, text scroll/download/close, unavailable preview fallback |
| Responsive | mobile full-screen viewer, desktop Modal, narrow message width, desktop wide message width |
| Accessibility | keyboard open/close/download/zoom, focus restoration, accessible labels, reduced motion |

### E2E plan

- Use the real chat upload flow to attach image, text, PDF-shaped binary, and archive fixtures to a user message.
- Seed deterministic Agent messages containing image-only, non-image-only, and mixed attachment snapshots.
- Verify geometry and visibility through roles and bounded layout assertions rather than pixel-only selectors.
- Exercise horizontal scrolling to start, middle, and end positions and assert the corresponding mask state.
- Open image and text previews, verify the full-screen mobile shell, exercise zoom/text scroll, download, and close.
- Run a desktop viewport pass to verify Modal sizing and focus restoration.

### Fixture and prerequisite support

- Add deterministic image fixtures with portrait and landscape aspect ratios.
- Add UTF-8 text fixtures with long lines and enough content to scroll.
- Add available, expired, unavailable, and preview-missing attachment snapshots.
- PDF first-page rendering remains excluded until backend preview generation exists; its UI renderer can use a static first-page image fixture in Storybook.
- Reuse the existing authenticated workspace/session E2E prerequisite. No live model provider is required for deterministic attachment presentation tests.

### Credential and snapshot requirements

- CI requires only the standard authenticated E2E workspace fixture and object-storage/download test configuration.
- Do not require external provider credentials or live image generation.
- Capture the seeded attachment manifest and viewport configuration in test diagnostics so failures can be reproduced.

### Evidence

- Native-scale Storybook component renders for each presentation matrix row.
- Playwright screenshots for mobile and desktop at deterministic viewport and device scale.
- Playwright trace on failure, including scroll position and viewer state.
- CI logs for layout assertions, accessibility labels, and download responses.

### CI execution policy

- Deterministic Storybook build, interaction checks, and attachment E2E tests are required CI checks.
- Tests using only local fixtures must fail CI on any assertion failure; they are never optional skips.
- Future live-provider or live-PDF-generation coverage may run separately and may skip only when its explicitly declared credential or service prerequisite is unavailable.
- A missing standard authenticated workspace, Exchange download route, or required fixture is a failure rather than a skip.

## Spec Impact

After implementation, update `docs/azents/spec/flow/file-exchange-storage.md`:

- expand the UI Contract with the role/composition presentation matrix;
- document the shared preview viewer and preview-capability selection;
- update `last_verified_at` and increment `spec_version`;
- keep storage, lifecycle, and authorization behavior unchanged.

## Open Questions

- Exact desktop Modal maximum width and height should be finalized during desktop visual review.
- Future PDF preview generation must decide whether the generalized preview thumbnail represents only the first page or supports multiple page preview assets.
- The five-plus image gallery `+N` interaction may open the first hidden image or a gallery index; this should be selected during interaction implementation.
