---
title: "Codex-first Subagent Prerequisites Validation Report"
created: 2026-07-08
updated: 2026-07-08
tags: [backend, engine, toolkit, documentation]
---
# Codex-first Subagent Prerequisites Validation Report

## Summary

This report validates the prerequisite stack for the Codex-first subagent redesign against [ADR-0096](../adr/0096-codex-first-subagent-redesign.md), the implementation design, and the prerequisite implementation plan.

The prerequisite stack is intentionally limited to foundations. It does not expose child `SessionAgent` creation, model-visible subagent collaboration tools, Subagent Tree APIs, or frontend subagent UI.

## Validation Scope

Validated commits and PRs:

| PR | Commit | Scope |
| --- | --- | --- |
| #237 | `24320d9` | Session input producer and wake boundary cleanup |
| #238 | `fdd9310` | Toolkit taxonomy and execution-mode filter groundwork |
| #239 | `ecf9c20` | Head-bound context fork helper and FilePart placeholders |
| #240 | `ea707e1` | Root `SessionAgentContext` Project/worktree foundation |
| #241 | `a6599fd` | ADR/requirements mapping validation |
| #245 | `0c84410` | TurnAction turn-boundary gap fix |

## ADR and Requirements Mapping

| Source | Requirement | Expected code path(s) | Observed implementation | Status | Gap/fix PR |
| --- | --- | --- | --- | --- | --- |
| Prerequisite plan PR 2 | Keep `input_buffers` as internal pending model-input storage. | `python/apps/azents/src/azents/services/input_buffer.py`, `python/apps/azents/src/azents/rdb/models/input_buffer.py` | `InputBufferService.enqueue()` remains the low-level persisted input path. No public/model-visible input-buffer API was added. | Implemented | #237 |
| Prerequisite plan PR 2 | Low-level input buffer writer appends rows and returns created rows without owning broker wake-up. | `python/apps/azents/src/azents/services/input_buffer.py` | `InputBufferService.enqueue()` returns `InputBufferEnqueueResult`; wake-up decisions were removed from this low-level path. | Implemented | #237 |
| Prerequisite plan PR 2 | Move wake ownership to fixed producer/orchestrator boundaries. | `python/apps/azents/src/azents/services/agent_session_input.py`, `python/apps/azents/src/azents/services/chat_write.py`, `python/apps/azents/src/azents/worker/input/queue.py`, `python/apps/azents/src/azents/worker/session/idle_continuation.py` | User input, action input, chat write, queued worker input, background results, and idle continuations call `AgentSessionRepository.mark_running_for_input_wakeup()` at their owning boundary. | Implemented | #237 |
| Prerequisite plan PR 2 | Preserve current first-message, edit, TurnAction, goal/system continuation, live pending input, and broker wake behavior. | `python/apps/azents/src/azents/services/agent_session_input_test.py`, `python/apps/azents/src/azents/services/input_buffer_test.py`, `python/apps/azents/src/azents/worker/session/idle_continuation_test.py` | Focused tests cover wake marking, idempotency, continuation wake-up, and unchanged input buffer behavior. | Implemented | #237 |
| ADR-0086 / ADR-0094 | Process TurnActions at turn boundaries, not only at run-entry/run-complete boundaries. | `python/apps/azents/src/azents/worker/run/executor.py`, `python/apps/azents/src/azents/engine/events/execution.py`, `python/apps/azents/src/azents/worker/session/runner.py` | Model-call boundary polling now includes action-message promotion and operation-action execution. Context-invalidating actions cancel the current run without a completed run marker and enqueue a fresh wake-up; failed operation actions are marked failed and FIFO processing continues. | Implemented | #245 |
| Prerequisite plan PR 3 | Split memory auto-bound behavior into Memory Read and Memory Write capabilities. | `python/apps/azents/src/azents/engine/tools/builtin.py`, `python/apps/azents/src/azents/engine/run/resolve.py` | `MemoryReadToolkit` and `MemoryWriteToolkit` are resolved separately instead of one combined memory auto-bind capability. | Implemented | #238 |
| Prerequisite plan PR 3 | Add execution-mode filtering seam for future subagent mode without registering subagent tools. | `python/apps/azents/src/azents/core/tools.py`, `python/apps/azents/src/azents/engine/run/resolve.py` | `ToolkitExecutionMode` and `_allows_execution_mode()` route toolkit candidates through root/subagent allowlists. Worker execution still passes root mode. | Implemented | #238 |
| Prerequisite plan PR 3 | Keep Memory Read eligible for future subagent mode and Memory Write excluded from future subagent-mode auto-binding. | `python/apps/azents/src/azents/engine/run/resolve.py`, `python/apps/azents/src/azents/engine/run/resolve_test.py` | Memory Read uses root+subagent allowed modes; Memory Write remains root-only. Resolver tests assert the split. | Implemented | #238 |
| Prerequisite plan PR 3 | Keep Goal Toolkit root/user-facing and excluded from future subagent-mode auto-binding. | `python/apps/azents/src/azents/engine/run/resolve.py`, `python/apps/azents/src/azents/engine/run/resolve_test.py` | Goal Toolkit remains root-mode only in the resolver allowlist. | Implemented | #238 |
| Prerequisite plan PR 3 | Prepare runtime toolkit taxonomy around `runtime` without breaking current root-session behavior. | `python/apps/azents/src/azents/engine/tools/builtin.py`, `python/apps/azents/src/azents/engine/run/resolve.py` | Runtime file/process tools are represented by `RuntimeToolkit`, while current root sessions still receive the equivalent runtime-capability surface. | Implemented | #238 |
| Prerequisite plan PR 4 | Add reusable `fork_turns` parser for `none`, `all`, and positive integer strings. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/events/fork_context_test.py` | `parse_fork_turns()` accepts only the planned syntax and rejects malformed values before child creation can exist. | Implemented | #239 |
| Prerequisite plan PR 4 | Select fork range from current model-input head/compaction boundary. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/events/fork_context_test.py` | Fork selection operates on the head-visible transcript range and prevents pre-head durable history from being copied. | Implemented | #239 |
| Prerequisite plan PR 4 | Positive integer `fork_turns` selects latest N turns only inside current model-visible range. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/events/fork_context_test.py` | The helper applies the latest-turn count after the head-visible range is selected. | Implemented | #239 |
| Prerequisite plan PR 4 | Render forked ModelFile-backed FileParts as bounded text placeholders without copying blobs or creating child ModelFiles. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/events/fork_context_test.py` | FileParts degrade to metadata placeholders. The helper has no object-store copy or ModelFile creation path. | Implemented | #239 |
| ADR-0096 / design | Introduce `SessionAgent` as the live participant tree while keeping `AgentSession` as execution/transcript context. | `python/apps/azents/src/azents/rdb/models/session_agent.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | Root `SessionAgent` rows link one-to-one to `AgentSession`; `AgentSession` gains only `session_kind` and remains execution state owner. | Implemented | #240 |
| ADR-0096 / design | Add `agent_sessions.session_kind = root | subagent` for listing/filtering, not tree source of truth. | `python/apps/azents/src/azents/core/enums.py`, `python/apps/azents/src/azents/rdb/models/agent_session.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | `AgentSessionKind` is a DB enum; ordinary workspace/agent session lists filter to root sessions. | Implemented | #240 |
| Prerequisite plan PR 5 | Create root `SessionAgent` and `SessionAgentContext` transactionally for normal root sessions. | `python/apps/azents/src/azents/repos/agent_session/__init__.py` | Root session creation creates a context and root `SessionAgent` in the same DB transaction when `session_kind` is root. | Implemented | #240 |
| Prerequisite plan PR 5 | Move active Project registry ownership to `session_agent_context_projects`. | `python/apps/azents/src/azents/rdb/models/session_agent_context.py`, `python/apps/azents/src/azents/repos/session_workspace_project/__init__.py` | The existing Project repository API now reads/writes `RDBSessionAgentContextProject` via the session's root context. | Implemented | #240 |
| Prerequisite plan PR 5 | Move Azents-owned Git worktree allocation/cleanup authority to `session_agent_context_git_worktrees`. | `python/apps/azents/src/azents/rdb/models/session_agent_context.py`, `python/apps/azents/src/azents/repos/session_git_worktree/__init__.py` | The existing worktree repository API now reads/writes `RDBSessionAgentContextGitWorktree` via context ownership and preserves creation provenance. | Implemented | #240 |
| Prerequisite plan PR 5 | Preserve root-session Project selection, browser, runtime Project prompt, and `create_git_worktree` behavior. | `python/apps/azents/src/azents/services/agent_session_input.py`, `python/apps/azents/src/azents/services/chat/__init__.py`, `python/apps/azents/src/azents/services/project_browser_manifest.py`, `python/apps/azents/src/azents/services/session_git_worktree/__init__.py` | Existing service/repository APIs keep their session-shaped contract while delegating storage to context-owned rows. Runtime prompt and Skill projection dependencies continue through the Project repository interface. | Implemented | #240 |
| Prerequisite plan PR 5 | Keep Agent Project catalog/defaults/presets Agent-owned. | `python/apps/azents/src/azents/repos/agent_project_catalog`, `python/apps/azents/src/azents/repos/agent_project_default`, `python/apps/azents/src/azents/repos/agent_project_preset` | PR #240 does not move catalog/default/preset rows into `SessionAgentContext`; existing services still update Agent-owned repositories. | Implemented | #240 |
| Design non-exposure rule | Do not expose child `SessionAgent` creation or model-visible collaboration tools in prerequisite stack. | `python/apps/azents/src/azents/engine/run/resolve.py`, `python/apps/azents/src/azents/rdb/models/session_agent.py`, public API routes | The stack only creates root rows. No `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, `list_agents`, tree API, or UI route is registered. | Implemented | #237-#240 |
| Migration and rollout | Use clean migration names for context-owned tables and migrate existing root rows. | `python/apps/azents/db-schemas/rdb/migrations/versions/5042746274a0_add_session_agent_context_foundation.py` | The migration creates context-owned tables, backfills root sessions/projects/worktrees, and drops the old session-owned Project/worktree tables after copying row IDs. | Implemented | #240 |

## Gap Closure

The validation pass found one prerequisite-stack gap: running sessions promoted TurnActions only at the next run-entry boundary instead of each model-call turn boundary. PR #245 closes that gap. No prerequisite-stack gaps remain open after code inspection. Items that are intentionally not implemented here are outside the prerequisite stack and remain assigned to the later subagent implementation stack:

| Deferred item | Reason | Owning stack |
| --- | --- | --- |
| Child/nested `SessionAgent` creation and name/path validation | Requires model-visible `spawn_agent` semantics and mailbox integration. | Subagent PR 1 |
| `agent_message` input kind and mailbox producer | Requires child session targeting and collaboration tool semantics. | Subagent PR 2 |
| Six-tool collaboration Toolkit registration | Must be exposed only after all tools are coherent. | Subagent PR 2 |
| Child worker scheduling, terminal result projections, wait cursors, subtree stop/recovery | Requires child sessions and mailbox/tool behavior first. | Subagent PR 3 |
| Subagent Tree projection API and frontend tree/detail UI | Requires child domain and scheduling behavior first. | Subagent PRs 4-5 |
| Living subagent specs and final cleanup | Current prerequisite work exposes no subagent product surface. | Subagent PRs 7-8 |

## Validation Commands

Commands run locally for the prerequisite stack validation:

```console
$ python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
$ cd python/apps/azents && uv run ruff check . && uv run ruff format --check .
$ cd python/apps/azents && uv run pyright
$ cd python/apps/azents && uv run pytest src/azents/repos/session_workspace_project src/azents/repos/session_git_worktree src/azents/repos/agent_session/repository_test.py src/azents/services/session_workspace_project/service_test.py src/azents/services/session_git_worktree/service_test.py src/azents/services/project_browser_manifest_test.py -q
$ cd python/apps/azents && uv run pytest src/azents/services/agent_session_input_test.py src/azents/services/chat/team_session_test.py src/azents/services/chat/input_buffer_test.py src/azents/engine/tools/builtin_test.py src/azents/engine/tools/claude_rules_test.py -q
$ cd python/apps/azents && uv run pytest -q src/azents/engine/events/execution_test.py -k 'turn_boundary_control'
$ cd python/apps/azents && uv run pytest -q src/azents/worker/run/executor_test.py -k 'boundary_poll'
$ cd python/apps/azents && uv run pytest -q src/azents/worker/worker_test.py -k 'boundary_poll_broadcasts_input_buffer_taxonomy_actions'
```

Results:

- Docs index check: passed.
- Ruff check/format check: passed.
- Pyright: passed with 0 errors.
- Repository/service Project/worktree/session tests: 1 passed, 40 skipped because DB-backed tests require local testcontainers runtime.
- Input/chat/tool regression tests: 57 passed, 22 skipped because DB-backed tests require local testcontainers runtime.
- Turn-boundary action targeted tests: passed (1 engine execution test, 3 executor boundary-poll tests, 1 worker broadcast regression test).

## Conclusion

The prerequisite stack satisfies the planned foundation requirements and keeps the new subagent product surface unexposed after the TurnAction turn-boundary fix. The next step is to open PR #245 on top of the validation PR and monitor CI for PRs #236-#241 and #245 together.
