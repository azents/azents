---
title: "Codex-first Subagent Redesign Implementation Design"
created: 2026-07-08
updated: 2026-07-08
implemented: 2026-07-08
tags: [architecture, backend, frontend, engine, api]
---
# Codex-first Subagent Redesign Implementation Design

## Summary

Azents will implement the new subagent model defined by [ADR-0096](../adr/0096-codex-first-subagent-redesign.md). The implementation should avoid mixing unrelated foundation cleanup with the model-visible subagent surface. Independent prerequisite work should land first, then the subagent-specific stack should focus on `SessionAgent`, `SessionAgentContext`, collaboration tools, child scheduling, and UI projection.

The rollout has no feature flag. Intermediate code remains unexposed by keeping unfinished endpoints, tools, and UI entry points unregistered until their phase reaches a coherent usable boundary.

## Goals

- Implement Codex-style live child/nested subagents using Azents `SessionAgent` and independent child `AgentSession` execution.
- Preserve the shared runtime/workspace mental model while keeping transcripts, runs, inputs, tool state, skills, goals, todos, model files, artifacts, and exchange files session/run scoped.
- Move shared root-tree logical resources into `SessionAgentContext` only where required: active Project registry and Azents-owned Git worktree allocation/cleanup rows.
- Complete independent prerequisites first so later PRs can focus on subagent behavior rather than broad engine/tooling drift.
- Keep implementation phases reviewable, stackable, and testable without exposing incomplete tools or UI.

## Non-goals

- Restore the removed legacy subagent role/link/event/API model.
- Provide backward compatibility with old subagent API clients or transcript event kinds.
- Add feature flags for the new model.
- Implement selectable non-default agent profiles in `spawn_agent`.
- Implement subagent retention/removal UX beyond root lifecycle ownership.
- Grant Memory Write or Goal Toolkit capability to subagents in the initial model.
- Implement rich file blob copying or shared blob reference lifetimes during context fork.

## Current Behavior and Constraints

The previous subagent implementation was removed by the reset work. The current system still has several adjacent concepts that affect the redesign:

- `AgentSession` owns execution state, transcript/event history, input buffers, pending command state, stop intent, run heartbeat, model-input head, and ModelFile GC cursor.
- `session_workspace_projects` currently represents active Project scope for one session.
- `session_git_worktrees` currently owns Azents-created Git worktree allocation and cleanup for one session.
- Toolkit state, selected toolkit defaults, AGENTS.md/Claude Rules dedupe state, Skill projection/loading, Todo, and Goal behavior are session-scoped.
- ModelFile retention follows the individual `AgentSession` model-input head and active run pins. Artifacts and ExchangeFiles follow TTL/file-access lifecycle policy.
- Broker wake-ups are payload-free; durable input comes from persisted input buffers and promoted transcript events.

## Proposed Design

### Core Model

Introduce `SessionAgent` as the live participant tree for a root session:

- Root sessions have one root `SessionAgent` with `kind = root`.
- Child and nested subagents are `SessionAgent` rows with `kind = subagent`.
- Each `SessionAgent` links one-to-one to an `AgentSession`.
- Tree identity is stored on `SessionAgent` using `root_session_agent_id`, `parent_session_agent_id`, `name`, and canonical absolute `path`.
- `AgentSession` remains the execution/transcript context; it is not the tree source of truth.
- `agent_sessions.session_kind = root | subagent` is a listing/filtering marker so ordinary session lists can hide child sessions.

### Shared Root-tree Context

Introduce `SessionAgentContext` for one root `SessionAgent` tree:

- Every `SessionAgent` in the same root tree references the same context.
- The context references the owning Agent, Workspace, root `SessionAgent`, and AgentRuntime.
- Context-owned mutable resources are limited to:
  - active Project registry rows, stored in `session_agent_context_projects`;
  - Azents-owned Git worktree allocation/cleanup rows, stored in `session_agent_context_git_worktrees`.
- Referenced resources keep their existing owners. Agent, Workspace, AgentRuntime, Toolkit configs, memory storage, provider settings, access-control membership, Agent Project catalog, Project defaults, and Project presets do not move into the context.
- Session/run-owned resources stay session/run-owned: transcripts, input buffers, AgentRuns, action executions, Goal, Todo, Toolkit State, selected toolkit defaults, AGENTS.md/Claude Rules dedupe state, Skill projection/loading state, ModelFiles, ModelFilePins, artifacts, and exchange files.

### Context Fork Semantics

`spawn_agent.fork_turns` accepts only `"none"`, `"all"`, or positive integer strings.

- `"all"` copies the parent's current model-visible context range, not the entire durable transcript. The range starts at the current model-input head/compaction boundary and includes subsequent model-visible events.
- Positive integer values select the latest N turns within that same current model-visible range.
- `"none"` starts the child with the delegated spawn task plus normal child run preparation context.
- ModelFile-backed FileParts in forked parent context are degraded to bounded text placeholders. The fork does not copy object storage blobs, does not create child ModelFiles, and does not share ModelFile rows through `SessionAgentContext`.
- If a child needs file bytes, the parent must provide a runtime workspace path, import/export URI workflow, or another explicit handoff outside automatic context forking.

### Collaboration Tool Surface

Expose a bundled subagent collaboration Toolkit only when the subagent phase is ready:

- `spawn_agent`
- `send_message`
- `followup_task`
- `wait_agent`
- `interrupt_agent`
- `list_agents`

Initial `spawn_agent.agent_type` is omitted or `default` only. Non-default values fail validation.

`send_message` is queue-only. `followup_task` assigns work and wakes the child session. `wait_agent` observes unread terminal child run projections through per-child cursors. `interrupt_agent` interrupts only the addressed child current run and never closes/deletes it.

### Events and Transcript

- Parent transcript records ordinary collaboration tool calls/results only.
- Child execution details live in the child `AgentSession` transcript.
- Parent-to-child input is represented in the child session as `agent_message`, lowered as delegated user-role-compatible task/message content with explicit source labeling.
- Do not create durable parent summary events such as `subagent_created`, `subagent_message_sent`, `subagent_result_observed`, or `subagent_interrupted`.
- Store child terminal result projections on terminal `AgentRun` rows for `wait_agent`. `wait_agent` must not scan the child transcript at read time to infer the terminal result.

### Scheduling and Stop Behavior

- `spawn_agent` creates child `SessionAgent` and child `AgentSession`, writes the initial `agent_message`, and sends a payload-free broker wake-up.
- `followup_task` writes an `agent_message` and wakes the child.
- `send_message` writes an `agent_message` and does not wake the child.
- Parent and child sessions have independent `AgentRun` rows, retry state, stop intent, run heartbeat, pending command state, and failed-run recovery paths.
- User-facing stop is subtree orchestration over durable `SessionAgent` tree membership and linked child run state.
- Model-visible `interrupt_agent` remains target-scoped and does not automatically interrupt descendants.

### Frontend and Observability

- Parent chat shows actual collaboration tool cards.
- A dedicated Subagent Tree API projects the current root tree from durable rows and linked session/run state.
- The root chat `/live` payload does not embed the full subagent tree.
- Non-durable live signals such as `subagent_tree_changed` are invalidation/update triggers only; refresh/reconnect refetches the projection API.
- Desktop provides a tree panel/section and quick child detail surface.
- Mobile uses a full-height drawer or dedicated screen for the tree and a full-screen child detail view.
- Child sessions remain hidden from ordinary Agent session lists, but authorized direct child detail links are allowed through root tree context.

## Implementation Phases

### Phase 0 — ADR and cleanup baseline

Status: mostly complete before this design.

Scope:

- Remove legacy subagent surfaces.
- Record ADR-0096 decisions.
- Ensure old `role=subagent`, `agent_subagents`, legacy events, and old UI routes are not resurrected.

Completion criteria:

- Current branch contains no legacy subagent compatibility layer.
- ADR-0096 is validated with the docs index check.

### Prerequisite Phase 1 — Session input producer and wake boundary cleanup

This phase is intentionally independent of subagent tools. It prepares the input pipeline so agent-to-agent delivery can be added without expanding a generic wake API.

Scope:

- Keep `input_buffers` as internal pending model-input storage.
- Introduce a low-level input-buffer writer that only appends rows and returns created rows.
- Split domain producers around fixed semantics:
  - user message input producer;
  - turn action input producer;
  - system reminder input producer;
  - placeholder interface for future agent mailbox input producer.
- Remove caller-provided generic `wake=true/false` from the low-level input-buffer path.
- Keep ordering across heterogeneous inputs in the orchestrator that owns the larger workflow.

Completion criteria:

- Existing user message, first-message, edit, TurnAction, and system reminder flows behave unchanged.
- Broker wake-up decisions live in domain producers/orchestrators, not in the low-level writer.
- No model-visible subagent tool is registered.

Recommended PR boundary: one backend PR with focused service/repository tests.

### Prerequisite Phase 2 — Toolkit taxonomy and subagent-mode groundwork

This phase separates broad tool-surface cleanup from subagent implementation.

Scope:

- Rename the current runtime-independent `builtin` memory behavior into explicit Memory Read / Memory Write Toolkit capabilities.
- Keep Memory Read eligible for subagent mode when memory is enabled.
- Keep Memory Write excluded from subagent-mode auto-binding.
- Rename the runtime file/process toolkit concept to `runtime` rather than `shell` in the redesigned tool taxonomy.
- Preserve root session behavior while making tool resolution capable of applying execution-mode filters later.
- Keep Goal Toolkit root/user-facing by default and do not auto-bind it for subagent mode.

Completion criteria:

- Root sessions still receive equivalent intended capabilities.
- Tool resolution has an explicit execution-mode filter seam, but no subagent tools are registered yet.
- Memory Read/Write separation is test-covered at toolkit resolution level.

Recommended PR boundary: one backend/tooling PR. If public API/client schemas change, regenerate clients in the same PR.

### Prerequisite Phase 3 — Model-input fork range and FilePart placeholder utility

This phase builds fork mechanics without creating subagents.

Scope:

- Add reusable logic to select parent fork context from the current model-input head boundary.
- Support `fork_turns="all"`, `"none"`, and positive integer string validation as a reusable parser/helper.
- Render forked ModelFile-backed FileParts as bounded text placeholders.
- Ensure fork rendering does not copy blobs, create child ModelFiles, or share ModelFile rows.
- Add tests around compaction/head boundary behavior so pre-head durable history is not copied.

Completion criteria:

- Fork helper can be unit-tested without a registered `spawn_agent` tool.
- Placeholder text includes available name, media type, size, and source event reference facts.
- The helper has clear failure behavior for malformed `fork_turns` values.

Recommended PR boundary: one engine/events PR.

### Prerequisite Phase 4 — Root SessionAgent and context-owned Project foundation

This is the bridge from general prerequisites into the new root-tree resource model, but it should still expose no child subagent behavior.

Scope:

- Add `session_agents` with root rows for normal sessions.
- Add `session_agent_contexts` and create one context for every root session.
- Add `agent_sessions.session_kind`, defaulting existing normal sessions to `root`.
- Move active Project registry ownership from `session_workspace_projects` to `session_agent_context_projects`.
- Move Azents-owned Git worktree allocation/cleanup authority from `session_git_worktrees` to `session_agent_context_git_worktrees`.
- Preserve user-facing Project and worktree behavior for normal root sessions.
- Update runtime Project prompt loading to read from `SessionAgentContext`.
- Keep Agent Project catalog/defaults/presets Agent-owned.

Completion criteria:

- Existing session creation creates root `SessionAgent` and `SessionAgentContext` transactionally.
- Existing Project selection, Project browser, runtime Project prompt, and `create_git_worktree` behavior pass against context-owned tables.
- Ordinary session lists still show root sessions.
- No child `SessionAgent` can be created through public/model-visible surfaces yet.

Recommended PR boundary: this may need two stacked PRs if migration and service changes are large:

1. DB/domain migration and repositories.
2. Project/worktree service/API/runtime read-path migration.

### Subagent Phase 1 — Child SessionAgent domain foundation

Scope:

- Support child/nested `SessionAgent` creation under an existing root tree.
- Enforce `(root_session_agent_id, path)` and `(parent_session_agent_id, name)` uniqueness.
- Validate child names strictly.
- Add `agent_runs` terminal result projection fields.
- Add repository/domain APIs for tree lookup, path resolution, child creation, descendant enumeration, and observation cursor updates.
- Keep child `AgentSession` rows hidden from ordinary session lists by `session_kind`.

Completion criteria:

- Repository tests cover root, child, nested child, collision, invalid names, and cascade ownership.
- Terminal result projection fields can be written/read independently of collaboration tools.
- No model-visible subagent Toolkit is registered yet.

### Subagent Phase 2 — Agent mailbox input and collaboration tools

Scope:

- Implement agent mailbox input producer using target child input buffers.
- Add `agent_message` event kind and model lowering.
- Implement `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`.
- Keep `spawn_agent.agent_type` default-only.
- Wire `fork_turns` helper from prerequisite Phase 3.
- Register collaboration tools only when the whole six-tool baseline is coherent.

Completion criteria:

- `spawn_agent` creates child `SessionAgent`, child `AgentSession`, initial `agent_message`, and child wake-up in one coherent operation.
- `send_message` is queue-only.
- `followup_task` wakes the target child.
- `wait_agent` returns Codex-aligned `message` and `timed_out` shape.
- `interrupt_agent` returns `previous_status` and performs no close/delete.
- Tool tests cover invalid names, duplicate children, missing targets, out-of-tree targets, default-only agent type, and fork validation.

### Subagent Phase 3 — Worker scheduling, terminal projections, stop, and recovery

Scope:

- Schedule child sessions as independent `AgentSession` runs through existing worker/broker mechanics.
- Finalize terminal result projection during child run finalization.
- Implement wait observation cursor advancement only for returned terminal results.
- Implement user-facing subtree stop from root and child detail surfaces.
- Keep model-visible `interrupt_agent` target-scoped.
- Ensure parent run retry/recovery does not mutate child runs and child retry/recovery does not mutate parent run state.

Completion criteria:

- Child failures surface to parent only through terminal result projection and `wait_agent` observation.
- Root stop interrupts root and all running descendants.
- Child detail stop interrupts that child subtree.
- Targeted `interrupt_agent` does not automatically interrupt descendants.
- Worker recovery tests cover parent/child independence.

### Subagent Phase 4 — Projection API, frontend tree, and child detail UI

Scope:

- Add dedicated Subagent Tree projection API for a root `SessionAgent` tree.
- Add live invalidation/update signal such as `subagent_tree_changed` without treating it as source of truth.
- Render parent chat collaboration tool cards as ordinary tool interactions.
- Add desktop Subagent Tree panel/section.
- Add quick child detail surface and full child detail route.
- Add mobile full-height drawer or dedicated tree screen and full-screen child detail flow.
- Keep child sessions hidden from ordinary Agent session lists.

Completion criteria:

- Refresh/reconnect reconstructs the same tree from DB projection.
- Parent chat timeline does not show synthetic durable-looking lifecycle cards.
- Child detail reads child `AgentSession` history/live APIs directly.
- Mobile navigation has a clear back path to the root session.

### Subagent Phase 5 — Spec sync, E2E, QA, and cleanup

Scope:

- Run `/spec-review` for the coherent behavior boundary.
- Add/update living specs under `docs/azents/spec/` for current behavior.
- Remove temporary implementation notes if superseded by specs/design.
- Run final E2E/QA.

Completion criteria:

- Living specs describe the implemented behavior and include current code paths.
- E2E evidence covers nested subagents, wait/interrupt, subtree stop, reconnect, child detail route, and mobile detail navigation.
- CI is monitored after the full planned PR stack is created.

## Data Model Changes

### New or changed tables/columns

- `session_agents`
  - `id`
  - `root_session_agent_id`
  - `parent_session_agent_id`
  - `agent_session_id`
  - `kind`
  - `name`
  - `path`
  - `agent_type`
  - `last_task_message`
  - `parent_observed_run_index`
  - `parent_observed_event_id`
  - `created_at`
  - `updated_at`
- `session_agent_contexts`
  - references root `SessionAgent`, owning Agent, owning Workspace, and AgentRuntime
- `session_agent_context_projects`
  - `session_agent_context_id`
  - `path`
  - unique `(session_agent_context_id, path)`
- `session_agent_context_git_worktrees`
  - context-owned replacement for session-owned worktree allocation/cleanup rows
  - includes creation provenance such as `created_by_session_agent_id`, `created_by_agent_session_id`, and `action_execution_id`
- `agent_sessions.session_kind = root | subagent`
- `agent_runs` terminal result projection fields

### Removed or not reintroduced

- Legacy `role=subagent` Agent model.
- Legacy `agent_subagents` link model.
- Legacy parent transcript subagent summary events.
- `SessionWorkspaceProjectRegistrationRequest` replacement in the new model.

## API and Tooling Changes

- Add internal/domain APIs for `SessionAgent` tree lookup and child creation.
- Add model-visible subagent Toolkit only in Subagent Phase 2.
- Add dedicated Subagent Tree projection API in Subagent Phase 4.
- Keep ordinary session list APIs excluding `session_kind = subagent` rows.
- Regenerate OpenAPI clients when public API shapes change.

## Error Handling

- `spawn_agent` fails atomically if child `SessionAgent` or child `AgentSession` creation fails.
- Invalid child names, duplicate sibling names, unsupported agent types, missing parents, and out-of-tree target paths return tool-level validation errors.
- Missing `wait_agent` / `interrupt_agent` targets resolve as `not_found` in Codex-aligned result semantics where applicable.
- Child run failures are captured as terminal result projections and observed by parent through `wait_agent`.
- Runtime/broker failures do not create parent/child retry coupling.

## Security and Permissions

- Existing workspace membership, Agent access checks, runtime provider policy, model capability validation, and ToolkitConfig attachment rules continue to apply.
- Subagents do not receive a new partial-permission model.
- Child subagents use the same configured Agent access under their own `AgentSession` lifecycle and Toolkit State.
- Memory Write and Goal Toolkit are excluded from subagent-mode auto-binding by default.
- Child detail routes require authorization through normal session access and root tree context.
- Cross-root session control is not supported.

## Migration and Rollout

- Use clean migration names for context-owned tables rather than changing ownership under legacy names.
- Do not edit migrations that have already run in an environment.
- No feature flag is added.
- Avoid partial exposure by not registering unfinished endpoints, tools, or UI routes until the owning phase is ready.
- Stack prerequisite PRs first. After prerequisites merge or are stable in the stack, implement subagent-specific phases.

## Test Strategy

### E2E primary verification matrix

E2E is the primary product behavior verification once Subagent Phase 4 lands.

Required E2E scenarios:

- Root agent spawns one child and observes it through `wait_agent`.
- Child receives `send_message` without wake, then later receives `followup_task` and processes queued context.
- Nested child spawn appears in the same root tree projection.
- `interrupt_agent` interrupts only the target child current run.
- Root stop interrupts all running descendants.
- Child detail stop interrupts only that child subtree.
- Browser refresh/reconnect reconstructs the same tree from the dedicated projection API.
- Child transcript detail opens from parent tree and reads the child session history.
- Mobile tree/detail navigation uses drawer/full-screen flow with a clear back path.

### Backend tests

- Repository/model tests for `SessionAgent`, `SessionAgentContext`, Projects, worktrees, and observation cursors.
- Input producer tests for wake ownership boundaries.
- Toolkit resolution tests for Memory Read/Write split, runtime toolkit naming, Goal exclusion, and subagent-mode filtering.
- Fork helper tests for head-bound `fork_turns`, positive integer values, invalid values, and FilePart placeholders.
- Tool tests for all six collaboration tools.
- Worker tests for child scheduling, terminal result finalization, wait cursor advancement, subtree stop, and recovery independence.

### Frontend tests

- Component/unit tests for tree projection rendering, status projection, unread/observed indicators, and child detail entry points.
- Route tests for hidden child sessions in ordinary lists and authorized child detail deep links.
- Mobile layout/navigation tests for tree drawer/full-screen detail behavior.

### Testenv and fixture requirements

- Add fixture support for a root session with child/nested `SessionAgent` rows and linked child sessions.
- Add controllable fake/fixture agents that can complete, fail, run long enough to be interrupted, and spawn nested children.
- Provide reconnect/refresh fixture setup with existing tree state in DB.
- Optional live-runtime tests may be skipped only when runtime/provider prerequisites are unavailable; deterministic backend and frontend tests must still pass.

### Evidence format

Each PR should include:

- focused commands run locally;
- generated client commands when applicable;
- relevant backend/frontend test summaries;
- E2E evidence for phases that expose user-visible behavior;
- known skipped optional/live tests with reasons.

CI should be monitored after the planned PR stack is created.

## Risks and Mitigations

- **Large migration blast radius**: split input/tool prerequisites from context/table migrations and keep each PR focused.
- **Project/worktree ownership drift**: migrate read and write paths together and test Project prompt, browser, and cleanup behavior before subagent tools land.
- **Tool surface partial exposure**: register collaboration tools only after all six baseline tools and mailbox semantics are coherent.
- **File context loss during fork**: make FilePart placeholder text explicit so child agents know file bytes are unavailable and can request a handoff.
- **Parent/child lifecycle coupling bugs**: cover retry, stop, and failure behavior with worker tests before UI exposure.
- **Frontend source-of-truth confusion**: keep live signals non-durable and require projection API refetch on refresh/reconnect.

## Alternatives Considered

### Implement a single vertical subagent slice first

Rejected. It would mix input pipeline cleanup, toolkit taxonomy, DB ownership migration, worker behavior, and UI projection in one review path, making it hard to isolate regressions.

### Put all shared state into `SessionAgentContext`

Rejected. It would blur session/run ownership and conflict with existing ModelFile, Toolkit State, Skill, Goal, Todo, and transcript lifecycles.

### Copy object storage blobs during context fork

Rejected. It adds latency, storage cost, failure modes, and GC complexity. Initial fork degrades FileParts to bounded text placeholders.

### Hide incomplete work behind a feature flag

Rejected. The redesign has no legacy compatibility target. Incomplete surfaces should remain unregistered until ready.

## Related Documents

- [ADR-0096: Codex-first Subagent Redesign](../adr/0096-codex-first-subagent-redesign.md)
- [Subagent Removal Design](subagent-removal-2026-07-06.md)
- [ADR-0080: Simplified File Lifecycle Policy](../adr/0080-simplified-file-lifecycle-policy.md)
- [ADR-0092: Azents-owned Git Worktree Ownership and Cleanup](../adr/0092-azents-owned-git-worktree-ownership-and-cleanup.md)
- [ADR-0094: Model Session Operations as Turn Actions](../adr/0094-action-as-operation-turn-actions.md)
