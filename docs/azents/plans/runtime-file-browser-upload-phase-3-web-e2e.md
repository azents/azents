---
title: "Runtime File Browser Upload Phase 3 Web E2E"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, frontend, e2e, implementation, phase-plan]
---

# Runtime File Browser Upload Phase 3 Web E2E

## Phase Execution Plan

- Phase: `3/3 — Web direct upload, E2E, Specs, and cleanup`
- Branch/base: `feat/upload-260917-3-web-e2e` → `feat/upload-260917-2-public-api`
- PR boundary: `Deliver the browser direct-upload experience, end-to-end evidence, current Specs, and plan cleanup`
- Inputs: `Phase 2/3 complete; approved fileupload-260917/DESIGN revision 1`
- Deliverables: `Generated-client JSON control calls; bounded worker SHA-256; cancellable progress-capable presigned PUT; FileBrowser picker/tray/conflict/cancel/retry; directory invalidation; four-locale messages; Storybook/component coverage; required direct PUT/finalize/direct GET E2E; Spec promotion; implemented dates; plan removal`
- Non-goals: `New backend authority, Main Web binary proxy, application file-body relay, browser reload resume, directory/archive upload, Exchange fallback`
- Interfaces: `Phase 2 generated create/finalize/status/cancel/retry functions; required signed headers; upload UI ADT; FileBrowser/FileBrowserContainer props; localized workspacePanel keys; E2E prerequisite contract`
- Approved Design mechanisms: `M2, M4, M5, M6, M8, M9, M11, M12, M13, M14`
- Authority references: `fileupload-260917/REQ-1` through `REQ-6`; `fileupload-260917/ADR-D2` through `D9`; current Workspace, Runtime Control, Runtime Provider, and File Exchange Specs; Phase 2 interfaces`
- Design delta: `None`
- Removal obligations: `Remove old upload-260917/workspaceupload-260917 implementation plans and obsolete UI/proxy assumptions after validation; remove all feature plans after Spec promotion and implemented marking`
- Absence verification: `Browser network evidence shows File body goes directly to S3; no Main Web/API body proxy, hidden Exchange attachment, raw backend contract duplication, UI success before Runtime commit, or fallback transport`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Browser checksum and direct PUT | Root agent | `typescript/apps/azents-web/src/features/chat/workspace/**`, worker/helper tests | Phase 2 ticket | Bounded SHA-256, signed headers, progress, abort, finalize call | Unit/component tests, typecheck/lint |
| Workspace panel UI | Root agent | Workspace components, containers, types, stories | Direct PUT state | Per-file queued/uploading/finalizing/moving/success/failure/conflict/cancel/retry UI | Storybook play and component tests |
| Localization | Root agent | `messages/{en-US,fr-FR,ja-JP,ko-KR}/**`, composition | UI copy | Natural aligned labels/errors/actions | Message parity tests |
| E2E fixtures and journeys | Root agent | `testenv/azents/e2e/**`, object-store/runtime fixtures | Backend + Web | Real browser direct PUT, immutable finalize, Runner direct GET, network modes, failure matrix | Required API/Web E2E and captured evidence |
| Specs and final cleanup | Root agent | `docs/azents/spec/**`, final snapshot frontmatter, `docs/azents/plans/**` | Stable validated feature | Current behavior Specs, matching implemented date, plan removal | spec-review, docs validator/index, authority audit |
| Integrated validation | Root agent | All phase paths | All workstreams | Frozen final feature diff | TypeScript/Python/E2E/spec matrix and absence proof |

- Integration order: `checksum/direct PUT transport → UI state/components → localization/stories → E2E fixtures/journeys → integrated fixes → Spec promotion and implemented marking → plan cleanup`
- Independent review: `fileupload-reviewer; root requests the final read-only review after integrated E2E, Spec updates, authority/removal audit, and stable diff`
- Final validation: `TypeScript format/lint/typecheck/build/tests; Storybook interaction tests; required browser E2E for direct PUT/finalize/direct GET, exact-byte download, cancellation, conflict/re-conflict, retry, generation fencing, URL expiry, no-network/proxy-required, empty Redis, cleanup; Python regression as affected; spec-review; docs validator/index; git diff --check`
- Scope-drift check: `Only M2/M4/M5/M6/M8/M9/M11/M12/M13/M14; no new product behavior, persistence authority, fallback, endpoint mode, or backend mechanism`
- Context checkpoint: `Record browser/network evidence, exact-byte and failure results, all-network-mode prerequisite evidence, Spec promotion, implementation date, plan cleanup, reviewer result, removal absence proof, and Design delta None`
