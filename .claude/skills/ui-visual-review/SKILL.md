---
name: ui-visual-review
description: Create and discuss trustworthy UI visual variants from the product's real components. Use when comparing UI options, reviewing visual polish, reproducing a screenshot, choosing spacing/typography/radius/layout alternatives, or presenting responsive desktop/mobile states as rendered images before implementation.
---

# UI Visual Review

Produce decision-ready UI images whose differences come from the requested design variables rather than from an inaccurate mock, font substitution, scaling, or unrelated layout drift.

## Establish the fidelity contract

Before rendering, identify and state the artifact type accurately:

- **Component render**: the repository's real component rendered through its existing app, Storybook, test page, or equivalent harness.
- **Product screenshot**: the actual application running in a representative environment.
- **Concept mock**: a separate approximation used only when the real component cannot express the proposal yet.

Prefer component renders. Never describe a reimplementation, manually drawn image, or font-substituted render as the actual UI. Disclose any known fidelity gap before asking the user to compare options.

## Inspect the real UI first

1. Locate the component, its stories/tests, styles, theme, fonts, icons, providers, and app shell.
2. Identify the baseline state and the exact variables under discussion.
3. Separate requested changes from invariants. Preserve surrounding geometry, content, state, and behavior unless they are explicitly part of the comparison.
4. Determine which states matter, including open overlays, validation, loading, long labels, Todo/status bars, autocomplete, and responsive layouts.
5. If desktop and mobile differ, verify that the difference is intentional. Do not invent platform-specific interaction patterns without a requirement.

Use the smallest real rendering surface that preserves product fidelity:

1. Existing story or visual test fixture
2. New story wrapping the real component
3. Running application route with controlled state
4. Temporary repository-local harness around the real component
5. Concept mock only as a disclosed fallback

Do not recreate the component in standalone HTML merely because it is faster.

## Define comparable options

- Give every option a stable number starting at 1.
- Change one decision axis at a time whenever possible.
- Keep viewport, content, state, theme, locale, font, zoom, and device scale identical across options.
- Include a baseline when it helps the user understand the change.
- Render all states needed to expose tradeoffs; do not choose only the state that makes an option look best.
- When responsive behavior is relevant, show desktop and mobile for each option with the same interaction model unless a deliberate difference is being evaluated.

Prefer one native-resolution image per numbered option. Use a matrix only when direct adjacency is essential and labels remain unambiguous.

## Render with product-equivalent conditions

Match the application environment rather than browser defaults:

- Use the app's actual theme and CSS entry points.
- Load the same font files and font variables as the app shell.
- Wait for `document.fonts.ready` and verify computed font family, size, weight, and line height on representative elements.
- Set explicit viewport dimensions, color scheme, locale, and device pixel ratio.
- Keep browser zoom at 100%.
- Wait for layout, animations, icons, and async content to settle.
- Disable motion only when it improves deterministic capture without changing final layout.
- Ensure popovers, drawers, menus, tooltips, and shadows fit fully inside the capture with useful surrounding whitespace.

Record the render conditions used. If the harness cannot match the app in a material way, fix it or downgrade the artifact classification.

## Capture without distorting the UI

Capture at native rendered size.

- Do not resize screenshots to make variants align.
- Do not stretch or resample a capture during composition.
- If composing images, paste each capture at 1:1 pixels and add only padding, labels, or background outside it.
- Avoid clipping overlays, focus rings, borders, and shadows.
- Keep enough surrounding context to judge alignment and hierarchy.
- Use lossless PNG unless the source itself is photographic.
- Prefer deterministic browser automation over manual screenshots.

Store generated comparison artifacts outside tracked source directories unless the repository explicitly treats them as fixtures or documentation assets.

## Validate before presenting

For every option:

1. Inspect the final image, not only the browser page.
2. Confirm the expected component and state are visible.
3. Confirm fonts and text sizes match the computed product styles.
4. Confirm native pixel dimensions were preserved through capture and composition.
5. Confirm only intended variables differ between comparable images.
6. Confirm overlays and neighboring elements are not clipped or accidentally moved.
7. Confirm numbering in filenames, image labels, and discussion text agrees.

If a validation check fails, regenerate the image rather than explaining away the discrepancy.

## Present the review

Attach the actual image files and keep the discussion concise:

- State whether each artifact is a component render, product screenshot, or concept mock.
- State the shared render conditions once.
- List numbered options with only their intentional differences.
- Call out any remaining fidelity limitation.
- Ask for a choice by number or for a specific adjustment.

Do not provide dead local paths or claim an attachment exists before it has been successfully presented.

## Iterate from user feedback

Treat feedback about subtle mismatch as evidence to re-check the render pipeline before debating taste. Investigate fonts, CSS entry points, viewport, device scale, scaling, state setup, and composition.

After the user chooses:

1. Restate the selected option and any constraints.
2. Apply exactly that decision to the real component when implementation is requested.
3. Preserve explicitly unchanged geometry and behavior.
4. Re-render the implemented result under the same conditions for verification.
5. Clearly distinguish the final implementation render from earlier proposal images.
