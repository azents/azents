---
title: "Main Web Theme and Contrast"
created: 2026-10-22
updated: 2026-10-22
tags: [web, theme, accessibility, contrast]
spec_type: domain
domain: web-theme
code_paths:
  - typescript/apps/azents-web/src/shared/theme.ts
  - typescript/apps/azents-web/src/shared/theme.module.css
  - typescript/apps/azents-web/src/shared/providers/mantine.tsx
  - typescript/apps/azents-web/src/shared/ThemeContrast.stories.tsx
  - typescript/apps/azents-web/src/shared/storybook/contrast.ts
  - typescript/apps/azents-web/src/features/workspace/components/WorkspaceHome.module.css
  - typescript/apps/azents-web/src/shared/toolkits/components/GoogleSetup.stories.tsx
  - scripts/ci/component_portfolio.py
last_verified_at: 2026-10-22
spec_version: 1
---

# Main Web Theme and Contrast

Main Web and its Storybook use the same `AppMantineProvider`, theme, and semantic
CSS-variable resolver. The primary monochrome fill uses shade 9 in light mode
and shade 0 in dark mode. Semantic status colors remain caller choices.

## Filled Controls

The shared filled-variant resolver computes the foreground from the actual
background separately for each color scheme, including explicitly selected
palette shades. Automatic contrast selects whichever pure black or white has
the higher WCAG contrast. Button, ActionIcon, and selected Chip also resolve
their foreground against the hover fill for desktop hover and touch pressed
states. Dedicated contrast tokens keep this independent of
the warm canvas white and black tokens. Explicit `autoContrast={false}` retains
Mantine's caller opt-out. Other variants retain Mantine's normal resolver.

Badge, ThemeIcon, and Chip receive an explicit filled default so their default
rendering applies the resolver rather than falling back to a white foreground
in library CSS. Checkbox and Radio share the filled foreground rule unless an
explicit icon color or outline variant owns that choice. A checked, enabled
Switch uses the same rule for track text and thumb; unchecked and disabled
styling remains library-owned.

Human message Paper uses the shared `message` variant. Session Context badges
provide semantic fills without maintaining their own foreground/background
pairs. Browser and GitHub badges rely on the shared defaults.

## Semantic Surfaces

The theme owns secondary text, canvas, surface, raised surface, hover surface,
border, stronger border, muted/subtle text, error text, and inverse-surface
tokens. Workspace Home and chat error styling consume these tokens instead of
maintaining per-screen light/dark palettes. Metadata popovers consume inverse
surface tokens and their child text inherits the foreground. Browser secondary
text uses the same globally readable dimmed token as the rest of Main Web.

Media overlays, terminal canvases, alpha masks, and syntax highlighting have
content-specific presentation needs; they are not filled-control overrides.

## Regression Coverage

Required component CI includes light/dark theme contrast stories, explicit
caller override/variant preservation stories, and saved Google connection
stories. Theme stories measure computed browser colors for Badge, Button,
ActionIcon, ThemeIcon, selected Chip, checked Checkbox/Radio, checked Switch,
human-message and inverse surfaces, and secondary text. Text and checked icon
contrast must be at least 4.5:1 for the covered palette matrix. Theme stories
also fail on accessibility violations rather than using the global Storybook
`todo` policy. Explicit caller override fixtures instead verify preservation.

This is shared-control regression protection, not a claim that every possible
custom color, translucent background, media surface, or existing product screen
has completed an accessibility audit.
