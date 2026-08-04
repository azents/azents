---
title: "Session Folder Project Browser Prominence"
created: 2026-08-04
tags: [session, workspace, project-browser, frontend]
document_role: primary
document_type: adr
snapshot_id: session-260804
---

# session-260804/ADR: Session Folder Project Browser Prominence

## Context

The confirmed
[session-260804/REQ](../requirements/session-260804-project-browser-session-folder-prominence.md)
requires the Session files root to remain first in the displayed Projects list and
to show the exact working-folder path supplied by its manifest entry.

The existing-session Project Browser manifest already puts the backend-owned
`session_folder` entry first and supplies its exact context-owned path. The Web
file browser rebuilds all displayed directory lists with a generic
directory-before-name sort, which discards that root precedence. It also reserves
root-row path text for registered Project and preview Project sources, excluding
the Session files root.

The change must preserve server ownership of manifest identity and path, the
relative ordering of registered Projects and Git worktrees, the existing search
filter behavior, and All files mode.

## Decision Map

- **Fixed or derived outcomes:** the server-provided `session_folder` source and
  path remain authoritative; only an included Session files entry receives root
  precedence; registered Project and Git-worktree ordering remains unchanged; and
  All files mode retains its current ordering.
- **Material decisions:** none. The confirmed Requirements and existing manifest
  contract determine the presentation behavior without a competing authority,
  source-of-truth, lifecycle, API, persistence, or compatibility outcome.
- **Agent-owned details:** local predicates, sort-rank expression, component
  structure, static Storybook fixture values, and test names.

## Decisions

No material architecture or product-contract decision is required for this
snapshot. The Design records the derived frontend presentation mechanisms.

## Fixed and Derived Outcomes

- The frontend consumes the manifest-provided `source.type` and `path` without
  constructing, substituting, or persisting a Session-folder path.
- The Session files root is first only while it survives the existing browser
  search filter.
- The existing title attributes remain the full-path affordance when layout
  truncates the supporting path.

## Agent-Owned Details

The implementation may choose local helper names, predicate placement, comparator
shape, static fixture paths, and Storybook story names provided those choices do
not add a source of truth, persisted state, API field, lifecycle behavior, or
browser mode.
