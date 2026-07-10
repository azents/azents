---
title: "ADR-0110: Use a Compact Integrated Chat Composer"
created: 2026-07-10
tags: [architecture, chat, frontend, mobile, accessibility]
---

# ADR-0110: Use a Compact Integrated Chat Composer

## Context

The current chat composer places attachment and Send/Stop controls outside the textarea on its left and right. That row has no remaining horizontal space for per-prompt model and reasoning-effort controls, especially on mobile. Adding another external control row would also consume scarce vertical viewport space when the mobile keyboard is open.

The composer already has a Goal/Todo preview attached above the input. The redesign must preserve its session-context role, distinguish it from prompt-scoped inference controls, and avoid turning the lower viewport into a stack of persistent bars. Mobile Safari also zooms focused form controls whose rendered text is smaller than 16 CSS pixels, so the textarea font size cannot be reduced to make the layout fit.

## Decision

Redesign the chat composer as one compact rounded surface with two default internal regions:

1. a one-line, vertically expanding textarea;
2. a compact bottom toolbar containing attachment, inference-profile, and Send/Stop controls.

Remove the external left attachment and right Send/Stop buttons. Their actions move into the bottom toolbar, giving the composer the full available width. Desktop may present Model and Reasoning effort as separate controls. Narrow mobile layouts use one compact profile control that displays both values and opens a selector where they remain independently editable. Reasoning effort is omitted when the selected model does not advertise selectable effort levels.

Keep the Goal/Todo preview as a single-line session-context tab docked behind the top edge of the composer. It is not part of the prompt toolbar. The tab is inset from the composer edges, truncates long content, and contributes only its exposed height because the composer visually masks its lower edge. When Goal and Todo both exist, show the active Goal objective and the Todo progress count in the same row rather than stacking two rows. Opening the tab continues to show full Goal and Todo details in a desktop dialog or mobile bottom sheet.

Prompt-specific attachments and selected actions appear inside the composer above the textarea only when present. They do not create empty reserved rows.

The compact mobile layout has these constraints:

- keep textarea and placeholder text at a rendered size of at least 16 CSS pixels to prevent Mobile Safari focus zoom;
- do not reduce input text size to achieve compactness;
- keep the default empty composer to a one-line textarea plus one compact toolbar row;
- target an approximately 80–84 CSS pixel default composer height before optional content;
- expose approximately 22 CSS pixels of the docked Goal/Todo tab, for an approximately 102–106 CSS pixel combined footprint when it exists;
- avoid a separate persistent model row above or below the composer;
- preserve only one exposed Goal/Todo tab row with no gap between the tab and composer;
- use compact toolbar controls with an approximately 32 CSS pixel visual height and an approximately 40 CSS pixel interaction target;
- truncate model display names before increasing height;
- let the textarea expand upward to its configured maximum, then scroll internally;
- account for the on-screen keyboard and bottom safe area without adding redundant vertical padding or strong mobile shadow.

The Send slot changes to Stop under the existing run/input-state rules. Voice input and other new toolbar actions are outside this feature's scope.

## Rejected options

### Add model and effort controls to the existing horizontal row

The external attachment and Send/Stop controls already consume the available width and leave no robust mobile layout.

### Add a persistent profile row outside the composer

A separate row increases the keyboard-open footprint and visually disconnects prompt-scoped settings from the prompt being composed.

### Stack Goal, Todo, model, and effort as independent bars

This consumes excessive vertical space and obscures the distinction between session context and prompt settings.

### Reduce the textarea font size

Text below 16 CSS pixels can trigger Mobile Safari auto-zoom and would reduce readability.

## Consequences

- `ChatInput` becomes a single integrated composer surface rather than a textarea flanked by external actions.
- Goal/Todo remains visually attached but semantically separate from prompt-scoped controls.
- The normal mobile footprint grows only enough for one compact internal toolbar; optional content adds height only when present.
- Responsive presentation may differ between separate desktop Model/effort controls and a combined mobile profile control while preserving the same requested-profile state.
- Storybook and browser coverage must include empty, Goal/Todo, attachment, action, editing, running, narrow mobile, keyboard-open, long-model-name, and unsupported-effort states.
- Mobile testing must verify that focusing the textarea does not trigger Safari auto-zoom.
