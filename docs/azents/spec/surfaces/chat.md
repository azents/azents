---
title: "Chat presentation and navigation"
created: 2026-11-04
tags: [wiki]
---

# Chat presentation and navigation

Owns concrete and draft Chat layout, supporting navigation and renderer behavior. Timeline synchronization and durable Session state remain separate from visual presentation.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Chat resynchronization](../flow/chat-session-resync.md)
- [Session Context Inspector](../flow/session-context-inspector.md)
- [Conversations and events](../domain/conversation.md)
- [Web theme and contrast](../domain/web-theme.md)

## Viewport and composer layout

Draft and concrete-session chat routes use a full-height, document-contained viewport.
While this surface is mounted, CSS fixes the body to the viewport and makes the AppShell
and Agent content inherit its height. Leaving the chat route removes that containment;
settings and directory pages keep their ordinary document scrolling. Non-scrolling chat
surfaces permit pinch zoom but do not initiate vertical touch panning. The native timeline
and draft content scrollers explicitly permit vertical panning and pinch zoom. Native
textarea editing, multiline scrolling and selection remain unchanged. This boundary uses
CSS `touch-action`, not keyboard-height calculations, viewport-offset correction, forced
focus/scroll, gesture event cancellation or a JavaScript document scroll lock.

Concrete-session composers float over the conversation in a separate layer anchored to
the chat column's lower edge. The surrounding layer is transparent and lets pointer
gestures reach the timeline; the input card retains its own background and controls.
The timeline reserves the measured composer height at its end so the final message can
scroll above the input, including when multiline input or attachments change that height.
The vertical timeline scrollbar ends at the input card's top edge without reducing
the conversation's scroll viewport. Conversation items remain fully opaque above that
edge and fade linearly to transparent at the card's bottom edge. This alpha mask affects
only the timeline, not the composer or scrollbar. The track and mask boundaries follow
the measured card height as multiline input, attachments or composer status change.
The layout does not track `VisualViewport` or infer keyboard geometry. Draft screens
retain their native bottom composer and independently scrollable setup content.

Both chat routes request `interactive-widget=resizes-content` viewport behavior so
supporting browsers resize the layout with the on-screen keyboard. Browsers that do not
support this directive retain their native keyboard viewport behavior. This does not
register an OS keyboard accessory. Safari and embedded WebKit may still pan the native
viewport or expose a keyboard-related bottom gap despite document containment; this
layout does not guarantee suppression of that browser behavior.

## Markdown rendering

azents-web renders user-visible chat Markdown with GitHub Flavored Markdown, soft line breaks, and
compact chat typography. Fenced code blocks render through the chat code block renderer. A fenced code
block with language `mermaid` renders as an inline Mermaid diagram instead of syntax-highlighted text.
The Mermaid renderer is client-side, lazy-loads the Mermaid package, uses strict Mermaid security
settings for untrusted chat content, and falls back to the original source block with a user-visible
error message when diagram rendering fails.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`typescript/apps/azents-web/src/features/chat`](../../../../typescript/apps/azents-web/src/features/chat)
- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
