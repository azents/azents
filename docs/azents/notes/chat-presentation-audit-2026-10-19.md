---
title: "Chat presentation renderer audit"
created: 2026-10-19
tags: [frontend, chat, audit]
---

# Chat presentation renderer audit

## Scope and finding

The audit follows every transcript branch in `ChatView`, role/source route in
`MessageBubble`, nested Run activity event, pending input and live/status surface.
It does not change event grouping, Run lifecycle, scheduler, accounting, APIs or
persistence. Composer, session sidebars and global overlays are not transcript items.

The supplied screenshot exposed conflicting spacing ownership: `ChatView` uses a
zero-gap Stack; Routine judgment had no outer margin, Routine work owned a message
margin and a separate semibold header, and activity groups owned a compact margin
and another header implementation. Matching individual margins would leave the
underlying duplication intact.

## Standard presentation ownership

- `ChatTimelineItem`: one outer spacing owner for activity, message and boundary items.
- `ActivityRow`: canonical header typography, chevron/icon columns, status/action
  placement, controlled/uncontrolled disclosure, detail inset and keyboard behavior.
- `ChatDetailPanel`: standard border, radius, padding, maximum width and optional
  bounded detail viewport with the existing scroll-boundary behavior.
- `ChatHumanMessageBody`: shared human bubble for submitted, pending and optimistic input.
- `ActivityEventList`: reusable nested Run event routing and zero-gap list; children
  do not own top-level transcript spacing.

## Complete renderer disposition

| Route / surface                               | Disposition                                    | Preserved specialization                                                                              |
| --------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Routine judgment                              | Timeline + canonical row                       | Decision checklist, model/usage availability and error state                                          |
| Routine work / continuation                   | Agent disclosure using canonical row/panel     | Trigger/continuation labels and immutable input content                                               |
| Scheduled Task                                | Agent disclosure using canonical row/panel     | Structured schedule parsing, title tooltip, retained source content                                   |
| Agent mailbox                                 | Agent disclosure using canonical row/panel     | Sender path, source label, content and message actions                                                |
| External channel invocation/context           | Timeline + canonical row/panel                 | Provider icon, sender/preview, status badge, partial marker, original URL, metadata modal and actions |
| Goal/channel continuation and Goal update     | Compact timeline + canonical row               | Non-interactive control labels and source icon                                                        |
| Goal briefing                                 | Message timeline + standard panel              | Completion check, objective/content and completion metadata                                           |
| Ordinary user text/action                     | Message timeline + human body                  | Right alignment, sender, attachments, command/Skill/action pill, editing and actions                  |
| Assistant text                                | Message timeline                               | Markdown, media/files, streaming state and metadata/action row                                        |
| Standalone client/provider tool calls         | Message timeline, canonical child rows/panels  | Raw-data action, tool lifecycle, output and attachment behavior                                       |
| Error / failed Run recovery                   | Message timeline + standard panel              | Error copy, provider-vs-runtime failure, bounded output, attempt history and retry action             |
| Interruption                                  | Boundary timeline                              | Centered solid separator and interruption label                                                       |
| Compaction summary / in-progress              | Boundary timeline                              | Dashed separator, progress indicator and summary disclosure                                           |
| Authorization                                 | Message timeline; compact action stays inline  | Warning alert, authorization popup and completion callback                                            |
| Worktree create/remove                        | Message timeline + standard panel              | Branch/base ref/path, progress, output, failure/cancellation and status badge                         |
| Worktree cleanup                              | Compact timeline + canonical row               | Phase, counts, candidate details, latest progress, failure/cancellation and collapse behavior         |
| Agent-run indicator                           | Compact timeline                               | Animated dots, silence duration, reduced motion and status role                                       |
| Pending mailbox                               | Delegates to the corresponding message route   | Safe pending projection, opacity, deletion policy and source metadata                                 |
| Pending/optimistic input                      | Message timeline + human body                  | Pending controls, opacity, attachments and action content                                             |
| Activity-group active/completed/authorization | Compact timeline + canonical header            | Category summary, duration, failed count, live indicator and sibling authorization action             |
| Run reasoning                                 | Canonical nested row + standard bounded panel  | Sanitized preview, Markdown, collapse-from-detail and focus restoration                               |
| Run Skill-loaded / load_skill                 | Canonical nested row + shared Skill body/panel | Frontmatter stripping, Skill formatting and bounded scroll                                            |
| Run client tool known/generic                 | Canonical nested row + standard panel          | Semantic summaries, Raw dialog, code/diff/process/checklist/output widgets and errors                 |
| Run provider tool                             | Canonical nested row + standard panel          | Search queries/sources, image deliverables, raw output and status                                     |
| Run Goal/channel/other control                | Canonical nested row                           | Non-interactive control semantics and bounded preview                                                 |
| Hidden tool/system/completion/boundary events | No frame or spacing                            | Existing transcript filtering and action-execution placement                                          |

### Intentional inner differences

Code blocks, patch/diff file headers, tables, media, search-result links, todo and
Routine checklists, error output, raw-data dialogs and metadata footers own their
content-level layout. They are not additional timeline items. Compaction and
interruption remain visually distinct boundaries; human messages remain distinct
from Agent/activity rows. Skills were inspected, not presumed to be the original
spacing defect.

## Regression strategy

- `ChatPresentation` reproduces the supplied Routine/activity sequence and composes
  every compact disclosure route with canonical reasoning/Skill/client/provider rows.
  It compares row height, typography and icon alignment and exercises keyboard controls.
- `ChatView.StandardPresentationTranscript` verifies actual transcript wrapper geometry,
  using the same source/role fixtures rather than a parallel mock implementation.
- `ActivityEventList` covers mixed Run interiors, empty content, failed/running tool
  states, Skill bodies, raw actions and absence of nested timeline margins.
- Existing message, external-channel, activity-group, retry, worktree, boundary,
  pending-input and ChatView stories are included in the component contract suite.
- Native Storybook component renders use the product theme/fonts, Chromium DPR 1,
  en-US, light/dark and desktop/mobile viewports. They are component renders, not
  authenticated product screenshots or backend end-to-end evidence.

The suite also corrects stale exact-text selectors, missing live-state fixture props
and checks that ran before disclosure transitions completed. These are fixture and
synchronization corrections, not changes to runtime behavior.

## Local verification

- Web unit suite: 756 passed.
- Storybook contract suite: 205 passed across 23 files; unrelated stories without
  the `ci-contract` tag are outside this configured suite.
- Web typecheck, lint and production build: passed.
- Read-only independent source review: the cleanup accessible-status finding was
  corrected and rechecked; no additional material findings in Run-interior routing,
  Skill formatting, bounded scrolling, tool details or Raw-dialog behavior.
- Render matrix: Chromium, DPR 1, en-US, 1100 × 740 and 390 × 844, light/dark,
  loaded product Geist fonts; composed routes, full ChatView and expanded mixed Run
  details. Render artifacts remain outside tracked source.

These checks do not assert authenticated external-provider interoperability or
backend end-to-end behavior. PR CI is a separate validation stage.
