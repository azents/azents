---
title: "Session Folder Project Browser Prominence Design"
created: 2026-08-04
updated: 2026-08-04
implemented: 2026-08-04
tags: [session, workspace, project-browser, frontend]
document_role: primary
document_type: design
snapshot_id: session-260804
---

# Session Folder Project Browser Prominence Design

- Snapshot: `session-260804`
- Requirements: [`session-260804/REQ`](../requirements/session-260804-project-browser-session-folder-prominence.md)
- ADR: [`session-260804/ADR`](../adr/session-260804-project-browser-session-folder-prominence.md)
- Design reference: `session-260804/DESIGN`

## Current Behavior and Requirement Gaps

The existing-session Project Browser manifest emits the `session_folder` root
before registered Project roots and carries the exact
`SessionAgentContext.working_folder_path`. The frontend maps that response into
`WorkspaceEntry` without changing the path.

`FileBrowser.buildTree()` currently applies `sortEntries()` to every list,
including Projects roots. Its generic directory-before-name comparator can place
Session files after registered roots. `getEntryDisplayPath()` renders supporting
path text for `session_project` and `preview_project` root rows but not
`session_folder`.

| Requirement | Current gap |
| --- | --- |
| `session-260804/REQ-1` | Frontend sorting can discard the manifest's Session files root precedence. |
| `session-260804/REQ-2` | The Session files row omits its manifest-provided exact path. |

## Architecture

### Ownership and source of truth

The Project Browser manifest remains the source of truth for the root entry's
identity, `source.type`, display name, exact path, status, and capabilities.
Azents Web consumes those values as mapped `WorkspaceEntry` data. It does not
derive a Session-folder path from the workspace root, a Session identifier, or a
known directory convention.

### Projects-root ordering

`FileBrowser` adds a source-type predicate for `session_folder`. Its shared entry
comparator places that source before all other entries, then retains the existing
directory-before-name comparator for the remaining entries.

The Session folder is present only in the existing-session Projects manifest, so
the precedence applies to the intended Projects root list. No filtering exception
is introduced: browser search continues to remove unmatched roots. Entries that
are not `session_folder`, including registered Projects and Git worktrees, retain
their current relative ordering. All-files entries use the existing `workspace`
source and therefore retain their current ordering.

### Root-row supporting path

`FileBrowser` recognizes `session_folder` as a root type that displays its
manifest path as supporting text. It preserves the existing Session files name
instead of replacing it with the path basename. The existing flexible row layout
keeps the name visible and allows the supporting path to truncate. The path text's
existing `title` attribute remains the full exact-path affordance.

### Storybook coverage

The existing workspace-panel Projects story adds a static Session files entry with
an exact working-folder path before Project and Git-worktree roots. This makes the
ordering and supporting-path state reviewable without a live API or Runtime.

## Interfaces and Contracts

No public API, generated client, database, event, persistence, lifecycle,
permission, or configuration contract changes. The existing `WorkspaceEntry`
mapping continues to consume `source.type = "session_folder"` and the supplied
`path`.

## Security and Permission Boundaries

This frontend-only display change does not modify manifest capabilities or
filesystem operations. Backend capability enforcement and the existing protected
Session-folder root behavior remain authoritative.

## Migration, Rollout, and Rollback

No migration or staged rollout is required. Rollback consists of reverting the
frontend presentation change; the backend manifest contract and Session-folder
data remain unchanged.

## Failure, Retry, and Recovery

Missing, unchecked, unavailable, and error status presentation remains unchanged.
Manifest refresh continues to replace the displayed root data; applying the
source-aware comparator after each refresh preserves Session files precedence when
the entry is included.

## Observability and Operational Risk

No new telemetry or operational control is required. The primary risk is a future
source type accidentally receiving Session-folder precedence; the comparator
matches only the explicit `session_folder` value.

## Requirement and ADR Traceability

| Requirement or ADR | Design mechanisms | Primary verification |
| --- | --- | --- |
| `session-260804/REQ-1` | Source-aware Session-folder-first comparator | Static UI test or story evidence with Session files, registered Project, and Git worktree roots |
| `session-260804/REQ-2` | Session-folder root supporting-path predicate and existing truncation/title layout | Story evidence at normal and constrained viewport widths |
| `session-260804/ADR` | Manifest-owned identity and path, no interface change | Typecheck and review of mapped entry usage |

## Test Strategy

### E2E primary verification matrix

| Journey | Required evidence |
| --- | --- |
| Active Session with registered Projects | Projects view lists Session files first and shows the exact manifest path. |
| Manifest refresh | Session files remains first after refreshed statuses or root data. |
| Narrow viewport | Session files name remains visible, path truncates when necessary, and the full path remains in the row title. |
| Search and All files mode | Unmatched Session files remains filtered by search; All files ordering is unchanged. |

### E2E plan

The existing Project Browser deterministic E2E journey is the primary product-level
verification target when its fixture can create an active Session with registered
Projects. It should assert the root order and supplied Session path from the
rendered Projects browser, then assert the existing search and All files behavior.

### Lower-level verification and fixtures

Add or update static WorkspacePanel Storybook data with Session files, a registered
Project, and a Git worktree root. The change is a pure presentation adjustment;
the static story is the focused review fixture and TypeScript validation protects
the existing manifest mapping. No new testenv seed, external credential, Runtime,
or generated client prerequisite is required.

### Evidence, CI, and skip policy

Run `pnpm run format`, `pnpm run lint`, and `pnpm run typecheck` from
`typescript/`. CI must run the repository's normal Web and deterministic E2E
checks. An unavailable local browser harness does not waive CI E2E evidence.

## Alternatives and Non-Blocking Risks

Reordering the server manifest is rejected because it already provides the required
precedence and cannot prevent the frontend's later generic sort. Constructing a
Session path in the browser is rejected because the server-owned manifest already
supplies the exact context-owned path.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- |
| M1 | Preserve the included Session files root before other Projects entries in frontend sorting. | `session-260804/REQ-1` | `required` |
| M2 | Render the supplied Session files path as root-row supporting text while retaining the existing truncation and full-path title behavior. | `session-260804/REQ-2` | `required` |
| M3 | Keep manifest identity, path authority, API contracts, search filtering, and All files ordering unchanged. | `session-260804/REQ-1`, `session-260804/REQ-2`, existing Workspace specification | `derived` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Generic root sorting that can place Session files after Project roots | `session-260804/REQ-1` | Source-aware Session-files-first comparator | `FileBrowser` entry sorting only | Static fixture shows Session files before registered Project and Git worktree roots |
| Project-root-only supporting-path predicate | `session-260804/REQ-2` | Session-folder-inclusive supporting-path predicate | `FileBrowser` root-row display only | Static fixture renders the exact Session path while registered Project rendering remains unchanged |
| API, generated clients, persistence, and backend manifest ordering | None; repository-grounded analysis finds no removal obligation | Existing behavior | None | Diff contains no change in those surfaces |

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: 2026-08-04
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`
- Approved scope: Preserve Session files first in Projects ordering, render its
  manifest-provided working-folder path, and leave manifest ownership, APIs,
  persistence, search filtering, and All files ordering unchanged.
