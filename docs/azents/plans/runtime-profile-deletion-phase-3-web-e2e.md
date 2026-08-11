---
title: "Runtime Profile Deletion Phase 3 Web and E2E"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, profile, deletion, web, e2e]
---
## Phase Execution Plan

- Phase: `3 - Owner deletion Web UX and Docker-backed E2E`
- Branch/base: `feature/runtime-profile-deletion-web` → `feature/runtime-profile-hard-delete`
- PR boundary: Add an owner-only permanent-delete workflow to the Workspace Runtime Profile management surface, communicate irreversible selection and Runtime continuity effects, report exact committed impact counts, handle stale/not-found/authorization failures without losing page context, and prove deletion plus retention semantics through the deployed Web surface and official Public API in the Docker-backed E2E lane.
- Inputs: Confirmed `profile-260811/REQ`, accepted `profile-260811/ADR`, approved `profile-260811/DESIGN` revision 1, baseline PR #1258, current-state PR #1259, and hard-delete API/generated-client PR #1260.
- Deliverables:
  - generated-public-client-backed tRPC delete mutation with exact version fencing and bounded expected-error mapping;
  - owner-only row-local delete action while existing Manager/Owner editing and recreation authority remains unchanged;
  - destructive confirmation modal requiring the exact Profile name and an explicit irreversible-action acknowledgement;
  - confirmation copy explaining that matching Workspace default and Agent selections are cleared without fallback, existing running Runtime applied state and Workspace storage remain, and replacement selection is required for configuration-dependent recovery;
  - success feedback containing committed default, Agent, running Runtime, and recreation-operation impact counts;
  - stale conflict, not-found, authorization, and generic failure presentation that keeps the current page and confirmation context recoverable;
  - Storybook interaction coverage for owner/non-owner, confirmation gating, success, conflict, and failure states;
  - Docker-backed deployed-Web E2E that creates a Profile through the official Public API, deletes it through the owner UI, and verifies Profile absence, default/Agent selection clearing, no fallback, retained running Runtime applied state, and retained Workspace storage through official product surfaces.
- Non-goals: Backend deletion semantics, new API contracts or generated-client edits, deletion preview/count endpoint, Manager deletion authority, automatic replacement Profile selection, Runtime restart/recreation during deletion, applied-state or Workspace deletion, Kubernetes fixture expansion, Living Spec promotion, deployment, compatibility behavior, or plan cleanup.
- Interfaces:
  - `runtimeProfile.delete` accepts `handle`, `profileId`, and positive `expectedVersion`, calls `runtimeProfileV1DeleteWorkspaceRuntimeProfile`, and returns `WorkspaceRuntimeProfileDeleteResponse`;
  - expected HTTP mappings are `401 → UNAUTHORIZED`, `403 → FORBIDDEN`, `404 → NOT_FOUND`, `409 → CONFLICT`, and `422 → BAD_REQUEST`;
  - `canManage` remains Owner-or-Manager for create/edit/default/recreate while a distinct `canDelete` is true only for Workspace Owner;
  - successful deletion invalidates both the Runtime Profile list and Workspace default queries and closes the confirmation only after committed result data is captured;
  - the confirmation modal receives one immutable Profile snapshot, requires exact case-sensitive display-name input plus explicit acknowledgement, disables destructive submission while invalid or pending, and restores keyboard focus through Mantine modal behavior;
  - no pre-delete numeric estimate is fabricated: the modal communicates contract-defined effects, and the server response supplies exact committed impact counts after success;
  - E2E setup and assertions use official generated API clients and the deployed Web UI, with no direct database writes.
- Approved Design mechanisms: `M1`, `M4`, `M6`, `M8`
- Authority references: `profile-260811/REQ-1`, `REQ-2`, `REQ-3`, `REQ-7`, `REQ-8`; `profile-260811/ADR-D3`, `ADR-D4`, `ADR-D6`; `profile-260811/DESIGN` Runtime Profile Hard Delete, Runtime behavior after deletion, API/Generated Clients/UI, Failure/Retry/Recovery, and Test Strategy; current Workspace, Agent, Runtime Control, and Runtime Persistence Specs; TypeScript Container/Component/Page, ADT state, generated-client, cache-invalidation, localization, Storybook, and testenv no-direct-DB-write conventions.
- Design delta: `None`
- Removal obligations:
  - expose permanent deletion rather than disable/archive/tombstone/fallback behavior;
  - remove no applied Runtime state or Agent Workspace storage during the Web workflow;
  - add no raw HTTP path, hand-written generated contract, or Manager-visible deletion affordance;
  - retain no stale deleted Profile in selectable/default UI state after successful invalidation.
- Absence verification: Active Web source search for raw DELETE URLs and archive/tombstone/fallback deletion substitutes; role-state stories proving Managers lack delete UI; generated-client import inspection; post-delete Storybook/E2E assertions that the Profile is absent from management/default choices and no substitute selection appears; API assertions that the deleted Profile is not returned while retained Runtime/Workspace evidence remains.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| tRPC delete adapter | `root` | `typescript/apps/azents-web/src/trpc/routers/runtime-profile.ts` | PR #1260 generated TypeScript client delete operation | Typed delete mutation and bounded expected-error mapping | Typecheck plus focused adapter inspection/tests where existing router harness permits |
| Container state and authorization | `root` | `typescript/apps/azents-web/src/features/runtime-profiles/containers/useRuntimeProfilesContainer.ts`, `types.ts` | Workspace member role query, tRPC mutation, cache utilities | Distinct Owner-only delete authority, confirmation/result ADTs, callbacks, invalidation | Typecheck and component interaction stories for owner/manager and all mutation states |
| Pure deletion UI | `root` | `typescript/apps/azents-web/src/features/runtime-profiles/components/RuntimeProfiles.tsx` and a colocated confirmation component if separation improves clarity | Container output contract and existing Mantine management table | Row-local destructive action, accessible confirmation, effect copy, pending/success/conflict/error feedback | Storybook interaction tests, keyboard/disabled-state assertions, focused visual inspection |
| Localization and stories | `root` | `typescript/apps/azents-web/messages/*.json`, `RuntimeProfiles.stories.tsx` | Stable UI state contract | Natural localized copy and static fixtures for meaningful states | Locale JSON parse/format, Storybook tests for owner/non-owner, modal, success, conflict, failure |
| Docker-backed Web E2E | `root` | `testenv/azents/e2e/src/support/runtime_profiles.py`, `src/tests/azents/public/test_runtime_profiles.py` or the nearest existing Runtime Web module | Deployed Main Web, Docker Runtime Provider fixture, official Public/Admin clients | API-created selected/default running Runtime Profile deleted through UI with product-surface absence and retention assertions | Focused `pytest -m web_surface` selection after fixture doctor/up, logs/trace on failure |
| Scope and absence evidence | `root` | Phase-owned sources and validation output | Stable integrated diff | Evidence of Owner-only authority, no fallback/archive/tombstone/raw HTTP, and retained Runtime/Workspace state | Targeted source searches, `git diff --check`, pre-commit |

- Integration order: Add the generated-client tRPC mutation → define deletion/feedback ADTs and separate `canDelete` authority → implement confirmation and row action → add localized copy and static interaction stories → extend product E2E setup/assertions → run focused Web checks and smallest Docker E2E → correct defects → run stable-diff review and final validation.
- Independent review: `hardtack` reviews the stable Phase 3 diff read-only against confirmed Requirements, accepted ADR, approved Design revision 1, PR #1260 interfaces, current Specs, and this plan. Criteria are Owner-only destructive authority, exact-version use, no Manager affordance, explicit irreversible/name confirmation, accurate effect and result communication, page-context-preserving recovery, accessibility, generated-client/cache conventions, no fallback/archive/tombstone, and E2E proof of deletion with running Runtime and Workspace retention. Output is one consolidated review with required findings separated from optional polish.
- Final validation:
  - from `typescript/`: focused Prettier, ESLint, TypeScript typecheck, and `@azents/web` build using repository scripts; focused Storybook test execution for Runtime Profile stories;
  - from `testenv/azents/`: bootstrap/prerequisite preparation and fixture readiness checks required by the selected Docker Web fixture, followed by the smallest focused Runtime Profile deletion E2E with logs and browser trace retained on failure;
  - locale JSON validation, targeted active-source absence searches, `git diff --check`, and all pre-commit hooks on the stable diff.
- Scope-drift check: Confirm complete Phase 3 coverage of `M1`, `M4`, `M6`, and `M8`; confirm the diff adds no backend/API schema, preview-count endpoint, Manager deletion, fallback/replacement automation, Runtime termination/recreation, applied-state cleanup, Workspace reset, Kubernetes prerequisite policy, Living Spec edits, deployment action, compatibility path, or new material mechanism.
- Context checkpoint: PR #1260 supplies the owner-authorized, exact-version hard-delete operation and generated request/response contracts. This phase consumes that contract without changing it. The Web currently grants Owner-or-Manager general management authority, so deletion requires a separate Owner-only capability. Exact numeric impact is known only after the atomic delete response; the confirmation therefore states guaranteed effects and the success result reports committed counts. Remaining phases own repository-wide integrated validation, Living Spec promotion, snapshot implementation metadata, and plan cleanup. Main risks are destructive-action gating, stale-version recovery, reliable deployed-Web selectors, and proving retained running Runtime/Workspace state without direct database access; no material Design blocker is known.
