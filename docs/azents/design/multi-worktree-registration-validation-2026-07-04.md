---
title: "Multi-Worktree Registration Validation Report"
created: 2026-07-04
tags: [backend, frontend, runtime, session, workspace, git, validation]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/multi-worktree-registration-validation-2026-07-04.md"
---

# Multi-Worktree Registration Validation Report

## Scope

This report validates the implementation stack for [Multi-Worktree Registration](multi-260704-multi-worktree-registration.md) through Phase 4:

- `Multi-worktree registration [3/7]: Backend queue and API`
- `Multi-worktree registration [4/7]: Project panel worktree attach UI`

The feature goal is to let an existing session register multiple Azents-owned Git worktree Projects by appending worktree-specific step groups to the session initialization lifecycle and processing them as one sequential queue.

## Environment Snapshot

| Area | Evidence |
| --- | --- |
| Repository | `azents/azents` |
| Validation branch | `feature/multi-worktree-registration-validation` |
| Base stack head | `feature/multi-worktree-registration-ui` at `e92b10a67b5d0ce7281934e52cc329f7511ad27f` |
| Backend stack head | `feature/multi-worktree-registration-backend` at `cb977c594a2dd1dbdf8d0675b4d74247543cd7cf` |
| Local Python project | `python/apps/azents` |
| Local TypeScript project | `typescript` |
| Runtime-backed browser fixture | Not available in this validation runtime. Runtime-dependent browser evidence is recorded as a prerequisite gap; backend/API coverage and CI lanes provide the required automated evidence for this phase. |

## Local Validation Commands

| Command | Working directory | Result |
| --- | --- | --- |
| `uv run pyright` | `python/apps/azents` | Passed: `0 errors, 0 warnings, 0 informations` |
| `uv run pytest src/azents/repos/session_initialization/repository_test.py src/azents/services/session_git_worktree/service_test.py src/azents/api/public/chat/v1/chat_api_test.py src/azents/services/agent_session_input_test.py src/azents/services/chat/team_session_test.py -q` | `python/apps/azents` | Passed locally for available tests: `31 passed, 39 skipped, 3 warnings` |
| `pnpm run lint --filter=@azents/web` | `typescript` | Passed |
| `pnpm run typecheck --filter=@azents/web` | `typescript` | Passed |
| `pnpm run build --filter=@azents/web` | `typescript` | Passed |
| `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | repository root | Passed |
| `git diff --check` | repository root | Passed |

The skipped local Python tests are fixture-dependent in this runtime. GitHub CI for the implementation PRs ran the normal backend and E2E lanes successfully, including `ci-python-run (python/apps/azents)` and `ci-python-e2e-run` for the backend/API PR.

## GitHub CI Evidence

| PR | Scope | Head | CI evidence |
| --- | --- | --- | --- |
| #171 | Design | `1c167e94d27db0a8c58abd4cca2ea5e34f9d8d6b` | All required checks passed in run `28698480177`; scoped run checks that did not apply were skipped. |
| #172 | Implementation plan | `6244918650e6277b680371d41439c6a036e8d82f` | All required checks passed in run `28698553074`; scoped run checks that did not apply were skipped. |
| #173 | Backend queue and API | `cb977c594a2dd1dbdf8d0675b4d74247543cd7cf` | All required checks passed in run `28702250096`, including backend, E2E, TypeScript, Helm, and Docker build aggregates. |
| #174 | Project panel worktree attach UI | `e92b10a67b5d0ce7281934e52cc329f7511ad27f` | All required checks passed in run `28702250843`, including TypeScript and Docker build aggregates; backend run lanes were skipped because this PR is frontend-scoped. |

All four open PRs were rechecked after the final backend fix. Their merge state was `CLEAN` at validation time.

## Behavior Validation Matrix

| Behavior | Implementation evidence | Result |
| --- | --- | --- |
| Attach first worktree to existing session | API route `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/git-worktrees`, service allocation creation, scoped initialization step append, generated public clients, and API tests. | Validated by backend/API tests and CI. |
| Attach second worktree to same session | `session_git_worktrees` unique `session_id` constraint removed; repository lists multiple allocations; service test covers second registration while preserving the first ready allocation. | Validated by service tests and CI. |
| Sequential queue | Worktree-specific step keys include `worktree_id`; service processes pending worktree groups in step sequence order. | Validated by service queue tests and CI. |
| Run gate while updating workspace | Attach marks initialization pending/running while blocking worktree steps remain; run dispatch waits for initialization ready. | Validated by backend service/input tests and CI. |
| Failure path | Invalid Git ref failures record initialization failure and keep input pending; no registered Project row is created for failed allocation. | Validated by service tests and CI. |
| Existing-session Project panel attach flow | UI adds the worktree attach action, ref preview state, attach mutation, loading/failure states, query invalidation, and Storybook states. | Validated by TypeScript lint/typecheck/build and CI Docker build. |
| Archive cleanup authority | Cleanup iterates all session-owned worktree allocations while retaining `session_git_worktrees` as destructive cleanup authority. | Validated by service tests and CI. |

## Runtime Fixture and Browser Evidence

The validation runtime did not provide a ready browser E2E fixture with a live Agent Runtime and Git repository. Because of that, this report does not include a live UI screenshot or DOM assertion for the Project panel.

Automated evidence still covers the feature contract through:

- backend service/API tests for allocation, queueing, run gating, failure, and cleanup behavior;
- generated client and tRPC compile-time coverage;
- Storybook states for the UI surface;
- TypeScript lint/typecheck/build;
- GitHub CI backend, frontend, Docker build, Helm, and E2E lanes.

If a ready runtime/browser fixture becomes available before merge, an optional follow-up validation can capture:

1. a created session ID;
2. the first and second worktree allocation IDs;
3. the final registered Project paths;
4. initialization status transitions from `pending`/`running` to `ready`;
5. a Project panel screenshot or DOM assertion showing both worktree Projects.

## Implementation vs Current Spec Comparison

| Topic | Implemented behavior | Current spec status | Phase 6 action |
| --- | --- | --- | --- |
| Existing-session worktree attach API | New endpoint attaches an Azents-owned worktree to an existing session. | `conversation.md` and `workspace.md` list existing Project registration and new-session worktree behavior, but do not yet fully promote the existing-session attach endpoint. | Add route and behavior to living specs. |
| Multiple worktree allocations per session | A session may own multiple `SessionGitWorktree` rows. | Specs still emphasize session-owned worktree cleanup and new-session worktree behavior; the multi-row invariant needs explicit promotion. | Update domain specs and relationship language. |
| Initialization as sequential workspace queue | Appended worktree-specific step groups reuse the session initialization lifecycle. | `agent-execution-loop.md` states the run gate waits for blocking initialization, but does not yet describe existing-session workspace updates as appended queue work. | Update flow spec. |
| Project panel worktree attach UI | Existing Project panel supports `New worktree` using ref preview and attach mutation. | `workspace.md` covers Project browser behavior but not this new UI action. | Update workspace spec. |
| Runner Git operation contract | Existing typed `list_git_refs`, `create_git_worktree`, `remove_git_worktree`, and `delete_git_branch` operations are reused. | `agent-runtime-control.md` already covers the typed Git operation contract. | Confirm `last_verified_at` only if no wording change is needed. |

## Validation Conclusion

The implementation stack through Phase 4 satisfies the planned backend/API and frontend validation gates available in this environment. The remaining work is Phase 6 spec promotion, followed by Phase 7 cleanup of stale implementation-plan artifacts after specs become the current source of truth.
