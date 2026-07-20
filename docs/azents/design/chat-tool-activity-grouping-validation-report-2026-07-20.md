---
title: "Chat Tool Activity Grouping Validation Report"
created: 2026-07-20
tags: [frontend, chat, tools, ux, testing]
---

# Chat Tool Activity Grouping Validation Report

## Scope

This report validates the complete frontend implementation described by [Chat Tool Activity Grouping](./chat-tool-activity-grouping.md) and [ADR-0173](../adr/0173-group-chat-tool-activity-in-the-frontend.md) through implementation commit `f6a6c04d`.

The validation covers:

- grouping continuous client and provider tool activity across model turns;
- explicit delivery, action, and terminal Run boundaries;
- the fixed collapsed `Activity` title and nested phase/detail disclosure;
- schema-gated specialized presentation and permanent Generic fallback;
- promoted generated-image delivery without duplicate attachment rendering;
- retained operational attachments inside tool details;
- compact approval state that does not create a grouping boundary;
- dark/light desktop and narrow mobile rendering;
- current implementation drift from living specs; and
- the existing full-stack provider image browser E2E contract.

Backend event, API, storage, and execution payloads remain unchanged.

## Environment

| Item | Value |
| --- | --- |
| Date | 2026-07-20 |
| Implementation commit | `f6a6c04d8ab54902152ae91a93bb4ba41e58776a` |
| Validation fix commit | `addb7a2880c2a87d02d35dca74d5bc53ba99abdb` |
| Runtime | Linux 6.8.0-134-generic x86_64 |
| Python | 3.14.6 |
| uv | 0.11.1 |
| Node.js | 24.18.0 |
| pnpm | 11.1.0 |
| Browser | Playwright Chromium 1.61.0 |
| Docker | Unavailable: `/bin/sh: docker: not found` |

The local runtime cannot start the containerized Azents E2E topology. The updated deterministic browser E2E therefore ran in the required GitHub Actions `ci-web-surface-e2e-run` job and passed after the provider empty-input fix. No local full-stack E2E pass is claimed.

## Added Validation

### Full-stack generated-image browser contract

`test_provider_image_generation.py::test_renders_one_activity_and_promoted_attachment_across_refresh` now validates the shipped presentation rather than the superseded individual-card layout.

After one deterministic provider-hosted image generation run, the browser must contain:

1. one `Activity` group;
2. one completed provider `image_generation` detail card owned by that group;
3. one promoted Exchange image in the conversation flow; and
4. zero Exchange images nested inside the provider card.

The same strict counts must remain after browser refresh. This preserves durable/live convergence while proving that promoted delivery does not duplicate the attachment inside diagnostic detail.

### Delivery-boundary regression coverage

The frontend projection tests now explicitly cover assistant-level attachment delivery between tool sequences. The attachment closes the preceding activity, renders as a normal message delivery, and causes later tool work to start a new activity.

### Production component browser matrix

The real `ChatView` Storybook story `SpecializedDeliverableAndApproval` was rendered through the product providers, Mantine theme, localization, real chat components, and repository font assets.

Shared conditions:

- browser zoom: 100%;
- device pixel ratio: 1;
- locale: `en-US`;
- font: `Geist Storybook`;
- desktop viewport: 1100 × 650;
- mobile viewport: 390 × 844;
- themes: dark and light;
- generated image route fulfilled with a deterministic one-pixel PNG while retaining the real Exchange attachment component and URL shape;
- screenshots captured at native size without resampling.

The deterministic image payload is the only fidelity substitution. Layout, disclosure, attachment ownership, status, approval UI, theme, typography, and responsive behavior use the production components.

| Viewport | Theme | Activity groups | Promoted images | Review actions | Horizontal overflow | Console errors | Result |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 1100 × 650 | Dark | 2 | 1 | 1 | None | None | Pass |
| 1100 × 650 | Light | 2 | 1 | 1 | None | None | Pass |
| 390 × 844 | Dark | 2 | 1 | 1 | None | None | Pass |
| 390 × 844 | Light | 2 | 1 | 1 | None | None | Pass |

All four renders also confirmed:

- the first activity and generated-media phase remain expanded after the story interaction;
- the later activity remains collapsed;
- `Review` is a separate button rather than a descendant of the activity disclosure;
- the promoted image appears exactly once;
- `generation.log` remains inside the tool detail;
- the fixed `Activity` title stays visible on mobile while lower-priority summary text truncates first; and
- computed title typography is 14 px, weight 550, 18.2 px line height using the repository Geist font.

Local screenshot artifacts are stored outside tracked source under `/workspace/agent/tool-call-ui-visual-review/07-validation-*.png`.

## Local Results

| Area | Command | Result |
| --- | --- | --- |
| Testenv lint | `cd testenv/azents/e2e && uv run ruff check .` | Pass |
| Testenv format | `cd testenv/azents/e2e && uv run ruff format --check .` | Pass; 51 files formatted |
| Testenv types | `cd testenv/azents/e2e && uv run pyright .` | Pass; 0 errors |
| Web lint | `cd typescript && pnpm --filter @azents/web lint` | Pass |
| Web types | `cd typescript && pnpm --filter @azents/web typecheck` | Pass |
| Web unit tests | `cd typescript && pnpm --filter @azents/web test` | Pass; 61 tests |
| Storybook build | `cd typescript && pnpm --filter @azents/web build-storybook` | Pass on the validation branch |
| Browser matrix | Playwright Chromium against built Storybook | Pass in four viewport/theme combinations |
| Patch integrity | `git diff --check` | Pass |
| Full-stack web E2E | `uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src` | Pass in required PR CI; not run locally because Docker is unavailable |

The known Node `MODULE_TYPELESS_PACKAGE_JSON` warnings remain non-failing and predate this feature.

## Primary Validation Matrix

| Scenario | Evidence | Status |
| --- | --- | --- |
| Multiple tool-only model turns | Pure projection test and native `ChatView` story | Pass |
| Visible assistant text between tool sequences | Pure projection boundary test | Pass |
| Assistant-level attachment delivery | Added projection regression test | Pass |
| Validated generated image | Registry test, production story, browser matrix, updated full-stack E2E | Pass; required CI gate completed |
| Reasoning, turn marker, or compaction between calls | Pure projection continuation test | Pass |
| Permission pause/resume | Compact `Review` production story; independent button and unchanged group count in browser matrix | Pass |
| Terminal Run followed by later tools | Pure projection terminal-boundary test | Pass |
| Explicit action/task transition | Existing action-placement boundary input to the pure projection | Pass |
| Known valid payload | Registry specialization and phase aggregation tests | Pass |
| Known malformed or incomplete payload | Registry Generic fallback tests | Pass |
| Adapter exception | Malformed runtime attachment test proves contained Generic fallback | Pass |
| Unknown attachment | Generic presentation emits no promoted deliverable and retains raw card attachments | Pass |
| Failed/running call while collapsed | Group summary story and status-count tests | Pass |
| Live-to-durable replacement | Existing client/provider semantic identity projection tests | Pass |
| Light/dark desktop | Native production component browser captures | Pass |
| Narrow mobile | 390 × 844 captures, title/Review retention, no page overflow | Pass |
| Browser refresh | Updated full-stack generated-image E2E | Pass in required PR CI |

## Implementation-to-Spec Comparison

| Contract | Implementation result | Current living spec | Spec-promotion action |
| --- | --- | --- | --- |
| Tool-only work groups across model turns until a user-visible boundary | Implemented by the frontend presentation fold | Not described in `domain/conversation.md` | Add continuation and boundary rules |
| Fixed collapsed `Activity` title with phase and detail disclosure | Implemented with stable group and phase identities | Not described | Add the three-level information hierarchy |
| Specialized presentation requires registered, validated input/output shapes | Implemented with per-call exception containment | Not described | Add registry validation and permanent Generic fallback |
| Generated images render as explicit deliveries and close the group | Implemented and covered by updated browser E2E | `domain/conversation.md` still says the image renders inside its owning tool card | Replace stale card-local wording |
| Promoted images do not duplicate inside detail; operational attachments remain | Implemented by URI-specific hiding | `flow/file-exchange-storage.md` still says image attachments render directly inside the tool card | Document promoted delivery and retained operational attachments |
| Approval remains inside ongoing work without splitting activity | Implemented as a compact independent `Review` action | Not described | Add approval grouping and accessibility behavior |
| Backend tool/event payloads remain unchanged | No backend or public-client contract changes | Existing event and semantic identity contracts remain aligned | Retain current backend contract wording |
| Durable provider calls replace matching live calls by `call_id` | Preserved | Existing `domain/conversation.md` wording is aligned | Verify and refresh metadata only |

No new ADR is required. ADR-0173 already owns the hard-to-reverse frontend grouping decision and remains immutable.

## Findings

- Validation found one stale full-stack browser assertion: it required the generated image to remain nested inside the provider card. The validation branch updates that test to the approved promoted-delivery contract.
- Validation added the missing assistant-level attachment boundary regression test.
- The first required CI run exposed one specialization defect: provider-hosted image calls may have an empty canonical input object, while the registry reused the client schema that requires a prompt. The fix separates client and provider image schemas, preserves the client prompt requirement, accepts the provider canonical allowlist with optional fields, and adds a unit regression for empty provider input.
- No remaining defect was found in grouping, specialization, delivery ownership, approval composition, theme behavior, or responsive layout.
- Mobile summary truncation behaves as designed: lower-priority metadata truncates before the fixed title or `Review` action is lost.
- Browser screenshots use a deterministic placeholder image body, so they validate layout and attachment ownership rather than image-content fidelity.
- Docker-dependent web-surface E2E passed in required GitHub Actions CI; no local full-stack E2E pass is claimed.

## Required CI Policy

`ci-web-surface-e2e-run` passed with the updated generated-image assertion and provider empty-input fix. The deterministic test required no external provider credential, and every other required changed-scope CI job also passed before spec promotion.
