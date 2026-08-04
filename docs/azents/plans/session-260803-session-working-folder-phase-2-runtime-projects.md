---
title: "Session Working Folder Phase 2 Execution Plan"
created: 2026-08-03
updated: 2026-08-03
tags: [session, workspace, runtime, projects, api, web]
---

# Phase Execution Plan

- Phase: `2 — Runtime Default and Projects UX`
- Branch/base: `feat/session-working-folder-2-runtime-projects` → `feat/session-working-folder-1-context-setup`
- PR boundary: Make the persisted Session working folder the default only for omitted Runtime command workdirs; expose and protect the Session folder in the active Session Projects experience; add explicit setup retry.
- Inputs: Phase 1 context persistence, pathless setup action, mailbox/action projections, and generated public action response contract from `133da4151`.
- Deliverables:
  - Runtime prompt guidance that distinguishes the Session folder, registered Projects, Agent Workspace, and temporary locations;
  - exact stored-path substitution only when `exec_command.workdir` is omitted, with explicit workdir precedence;
  - first, backend-owned `session_folder` Project Browser entry with current Runner-derived visibility/status and `prepare_session_folder` capability;
  - authenticated active-root retry route that queues the pathless setup action, wakes the Session, and accepts no path;
  - root/ancestor/destination-overwrite/bulk mutation protection for non-purged Session folder roots and the dedicated delete tool;
  - generated public clients and Web support for the new manifest and retry contracts.
- Non-goals:
  - worktree allocation or cleanup-path changes (`M7`);
  - archive folder deletion, cleanup state transitions, or Runner lexical delete changes (`M8`, `M9`);
  - contract migration, E2E promotion, current-Spec promotion, or plan cleanup (Phase 4);
  - Runtime-reset coordinator, automatic retries, physical-state persistence, or Session-folder Project registry rows.
- Interfaces:
  - `SessionAgentContext.working_folder_path` remains the sole path authority; no request/action payload supplies a target path;
  - omitted `exec_command.workdir` resolves to the stored context path, while every explicit workdir remains unchanged;
  - active-session manifest adds source `session_folder` and capability `prepare_session_folder`; previews remain Project-only;
  - retry returns the existing accepted mailbox/action projection and requires active-root Session authorization;
  - protected-root checks reject deleting/moving/overwriting the root or required ancestors before mutation, but retain descendant operations.
- Approved Design mechanisms: `M4`, `M5`, `M6`, and explicit retry from `M10`.
- Authority references: `session-260803/REQ-2`, `REQ-3`, `REQ-4`, `REQ-6`, `REQ-7`; `session-260803/ADR-D2`, `ADR-D4`; approved Design revision 1 and implementation-plan Phase 2.
- Design delta: `None`
- Removal obligations:
  - replace ordinary-output Runtime guidance and omitted-command default of `/workspace/agent` with the exact Session-folder default plus distinct Agent Workspace guidance;
  - replace active-session empty/Project-only manifest semantics with a first fixed Session entry without creating a Project row;
  - replace Agent-Workspace-only mutation protection with Session root and ancestor/destination protection.
- Absence verification:
  - prompt snapshots and Runtime tests prove explicit workdir precedence and no omitted-workdir fallback to a derived path;
  - active Session manifests always start with `session_folder`, preview manifests have none, and no Session-folder registry row exists;
  - public write tests prove retry accepts no path and user-authored action schemas still exclude the system action;
  - root, ancestor, overwrite, bulk, and dedicated-delete tests reject protected operations while descendant operations remain allowed;
  - no worktree-placement, archive-cleanup, delete-resolution, contract-migration, or reset-coordinator code appears in the diff.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime default and guidance | `/root` | `python/apps/azents/src/azents/engine/tools/{builtin.py,builtin_test.py,runtime_io.py}`; Runtime prompt/context construction and focused tests | Phase 1 stored context projection | Four-category guidance; stored-path omitted-workdir default; explicit-workdir precedence; explicit `/workspace/agent` repair guidance | Prompt/tool tests, Runner argument assertions, Ruff, Pyright |
| Project manifest and retry API | `/root` | `python/apps/azents/src/azents/services/project_browser_manifest{,_test}.py`; `python/apps/azents/src/azents/api/public/chat/v1/{__init__.py,data.py,data_contract_test.py,chat_api_test.py}`; `python/apps/azents/src/azents/services/{chat,mailbox}.py` and focused tests | Phase 1 action and context path | `session_folder` entry, status/capability projection, authorized retry enqueue/wake | Manifest/API/auth/order/retry tests, OpenAPI/client generation |
| Protected filesystem mutation | `/root` | `python/apps/azents/src/azents/services/chat/{workspace.py,workspace_test.py}`; relevant public chat API routes/tests; `python/apps/azents/src/azents/engine/tools/{delete_file.py,delete_file_test.py}` | Stored context projection | Root/ancestor/destination/bulk guards with descendant preservation | Direct service/API/delete-tool tests including atomic bulk rejection |
| Web Projects and action-state UX | `/root` | `typescript/apps/azents-web/src/features/chat/workspace/{types.ts,containers/useWorkspacePanelContainer.ts,components/ProjectPanel.tsx,components/WorkspacePanel.tsx,components/FileBrowser.tsx}`; chat action presentation/hooks/stories/tests | Generated public client and manifest/retry contracts | First system entry, disposable lifetime/status, capability-gated retry, disabled root controls, non-human system action state, post-action refresh | TypeScript format/lint/typecheck, component/pure-state tests, stories and responsive review |
| Generated contracts and integration | `/root` | public OpenAPI; `python/libs/azents-public-client/**`; `typescript/packages/azents-public-client/**`; phase plan | All backend contract changes | Regenerated public clients, stable integration evidence | OpenAPI dump, generators, generated-client checks, `git diff --check` |

- Integration order:
  1. Load the stored context in the Runtime prompt/tool path and add explicit versus omitted workdir tests before changing the default.
  2. Extend the manifest/domain/public response with the fixed Session entry and Runner-derived status; retain preview behavior unchanged.
  3. Add retry authorization/enqueue/wake with a retry-scoped deterministic key and no path input; prove action state is not a human bubble.
  4. Centralize protected-root resolution in workspace mutation and dedicated delete boundaries; prove all bulk checks run before side effects.
  5. Regenerate OpenAPI and public clients, then wire Web types, Project panel state, retry, root controls, and terminal-action refresh.
  6. Run focused backend/client/frontend validation and audit removal/absence obligations.
- Independent review:
  - Exact reviewer: GitHub reviewer `hardtack`.
  - Scope: complete Phase 2 diff against `M4`, `M5`, `M6`, explicit retry from `M10`, this plan, and the approved snapshot.
  - Criteria: stored path is loaded rather than derived; explicit workdir wins; prompt has four storage categories and repair guidance; no Session Project row; Session entry is first only for active manifests; retry is authenticated/pathless/waking/idempotent; setup state is observational; all protected mutation forms reject before I/O while descendants work; Web never renders setup as a user bubble; later destructive behavior is absent.
  - Inputs: approved Requirements/ADR/Design, Phase 1 PR, this plan, stable diff, generated artifacts, and validation output.
  - Output: grounded Critical/Warning findings or explicit approval.
- Final validation:
  - focused Runtime prompt/tool, manifest, chat API, workspace mutation, dedicated-delete, mailbox/action projection, and authorization tests;
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`;
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`;
  - `cd python/apps/azents && uv run pyright`;
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`;
  - public Python and TypeScript client generation plus generated-client checks;
  - `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck --filter=@azents/web --filter=@azents/public-client`;
  - focused Web tests/stories and required browser evidence;
  - `python -m pytest scripts/tests/test_gen_docs_index.py -q` and `git diff --check`.
- Scope-drift check:
  - Verify every deliverable maps to `M4`, `M5`, `M6`, or explicit retry from `M10`.
  - Remove any path derivation, request path field, Project-row authority, physical-state enum, automatic retry/reset coordinator, worktree relocation, archive deletion, symlink deletion change, migration contract tightening, or Spec promotion.
  - Return to feature design if implementation requires a new retry mode, ownership source, fallback path, action admission gate, destructive scope, or public contract outside the approved interfaces.
- Context checkpoint:
  - Record Runtime prompt/workdir evidence, manifest/retry schema and generated-client changes, root-protection and Web state evidence, independent-review result, validation commands, remaining Phase 3 inputs, risks, and blockers.
