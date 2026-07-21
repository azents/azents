---
title: "Session Workspace Project Contract Historical Requirements Reconstruction"
created: 2026-05-09
implemented: 2026-05-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: projects-260509
historical_reconstruction: true
migration_source: "docs/azents/design/session-workspace-projects.md"
---

# Session Workspace Project Contract Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `projects-260509`
- Source: `docs/azents/design/projects-260509-projects.md`
- Historical source date basis: `2026-05-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This document organizes Session Workspace / Project contract finalized in #3367 and Discussion #3541 into implementable form. Terminology cleanup (#3532) is assumed to proceed in separate session, and this document uses following definitions.

- **Workspace**: top-level unit of NoIntern service. Space where users create agents and collaborate.
- **Session Workspace**: storage space where Agent works in a session. Current root is `/home/sandbox`.
- **Project Source**: reusable source uploaded to Workspace that Agent can load as Project. MVP supports only archive upload.
- **Project**: actual result of a Project Source or empty-folder request being loaded into specific Agent's Session Workspace. DB row tracks load request and status, but Project injected into prompt is only row with `loaded=true`.

Goal is to keep `/home/sandbox` as Agent long-term workspace, but limit active configuration discovery scope, such as `AGENTS.md` and future skills, to registered Projects. Detailed AGENTS.md load method and hook system are separated into #3542.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. Each Agent has long-term Session Workspace root.
   - root is `/home/sandbox`.
   - Agent stores important data and files for continued use under this path.
2. `/home/sandbox` can contain multiple work folders.
   - git repository, normal folder, and artifact folder can coexist.
   - One Agent manages multiple repos and work folders long-term.
3. Explicitly designated long-term work folder is called Project.
   - `/home/sandbox` itself is not a Project.
   - project-scoped active configuration is discovered/loaded only inside folder designated as Project.
4. User can upload archive as Project Source and repeatedly load it into multiple Agents in same Workspace.
5. User can request loading Project Source archive or empty folder as Project during Agent creation or active Agent UI/API.
6. Agent can request user to register specific folder as Project through tool.
7. If Project folder is deleted from filesystem, it is also removed from Project registry.
8. Git repository source is enabled in follow-up phase that introduces Temporal-based external ingest. MVP public API supports only archive upload and empty folder.

## Supporting Scenarios

1. Each Agent has long-term Session Workspace root.
   - root is `/home/sandbox`.
   - Agent stores important data and files for continued use under this path.
2. `/home/sandbox` can contain multiple work folders.
   - git repository, normal folder, and artifact folder can coexist.
   - One Agent manages multiple repos and work folders long-term.
3. Explicitly designated long-term work folder is called Project.
   - `/home/sandbox` itself is not a Project.
   - project-scoped active configuration is discovered/loaded only inside folder designated as Project.
4. User can upload archive as Project Source and repeatedly load it into multiple Agents in same Workspace.
5. User can request loading Project Source archive or empty folder as Project during Agent creation or active Agent UI/API.
6. Agent can request user to register specific folder as Project through tool.
7. If Project folder is deleted from filesystem, it is also removed from Project registry.
8. Git repository source is enabled in follow-up phase that introduces Temporal-based external ingest. MVP public API supports only archive upload and empty folder.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
