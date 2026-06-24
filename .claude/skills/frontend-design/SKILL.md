---
name: frontend-design
description: Frontend UX and visual design guidance for building polished product surfaces, dashboards, admin tools, workflows, and local web apps. Use when designing or reviewing UI layout, interaction flow, information hierarchy, utility copy, responsive behavior, or visual quality before implementing frontend code.
---

# Frontend Design

Use this skill before implementing or reviewing a frontend surface. Bias toward a working product UI that helps the user operate, monitor, compare, and decide.

## Workflow

1. Identify the primary job, user role, and repeated workflow.
2. Classify features by task: discover, inspect, edit, sync, save, recover, or monitor.
3. Turn tasks into a screen flow before choosing visual treatment.
4. Put the primary workspace first; reserve decoration for cases where it clarifies the subject.
5. Check keyboard, empty, loading, error, mobile, and overflow states before calling the UI done.

## Product UI Rules

- Use utility copy: labels, headings, and status text should explain scope, freshness, action, or decision value.
- Start with the working surface itself: filters, tables, media, inspector panels, status, and task controls.
- Keep hierarchy calm: strong typography, compact spacing, restrained borders, and one clear accent color.
- Use real task content as the visual anchor. For media-heavy tools, the media preview should dominate the first viewport.
- Use cards only when the card itself is the repeated interaction unit. Prefer panes, tables, split views, inspectors, and sticky toolbars for workspaces.
- Keep controls close to the thing they affect. Make destructive, sync, and commit actions visibly distinct.
- Avoid hero sections, marketing copy, decorative gradients, generic card mosaics, and stacked cards in operational tools.

## UX Review Checklist

- Can the user understand the page by scanning headings, labels, counts, and status badges?
- Can the primary workflow be completed without losing context or opening unrelated screens?
- Are next/previous, add/remove, save, and sync actions reachable without scrolling during repeated work?
- Are unsaved changes, sync gaps, drift warnings, and failures visible at all times?
- Does mobile collapse into a focused flow without hiding the current task state?

Read `references/openai-delightful-frontends.md` when a task needs the OpenAI frontend design reference behind these rules.
Read `references/product-admin-design-laws.md` when building admin consoles, dashboards, dataset tools, tables, editors, or dense operational surfaces.
