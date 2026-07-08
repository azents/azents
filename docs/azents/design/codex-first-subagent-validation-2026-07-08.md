---
title: "Codex-first Subagent Implementation Validation Report"
created: 2026-07-08
updated: 2026-07-08
tags: [backend, frontend, engine, api, testenv, documentation]
---
# Codex-first Subagent Implementation Validation Report

## Summary

This report validates the Codex-first subagent implementation stack against [ADR-0096](../adr/0096-codex-first-subagent-redesign.md), the implementation design, and the implementation plan.

The validation pass inspected the actual backend, worker, API, frontend, generated-client, and E2E/testenv code. It also closes the frontend validation gaps found during inspection:

- Subagent Tree query state is now isolated in a container hook instead of being built inline in the chat surface.
- `subagent_tree_changed` now invalidates every cached Subagent Tree projection query, so root and child detail views cannot keep a stale tree projection when the live event arrives for a different visible session query key.
- Deterministic E2E coverage now exercises spawn, child execution, tree projection refetch, hidden child sessions, child detail history, and parent `wait_agent` observation through product APIs.

## Validated Stack Scope

Validated local branch chain at inspection time:

| PR | Branch | Scope |
| --- | --- | --- |
| #246 | `feature/subagent-session-agent-domain` | Child `SessionAgent` domain foundation |
| #247 | `feature/subagent-mailbox-tools` | Mailbox input and collaboration tools |
| #248 | `feature/subagent-worker-scheduling-stop` | Worker scheduling, terminal results, stop, and recovery |
| #249 | `feature/subagent-tree-projection-api` | Subagent Tree projection API and live invalidation |
| #250 | `feature/subagent-frontend-tree-surfaces` | Frontend tree and child detail surfaces |
| PR 6 | `feature/subagent-validation-gap-closure` | E2E validation, mapping, and gap closure |

## Requirements-to-Code Mapping

| Source | Requirement | Expected code path(s) | Observed implementation | Status | Gap/fix PR |
| --- | --- | --- | --- | --- | --- |
| ADR-0096 baseline | Subagents are live child agents, not blocking task tools that return only a result string. | `python/apps/azents/src/azents/rdb/models/session_agent.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | `spawn_agent` creates a child `SessionAgent` and linked child `AgentSession`, then wakes the child session independently. | Implemented | #246, #247, #248 |
| ADR-0096 baseline | `AgentSession` remains execution/transcript context; `SessionAgent` owns the live participant tree. | `python/apps/azents/src/azents/rdb/models/session_agent.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | Root and child `SessionAgent` rows carry tree references while each row links one-to-one to an `AgentSession`. | Implemented | #246 |
| ADR-0096 core model | Child/nested identity uses canonical paths with sibling uniqueness. | `python/apps/azents/src/azents/rdb/models/session_agent.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | Repository creation validates child names and enforces unique root path and sibling name constraints. | Implemented | #246 |
| ADR-0096 core model | Do not auto-rename colliding children. | `python/apps/azents/src/azents/repos/agent_session/__init__.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | Duplicate child creation raises and is surfaced as a `FunctionToolError`. | Implemented | #246, #247 |
| ADR-0096 agent type | Start with default-only spawning and do not reintroduce persistent `role=subagent`. | `python/apps/azents/src/azents/engine/tools/subagent.py`, `python/apps/azents/src/azents/core/enums.py` | `spawn_agent.agent_type` accepts only `default`; execution mode uses `session_kind` and toolkit resolution mode rather than persistent Agent role. | Implemented | #247, #248 |
| ADR-0096 collaboration tools | Register the coherent Codex-compatible tool bundle: `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`. | `python/apps/azents/src/azents/engine/tools/subagent.py`, `python/apps/azents/src/azents/engine/run/resolve.py`, `python/apps/azents/src/azents/worker/deps.py` | `SubagentToolkitProvider` returns all six tools and is auto-bound for root and subagent execution modes. | Implemented | #247 |
| ADR-0096 context fork | Support `fork_turns = none | all | positive integer` and fork only current model-visible context. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | `parse_fork_turns()` and `select_fork_events()` are used by `spawn_agent` before child input is enqueued. | Implemented | #247 |
| ADR-0096 FilePart fork | Degrade forked FileParts to metadata placeholders; do not copy blobs automatically. | `python/apps/azents/src/azents/engine/events/fork_context.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | `degrade_file_parts_for_fork()` is applied to selected fork events before appending to the child transcript. | Implemented | #247 |
| ADR-0096 mailbox | Use target child input buffers and promoted `agent_message` events as the durable mailbox representation. | `python/apps/azents/src/azents/services/input_buffer.py`, `python/apps/azents/src/azents/engine/events/types.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | `InputBufferKind.AGENT_MESSAGE` materializes source/target metadata and promotes to `EventKind.AGENT_MESSAGE`. | Implemented | #247 |
| ADR-0096 mailbox | `send_message` queues without waking; `followup_task` wakes. | `python/apps/azents/src/azents/engine/tools/subagent.py` | `_enqueue_agent_message(... wake=False)` is used for `send_message`; `followup_task` marks the target session running and sends a broker wake-up. | Implemented | #247, #248 |
| ADR-0096 wait | `wait_agent` returns unread terminal child run results once and advances observation cursors only for returned results. | `python/apps/azents/src/azents/engine/tools/subagent.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | `wait_agent` compares latest terminal run index to `parent_observed_run_index` and updates the cursor only when adding a returned message. | Implemented | #247, #248 |
| ADR-0096 interrupt | `interrupt_agent` is target-scoped, no-close, no-delete, and returns `previous_status`. | `python/apps/azents/src/azents/engine/tools/subagent.py` | Target lookup is restricted to the current root tree; interrupt requests stop only the selected target session's current run. | Implemented | #247, #248 |
| ADR-0096 list | `list_agents` includes root, children, status, and latest task preview. | `python/apps/azents/src/azents/engine/tools/subagent.py` | Tool output projects each `SessionAgent` entry from linked session/run state and `last_task_message`. | Implemented | #247, #248 |
| ADR-0096 worker | Child sessions are scheduled through the existing worker/broker loop. | `python/apps/azents/src/azents/worker/run/executor.py`, `python/apps/azents/src/azents/worker/deps.py`, `python/apps/azents/src/azents/engine/tools/subagent.py` | `spawn_agent` and `followup_task` use existing wake-up messages; executor resolves subagent execution mode for child sessions. | Implemented | #248 |
| ADR-0096 terminal results | Final child answers become terminal run projections for parent observation and UI unread indicators. | `python/apps/azents/src/azents/worker/run/executor.py`, `python/apps/azents/src/azents/repos/agent_execution`, `python/apps/azents/src/azents/services/chat/__init__.py` | Run finalization stores terminal result event/message; Subagent Tree projection reads latest run projection. | Implemented | #248, #249 |
| ADR-0096 stop | Root user-facing stop interrupts all running descendants; child detail stop interrupts that child subtree. | `python/apps/azents/src/azents/services/chat/__init__.py`, `python/apps/azents/src/azents/worker/session/runner.py`, `python/apps/azents/src/azents/repos/agent_session/__init__.py` | Stop service enumerates descendant sessions for the selected session tree and signals running descendants. | Implemented | #248 |
| ADR-0096 recovery | Parent retry/recovery and child retry/recovery remain independent. | `python/apps/azents/src/azents/worker/session/recovery_test.py`, `python/apps/azents/src/azents/worker/run/executor_test.py` | Tests cover root/subagent sessions as separate recovery units and preserve independent run state. | Implemented | #248 |
| ADR-0096 projection | Add a dedicated Subagent Tree projection API rather than embedding the full tree in root chat `/live`. | `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`, `python/apps/azents/src/azents/services/chat/__init__.py`, `python/apps/azents/src/azents/services/chat/data.py` | `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/subagents/tree` returns the full projection; `/live` remains focused on session live state. | Implemented | #249 |
| ADR-0096 projection | Projection supports nested tree shape, canonical paths, status, previews, unread results, and child detail links. | `python/apps/azents/src/azents/services/chat/__init__.py`, `python/apps/azents/src/azents/services/chat/data.py`, `typescript/packages/azents-public-client/src/generated/types.gen.ts` | `SubagentTreeNodeResponse` includes node IDs, child session IDs, path, status, last task, unread result, latest run, terminal result, and children. | Implemented | #249 |
| ADR-0096 reconnect | Refresh/reconnect reconstructs state from durable DB projection. | `python/apps/azents/src/azents/services/chat/subagent_tree_test.py`, `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` | Service test builds projection from durable DB; new E2E refetches root and child tree projections after child completion. | Implemented | #249, PR 6 |
| ADR-0096 live invalidation | `subagent_tree_changed` is non-durable and only invalidates/refetches the dedicated projection. | `python/apps/azents/src/azents/engine/events/engine_events.py`, `python/apps/azents/src/azents/engine/tools/subagent.py`, `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts` | Backend emits root/changed IDs only. Frontend now invalidates all cached Subagent Tree queries and continues rendering only from the refetched API projection. | Gap fixed | PR 6 |
| Implementation plan PR 5 | Render subagent coordination through ordinary tool call/result cards. | `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts`, `typescript/apps/azents-web/src/features/chat/components/MessageBubble.tsx`, `typescript/apps/azents-web/src/features/chat/components/ToolCallCard.tsx` | Subagent tool calls/results use existing `client_tool_call` / `client_tool_result` chat projection and generic tool cards. | Implemented | #250 |
| Implementation plan PR 5 | Add Subagent Tree UI with status, unread indicators, last task preview, terminal result preview, and child detail links. | `typescript/apps/azents-web/src/features/agents/components/SubagentTreePanel.tsx`, `typescript/apps/azents-web/src/features/agents/components/SubagentTreePanel.stories.tsx` | The panel renders nested rows, statuses, unread badges, run indices, last task previews, terminal result snippets, and links to child session routes. | Implemented | #250 |
| Implementation plan PR 5 | Add full child detail route for long transcripts, refresh, deep links, and debugging. | `typescript/apps/azents-web/src/app/(app)/w/[handle]/(agent)/agents/[agentId]/sessions/[sessionId]/page.tsx`, `typescript/apps/azents-web/src/features/agents/AgentChatTabPage.tsx`, `typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx` | Existing session detail route loads any authorized root or child session by ID; the tree links directly to child `agent_session_id`. | Implemented | #250 |
| Implementation plan PR 5 | Mobile tree/detail navigation uses a drawer/full-height flow with a clear route-based detail surface. | `typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx`, `typescript/apps/azents-web/src/features/agents/components/SubagentTreePanel.tsx` | Header action opens a right drawer with the tree; selecting a child closes the drawer and navigates to the child session route. | Implemented | #250 |
| TypeScript conventions | Query loading/error/data state should be converted to an ADT inside a container hook. | `typescript/apps/azents-web/src/features/agents/containers/useSubagentTreePanelContainer.ts`, `typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx` | Subagent Tree query state is now returned as `SubagentTreePanelState` by `useSubagentTreePanelContainer`; `ChatSessionView` only wires the state into the pure panel. | Gap fixed | PR 6 |
| Testenv no-direct-DB-write rule | Product E2E must reproduce state via product APIs instead of direct DB writes. | `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` | The new E2E creates users/workspaces/agents through public/admin APIs, drives chat through REST input, reads projections/history through public APIs, and performs no DB writes. | Implemented | PR 6 |
| Implementation plan PR 6 | Root agent spawns one child and observes it through `wait_agent`. | `testenv/azents/e2e/src/support/aimock_fixtures/agents_md_loader.json`, `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` | Deterministic AIMock fixtures make the parent call `spawn_agent` and `wait_agent`; the E2E asserts child completion and unread cursor clearing after wait. | Implemented | PR 6 |
| Implementation plan PR 6 | Browser refresh/reconnect reconstructs the same tree from the dedicated projection API. | `testenv/azents/e2e/src/tests/azents/public/test_subagents.py`, `typescript/apps/azents-web/src/features/agents/containers/useSubagentTreePanelContainer.ts` | E2E refetches the Subagent Tree through REST after child completion and after wait; frontend uses the same API through the generated client/tRPC route. | Implemented | PR 6 |
| Implementation plan PR 6 | Child transcript detail opens from parent tree and reads child session history. | `typescript/apps/azents-web/src/features/agents/components/SubagentTreePanel.tsx`, `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` | Panel links to child session routes; E2E reads the child `agent_session_id` from the tree and verifies child task/assistant history through the public history endpoint. | Implemented | PR 6 |
| Security requirements | Child sessions stay hidden from ordinary Agent session lists. | `python/apps/azents/src/azents/services/chat/__init__.py`, `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` | E2E asserts the child `agent_session_id` is absent from `/chat/v1/agents/{agent_id}/sessions` while remaining accessible through tree/detail routes. | Implemented | PR 6 |

## E2E Scenario Matrix

| Scenario | Coverage path | Status |
| --- | --- | --- |
| Root agent spawns one child and observes it through `wait_agent`. | `testenv/azents/e2e/src/tests/azents/public/test_subagents.py` with AIMock tool-call fixtures. | Covered |
| Child receives `send_message` without wake and later processes queued context through `followup_task`. | Unit/worker coverage in `python/apps/azents/src/azents/engine/tools/subagent_test.py` and worker scheduling tests; not repeated in deterministic E2E to keep PR 6 CI cost bounded. | Covered by focused lower-level tests |
| Nested child spawn appears in the same root tree projection. | `python/apps/azents/src/azents/services/chat/subagent_tree_test.py`. | Covered by service test |
| `interrupt_agent` interrupts only the target child current run. | `python/apps/azents/src/azents/engine/tools/subagent_test.py` and stop/recovery tests. | Covered by focused lower-level tests |
| Root stop interrupts all running descendants. | `python/apps/azents/src/azents/worker/run/executor_test.py` / chat stop service tests in the implementation stack. | Covered by focused lower-level tests |
| Child detail stop interrupts that child subtree. | Chat stop service and worker tests in the implementation stack. | Covered by focused lower-level tests |
| Browser refresh/reconnect reconstructs the same tree from the dedicated projection API. | New deterministic E2E refetches root and child tree projections through public API; frontend container uses the same generated API route. | Covered |
| Child transcript detail opens from parent tree and reads child session history. | New deterministic E2E follows the tree's child session ID through public history; UI row links use the same session route. | Covered |
| Mobile tree/detail navigation uses drawer/full-screen flow with a clear back path. | `SubagentTreePanel.stories.tsx` covers pure panel states; `ChatSessionView.tsx` uses a Mantine Drawer and route navigation. No in-repo Playwright/browser harness exists for this app. | Covered by static/story validation |

## Validation Commands

| Command | Result | Notes |
| --- | --- | --- |
| `cd typescript && pnpm run typecheck --filter=@azents/web` | PASS | Regenerated public TS client as part of Turbo dependency chain; no diff. |
| `cd typescript && pnpm run lint --filter=@azents/web` | PASS | ESLint passed with zero warnings. |
| `cd testenv/azents/e2e && uv run ruff format src/tests/azents/public/test_subagents.py && uv run ruff check src/tests/azents/public/test_subagents.py` | PASS | New E2E test file formatted and linted. |
| `cd testenv/azents/e2e && uv run pyright src/tests/azents/public/test_subagents.py` | PASS | Targeted pyright passed. |
| `cd testenv/azents/e2e && uv run pytest ./src/tests/azents/public/test_subagents.py -q` | BLOCKED locally | Docker socket is unavailable in this runtime (`FileNotFoundError` while testcontainers creates the Docker network). Deterministic CI has the required Docker environment. |

## Open Follow-up for Spec Promotion

PR 7 should run `/spec-review` and promote the implemented current behavior into living specs. Likely affected documents remain the ones listed in the implementation plan: agent/session domain specs, toolkit specs, agent execution loop, chat resync, file exchange storage, and E2E-primary test strategy.
