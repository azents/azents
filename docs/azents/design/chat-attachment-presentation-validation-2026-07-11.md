---
title: "Chat Attachment Presentation Validation"
created: 2026-07-11
tags: [frontend, chat, attachments, testing]
---

# Chat Attachment Presentation Validation

## Environment

- azents-web Storybook production build
- Chromium via Playwright 1.61.1
- Mobile viewport: 430 × 932 CSS pixels, device scale factor 3
- Color scheme: light
- Locale: ko-KR
- Font: Geist Storybook provider stack

## Commands

```console
cd typescript
pnpm run format --filter=@azents/web
pnpm run lint --filter=@azents/web
pnpm run typecheck --filter=@azents/web
pnpm exec turbo run build-storybook --filter=@azents/web
```

Documentation validation:

```console
python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
git diff --check
```

## Results

| Area | Result | Evidence |
| --- | --- | --- |
| Compact user strip | Passed | 200px tiles remain horizontal and the partial next tile is visible through the right-edge fade. |
| Composer strip | Passed | Multiple pending files remain one row and expose the same dynamic overflow affordance. |
| Agent gallery | Passed | Three-image fixture renders as square two-column cells with `cover`. |
| Agent mixed group | Passed | Gallery and compact file strip share one bordered group. |
| Mobile image viewer | Passed | Dialog bounds are 430 × 932; fixed header is 62px; image stage remains contained and zoom controls stay reachable. |
| Mobile text viewer | Passed | Dialog bounds are 430 × 932 and text scroll remains inside the viewer. |
| Provider fidelity | Passed | No page errors; Geist font, Mantine theme, next-intl provider, locale, and DPR were active. |
| Frontend checks | Passed | Format, lint, typecheck, and Storybook build completed successfully. |

## Overflow State Verification

The user strip measured 263px client width against 1250px scroll width. The composer strip measured 328px client width against 862px scroll width. At the initial position both exposed the required right-edge 40px mask. The implementation derives left/right masks from `scrollLeft`, `scrollWidth`, and `clientWidth`, producing both-edge and left-only states at intermediate and final positions.

## Design and Spec Comparison

| Contract | Implementation | Living spec before promotion |
| --- | --- | --- |
| Compact composer/user strips | Implemented | Missing |
| Dynamic start/middle/end fades | Implemented | Missing |
| Agent image gallery and mixed group | Implemented | Missing |
| Shared mobile/desktop preview viewer | Implemented | Missing |
| Localized controls and focus restoration | Implemented | Missing |
| Original/preview availability independence | Preserved | Partially documented |

The File Exchange Storage spec is promoted in this stack to close the identified drift. Storage, authorization, retention, upload, and download contracts are unchanged.

## Remaining External Integration

The deterministic presentation path does not require a live model provider. A full authenticated upload/download browser pass still depends on the standard testenv workspace and object-storage fixture; no frontend behavior was skipped in the Storybook and native-scale validation above.
