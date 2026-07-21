---
title: "Codex-first Subagent Redesign"
created: 2026-07-06
tags: [architecture, agent, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: codex-260706
historical_reconstruction: true
migration_source: "docs/azents/adr/0096-codex-first-subagent-redesign.md"
---

# codex-260706/ADR: Codex-first Subagent Redesign

## Context

Azents removed the previous subagent implementation and living specs to restart from a clean slate. The new design will be discussed topic by topic and then implemented incrementally.

The baseline premise is Codex-first: Azents follows Codex's subagent model by default and diverges only where Azents makes the Codex behavior awkward or impossible.

## Decision

Adopt Codex's subagent model as the default design reference for the new Azents subagent system.

Accepted baseline trade-offs:

- Subagents are live child agents, not blocking task-tool calls that return only a result string.
- `spawn_agent` returns child identity and canonical task name.
- Parent and children coordinate through a collaboration tool plane: `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`.
- Child agents share the parent workspace/runtime by default.
- Child agents receive the same tool surface as the spawning agent by default.
- Child agents may spawn nested child agents.
- No subagent-specific partial permission model is introduced by default.
- Codex trade-offs are accepted unless the behavior conflicts with Azents product/runtime boundaries.

Existing Azents product boundaries still apply, including workspace membership, Agent access checks, runtime provider/runner boundaries, configured shell/network policy, model capability validation, and existing toolkit constraints. These are ambient boundaries, not subagent-specific partial permissions.

## Design Topics

Each topic should be discussed through a focused `/feature-design` pass.

1. **Subagent core model**
   - Define whether the durable runtime object is an AgentSession child subagent, a separate subagent table, or a derived projection.
   - Define root/parent/child relationships, canonical task path, subagent status, and lifecycle states.
   - Define how Codex thread-tree semantics map to Azents AgentSession, AgentRun, and AgentRuntime.

2. **Agent type and profile model**
   - Define what Codex `agent_type` maps to in Azents.
   - Decide whether to reuse Agent rows as profiles, introduce lightweight agent profiles, or start with default-only spawning.
   - Avoid reintroducing the removed persistent `role=subagent` model unless a later design explicitly reverses that decision.

3. **Collaboration tool surface**
   - Define model-visible tools and exact naming.
   - Preserve Codex-compatible semantics for `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`.
   - Decide tool descriptions, schemas, result payloads, and error messages.

4. **Context fork semantics**
   - Implement Codex-compatible `fork_turns`: `none`, `all`, and positive integer strings.
   - Define how parent transcript slices become child model input.
   - Preserve Codex's full-history fork restriction against role/model/reasoning override unless Azents cannot support it.

5. **Mailbox and inter-agent communication**
   - Define durable queue/mailbox semantics for `send_message`, `followup_task`, final child answer, status updates, and errors.
   - Separate queue-only message delivery from turn-triggering follow-up delivery.
   - Define delivery, consumption, idempotency, and wake-up behavior.

6. **Wait/list/interrupt lifecycle control**
   - Define `wait_agent` as synchronization on mailbox/activity rather than result fetching.
   - Define `list_agents` visibility within the root AgentSession's subagent tree.
   - Define `interrupt_agent` behavior: interrupt current run while keeping the child reusable.

7. **Workspace and runtime sharing**
   - Preserve Codex's shared workspace model as the baseline.
   - Map child sessions to the same AgentRuntime workspace.
   - Define concurrency assumptions and file-change attribution without adding subagent-specific partial write permissions.

8. **Tool exposure and nested subagents**
   - Define how the parent tool surface is reused by child agents.
   - Keep nested `spawn_agent` available to child agents by default.
   - Clarify how existing ambient product/runtime boundaries apply.

9. **Events, transcript, and model lowering**
   - Define durable event kinds or projections for subagent creation, messaging, status, completion, and interruption.
   - Define what is model-visible in parent and child transcripts.
   - Preserve Azents event transcript as the durable source of truth.

10. **Worker, broker, and run scheduling**
    - Define how child AgentSession runs are scheduled.
    - Define how mailbox-triggered runs interact with input buffers and broker wake-ups.
    - Define stop/shutdown/retry behavior across parent and child sessions.

11. **Frontend and observability**
    - Define live projection and reconnect behavior for subagent trees.
    - Define how parent chat shows spawned/running/completed children and final child messages.
    - Define how users inspect child transcripts.

12. **Rollout and compatibility**
    - Define activation timing, migration order, and incremental PR boundaries without feature flags.
    - Confirm no backward compatibility with the removed subagent implementation unless explicitly requested.

## Current Discussion Notes

### Subagent core model

Accepted so far:

- Introduce a session-scoped live agent domain model, tentatively named `SessionAgent`, to generalize the root agent entry and child/nested subagent entries.
- Distinguish existing `Agent` from `SessionAgent`: `Agent` is the configured persistent owner/profile of sessions, while `SessionAgent` is a live agent participant inside a concrete session tree.
- Do not give AgentSession the structural parent/root role for the subagent tree. AgentSession remains the execution/transcript context linked from each `SessionAgent` entry.
- Keep a strict one-to-one relationship between `SessionAgent` and `AgentSession`. The root `SessionAgent` links to the root AgentSession, and each subagent `SessionAgent` links to its own child AgentSession.
- Represent the root agent context as a `SessionAgent` row with `kind = root`. Represent child and nested subagents as `SessionAgent` rows with `kind = subagent`.
- Use generalized self-references on `SessionAgent` for tree structure: root entries self-reference through `root_session_agent_id = id`; non-root entries point to the root entry through `root_session_agent_id` and to their immediate parent through `parent_session_agent_id`.
- Enforce `SessionAgent` identity and sibling uniqueness with unique constraints on `(root_session_agent_id, path)` and `(parent_session_agent_id, name)`. This preserves both canonical path identity and the spawn collision policy as database invariants.
- Keep Codex-style absolute paths such as `/root`, `/root/backend_research`, and `/root/backend_research/security_review` as the model-facing canonical identity for `SessionAgent` entries.
- Fail `spawn_agent` when the requested child name would collide with an existing child under the same parent. Do not auto-rename or create sibling suffixes; the model should choose a different name or use `followup_task` against the existing subagent.
- Strictly validate child subagent names at spawn time instead of normalizing them. Allow only path-safe names such as ASCII letters, numbers, `_`, and `-`; reject empty names, whitespace, `/`, `.`, `..`, and other path-separator or escaping-sensitive characters.
- Do not duplicate execution status or lifecycle state on `SessionAgent`. Derive execution-facing status for `list_agents` and UI from the linked AgentSession's `run_state` and latest AgentRun status.
- Create each child subagent `SessionAgent` entry and its linked AgentSession in the same transaction. If either creation step or invariant validation fails, fail the whole `spawn_agent` call rather than allowing an orphan subagent entry or orphan child session.
- Create child subagent AgentSessions with the same `agent_id` as the parent execution context. Agent type/profile behavior is metadata or profile snapshot behavior on `SessionAgent`, not a separate persisted `role=subagent` Agent row.
- Store `session_kind = root | subagent` on AgentSession as a listing/filtering marker so ordinary session lists can exclude child subagent sessions without relying only on tree joins. This field is not the tree source of truth; the generalized tree/list/detail UI resolves the full tree through `SessionAgent`.
- Hide child subagent AgentSessions from ordinary Agent session lists. They are surfaced through subagent-tree/list/detail UI, not as top-level user-created sessions.
- Keep completed subagents reusable. A completed child can receive `followup_task` and continue in the same child AgentSession/context.
- Do not add model-facing `close_agent` or a core subagent close concept for this design topic. Subagent retention/removal is outside the core Codex-first model and can be handled later through root lifecycle or separate retention policy if needed.
- Define ownership as cascade deletion from the root AgentSession: if a root AgentSession is deleted, its root `SessionAgent`, child/nested `SessionAgent` rows, and child/nested subagent AgentSessions are deleted with it. There is currently no ordinary product use case that deletes AgentSessions; this is a data ownership invariant for a future deletion path, not an active user flow.
- Store `SessionAgent` rows in a `session_agents` table with final core columns: `id`, `root_session_agent_id`, `parent_session_agent_id`, `agent_session_id`, `kind`, `name`, `path`, `agent_type`, `last_task_message`, `parent_observed_run_index`, `parent_observed_event_id`, `created_at`, and `updated_at`. Use the long self-reference column names for clarity over abbreviation.
- Store `last_task_message` separately from execution status. It is the latest task/message preview for `list_agents`, not a derived field from the current run status. A completed subagent may still need to show its last task message, especially while its terminal result remains unread by the parent.

### Agent type and profile model

Accepted so far:

- Start with default-only spawning. `spawn_agent` does not initially support selecting multiple agent profiles or custom agent types.
- Keep the Codex-compatible `agent_type` field in the `spawn_agent` schema, but only allow it to be omitted or set to `default` in the initial implementation. Reject any non-default value with a validation error instead of silently falling back.
- Store a minimal type snapshot on `SessionAgent`, initially `agent_type = "default"`. Do not store a broader profile snapshot until selectable profiles are explicitly designed later.
- Do not reintroduce the removed persistent `role=subagent` Agent model. Existing `Agent` remains the persistent configured owner/profile, subagent identity is represented by `SessionAgent(kind=subagent)`, and subagent execution/transcript ownership is represented by the linked child AgentSession.
- Child subagent sessions inherit the parent execution context by default, including model policy, workspace/runtime, and ambient product/runtime boundaries. The inherited tool surface is filtered for subagent execution mode: built-in tools that would be semantically invalid or unsafe for subagents are excluded instead of being exposed by default. The exact exclusion list belongs to the collaboration tool surface topic; this topic records the inheritance/filtering principle.

### Collaboration tool surface

Accepted so far:

- Provide the initial subagent collaboration surface as a bundled Toolkit containing the Codex-compatible tools: `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`.
- Treat this six-tool set as the baseline model-visible collaboration surface; individual tool schemas, result payloads, and error semantics are decided in the following tool-surface decision points.
- Define `spawn_agent` with a Codex-compatible shape adjusted for Azents decisions. Inputs include `task`, strict path-safe `name`, optional `agent_type` limited to `default`, and optional `fork_turns` whose detailed semantics are finalized in the context-fork topic. Results include `name`, `path`, `session_agent_id`, `agent_session_id`, `agent_type`, and `status`. Errors include invalid name, duplicate child name, unsupported agent type, missing parent, and creation failure.
- Define the model-visible behavior of `send_message` and `followup_task` separately from their internal mailbox implementation. `send_message` is a queue-only communication tool that delivers a message to a target child without directly assigning a new task. `followup_task` assigns a new task to an existing child and may resume/reuse that child's existing `SessionAgent` and linked AgentSession. The concrete mailbox storage, delivery, idempotency, and wake-up mechanics are deferred to the mailbox and inter-agent communication topic.
- Define `wait_agent` as a synchronization tool over parent-observable child terminal results, not a transcript-scanning result-fetch tool. Concrete wake-up conditions, mailbox consumption, and delivery mechanics are deferred to the mailbox and inter-agent communication topic.
- Define `list_agents` as a Codex-aligned projection of the current root `SessionAgent` tree. It includes the root entry and child/nested entries in the same `root_session_agent_id` tree, with optional path-prefix filtering. Results use Codex-style fields: `agent_name` for the canonical path, `agent_status` for projected execution status, and `last_task_message` for the latest task/message preview.
- Define `interrupt_agent` as a current-run interrupt for the target subagent, not a close/delete operation. Interrupting a child does not remove its `SessionAgent` row or linked AgentSession; the child remains reusable through `followup_task`. Idle/completed target response details are left to the tool schema/error semantics implementation, but they must not imply a close lifecycle.

### Context fork semantics

Accepted so far:

- Keep `spawn_agent.fork_turns` validation and semantics identical to Codex. Allow only `"none"`, `"all"`, or positive integer strings such as `"1"`, `"3"`, and `"10"`. Reject `0`, negative numbers, non-integers, numeric JSON values, and unknown strings.
- Interpret `fork_turns="none"`, `fork_turns="all"`, and positive integer string values with Codex-identical context fork semantics. Do not redefine the per-value behavior in this ADR unless Azents later discovers an implementation conflict that requires an explicit divergence.
- Interpret `fork_turns="all"` relative to the parent's current model-input head, not the entire durable transcript from session creation. The fork copies the same current model-visible context range that parent run preparation would load: the head/compaction boundary content plus subsequent model-visible events.
- Interpret positive integer `fork_turns` values inside that same current model-visible range. They select the latest N turns available after the model-input head boundary; they must not scan pre-head durable history that normal parent run preparation would no longer include.
- `fork_turns="none"` starts the child with only the delegated spawn task and system/developer/runtime context needed for normal child run preparation; it does not copy parent conversation turns.
- Do not copy object storage blobs when forked parent context contains ModelFile-backed FileParts. Initial implementation degrades rich FileParts in forked transcript context into bounded text placeholders that preserve file name, media type, size, source event reference when available, and an explicit note that rich file bytes are not available in the child context.
- Keep child ModelFile creation out of context fork unless a later explicit file handoff design adds shared blob lifetime/reference handling. If a subagent needs file bytes, the parent should provide a runtime workspace path, import/export URI workflow, or another explicit handoff outside automatic context forking.

### Mailbox and inter-agent communication

Accepted so far:

- Keep `input_buffers` as the internal pending model-input storage used by SessionRunner promotion, but remove wake-up ownership from the InputBuffer abstraction. InputBuffer rows are not a public/direct ingress API.
- Do not implement a single category-switching session input ingress facade. Instead, introduce separate input-producing components for each domain source, and let each component use an internal input-buffer writer as a storage primitive.
- Split existing input producers into these components:
  - User message input component: input-box messages, new-session first messages, and edited user messages.
  - Turn action input component: slash-triggered TurnActions and session operation actions.
  - System reminder input component: goal continuations and legacy/deprecated background result injection.
  - Agent mailbox input component: agent-to-agent mailbox deliveries such as `send_message` and `followup_task`.
- Wake policy belongs to each input-producing component's fixed method semantics, not to a caller-provided option. Public/internal producers must ask for the domain operation they need; they must not pass `wake=true` or `wake=false` into a generic input-buffer API.
- Keep the low-level input-buffer writer responsible only for appending internal `input_buffers` rows and returning the created rows. It must not decide wake policy, mutate session run state, send broker wake-up signals, or own source-specific idempotency semantics.
- Keep ordering across heterogeneous inputs in the caller/orchestrator that owns the larger workflow. For example, new-session setup actions and the initial user message are ordered by the new-session creation/bootstrap flow, not by the TurnAction input component.
- Add Mailbox as an abstract inter-agent communication surface above the input-producing components. It does not introduce a separate mailbox table/state machine; durable visibility comes from target AgentSession input buffers and promoted target-session transcript events.
- `send_message` and `followup_task` both materialize target AgentSession input through the agent mailbox input component when the target child should observe the content on its next run. `send_message` does not wake the target session; `followup_task` wakes the target session. Broker messages remain payload-free wake-up signals.
- Treat Mailbox as an abstract agent-to-agent communication interface, not as a dedicated mailbox storage table or independent mailbox state machine. Agent-to-agent messages use target AgentSession input buffers and promoted target-session transcript events for durable input/output visibility.
- Use a single agent-to-agent input/event kind for mailbox materialization: `agent_message`. The promoted payload carries the specific `message_kind` such as `send_message` or `followup_task`, along with source/target `SessionAgent` IDs, source/target paths, and content.
- Define `wait_agent` around unread terminal child run results, not current idle snapshots. A parent `SessionAgent` tracks observation cursors per target child `SessionAgent` so a terminal child run result returned once by `wait_agent` is not returned again. If multiple children have unread terminal results, `wait_agent` may return them as a batch. If no unread terminal result exists, `wait_agent` waits for one of the targets to reach a terminal run result. The cursor advances only for results actually returned to the parent.
- Keep `wait_agent` target selection semantics aligned with Codex. Do not introduce Azents-specific target selection variants unless a later implementation conflict or product need requires an explicit divergence.
- Define `wait_agent` no-result and timeout behavior by target state. If unread terminal results already exist, return them immediately and advance observation cursors only for returned results. If no unread result exists but one or more targets are running, wait up to the tool timeout; on timeout, return a timeout response that includes which target agents are still running. If no unread result exists and no target is running, return an immediate empty result instead of waiting.

### Wait/list/interrupt lifecycle control

Accepted so far:

- Keep `list_agents` output aligned with Codex: include the root entry and return `agent_name`, `agent_status`, and `last_task_message` for each visible `SessionAgent`.
- Treat `agent_status` as a projection, not stored state on `SessionAgent`. Project `running` from linked `AgentSession.run_state` or latest running `AgentRun`; project `{ completed: ... }`, `{ errored: ... }`, and `interrupted` from the latest terminal `AgentRun` plus terminal transcript events. Map Azents `stopped` and `cancelled` terminal run statuses to Codex-style `interrupted`. Reserve `shutdown` for future lifecycle/debug use and avoid emitting it in normal `list_agents`; use `not_found` for target-operation responses, not normal list rows.
- Required source data exists or is planned without adding a duplicated status column: `AgentSession.run_state`, `AgentRun.status`, `AgentRun.run_index`, `AgentRun.last_completed_event_id`, event transcript payloads/model order, `SessionAgent.last_task_message`, and the wait observation cursor from parent `SessionAgent` to target child `SessionAgent`.
- Treat `SessionAgent.last_task_message` as the latest instruction/message preview, not as an unread marker. Set it for root entries to the root/main-thread label, set it on spawn from the initial task preview, and update it when `send_message` or `followup_task` delivers a new instruction/message to the target. Do not clear it when `wait_agent` returns a terminal result; unread state is tracked only by the wait observation cursor.
- Store the wait observation cursor on the target child `SessionAgent` row with `parent_observed_run_index` and `parent_observed_event_id`. These columns record the latest terminal run result returned to the parent by `wait_agent`. This assumes a single parent observer per `SessionAgent`; if future designs introduce multi-observer waits, move the cursor to a separate observation table.
- Keep the `wait_agent` result shape aligned with Codex v2: return `message` and `timed_out`. Encode unread terminal result summaries, timeout running-agent summaries, and immediate empty-result summaries in `message` rather than introducing an Azents-specific structured result array.
- Keep `interrupt_agent` response aligned with Codex-style `previous_status`. Interrupting a running target requests current-run interruption and returns the status observed before the request. Interrupting an idle/completed/failed/interrupted target is a no-close no-delete no-op that still returns the observed `previous_status`. Missing targets return `previous_status = "not_found"` rather than introducing an Azents-specific validation failure shape.
- Restrict `wait_agent`, `list_agents`, and `interrupt_agent` visibility to the current root `SessionAgent` tree. `list_agents` lists the root and child/nested entries in that tree, with path-prefix filtering resolved relative to the current agent path as in Codex. `wait_agent` and `interrupt_agent` targets outside the current root tree resolve as `not_found`; cross-root session control is not supported.

### Workspace and runtime sharing

Accepted so far:

- Keep Codex's shared workspace model as the baseline: child subagents share the same `AgentRuntime` and physical Agent Workspace as the parent by default.
- Do not introduce automatic per-subagent working directories or Git worktrees as a core subagent primitive. Separate worktree orchestration may create resources, but the default subagent model does not allocate one workspace/worktree per child.
- Introduce `SessionAgentContext` as the shared logical context for one root `SessionAgent` tree. It owns shared logical resources for the root and all child/nested subagents, while `AgentRuntime` remains the physical sandbox/lifecycle owner.
- Link every `SessionAgent` in the same root tree to the same `SessionAgentContext`. The context references the root `SessionAgent`, the owning `Agent`, the owning `Workspace`, and the referenced `AgentRuntime`.
- Create `SessionAgentContext` in the same transaction that creates the root `SessionAgent`. Root-only sessions also receive a context row because the active Project registry is context-owned even when no child subagent exists.
- Child and nested subagent creation reuses the parent tree's existing `SessionAgentContext`; it must not create or copy a separate context for each child.
- Limit `SessionAgentContext` owned mutable resources to the active Project registry and Azents-owned Git worktree allocation/cleanup rows. The context may reference the owning Agent, Workspace, root `SessionAgent`, and AgentRuntime, but those referenced resources keep their existing owners.
- Classify existing resource concepts as follows for this redesign:
  - `SessionAgentContext` owned and shared across the root tree: active Project registry rows and Azents-owned Git worktree allocation/cleanup rows.
  - `SessionAgentContext` referenced but not owned: Agent, Workspace, root `SessionAgent`, and AgentRuntime.
  - Individual `AgentSession` or run owned: transcript/events, input buffers, AgentRuns, pending command state, stop intent, action executions, Goal, Todo, Toolkit State, selected toolkit defaults, AGENTS.md / Claude Rules dedupe state, Skill projection/loading state, ModelFiles, and ModelFilePins.
  - Existing Agent/Workspace owned configuration: Toolkit configs/attachments, memory scope storage, Agent Project catalog entries, Project defaults, Project presets, model/provider settings, and access-control membership rows.
  - TTL/file-access resources with existing ownership: artifacts and exchange files.
- Treat root `SessionAgent` deletion as the database ownership boundary for deleting its `SessionAgentContext` and context-owned rows. In normal cascade ownership, root AgentSession deletion deletes the root `SessionAgent`, which then deletes the context-owned rows. Worktree filesystem cleanup policy is separate from database ownership and must be handled by the Git worktree cleanup lifecycle.
- Move the active Project registry from `AgentSession` ownership to `SessionAgentContext` ownership. Root and child subagents read the same registered Project set instead of copying `session_workspace_projects` rows per child session.
- Use clean migration names for the new context-owned tables instead of keeping legacy session-owned names with changed foreign keys. The Project registry table is `session_agent_context_projects`; the Azents-owned Git worktree table is `session_agent_context_git_worktrees`.
- `session_agent_context_projects` stores `session_agent_context_id` and `path`, with uniqueness on `(session_agent_context_id, path)`.
- Do not include `SessionWorkspaceProjectRegistrationRequest` in the new subagent model. The Project registration request feature has been removed, so this redesign does not introduce a context-owned replacement.
- Move Azents-owned Git worktree allocation and cleanup authority to `SessionAgentContext` ownership when the created worktree becomes a shared Project. `session_agent_context_git_worktrees` stores `session_agent_context_id`, optional linked `project_id`, source project path, starting ref, worktree path, branch metadata, lifecycle status, cleanup/failure summaries, and creation provenance.
- Keep creation provenance on shared worktree rows with fields such as `created_by_session_agent_id`, `created_by_agent_session_id`, and `action_execution_id` so the UI and transcript can explain where the resource came from.
- Keep transcript, run, input, action execution, Goal, Todo, Toolkit State usage, selected toolkit defaults, AGENTS.md / Claude Rules dedupe state, model files, artifacts, exchange files, and active Skill state scoped to the individual `AgentSession` or run where they belong.
- Do not treat [simplified-260627/ADR](./simplified-260627-simplified-file-lifecycle-policy.md)'s ModelFile "context-owned" terminology as ownership by `SessionAgentContext`. ModelFile retention follows the individual `AgentSession` model-input head and active run pins. Context forking must not share ModelFile rows through `SessionAgentContext`.
- Keep TTL file resources such as artifacts and exchange files outside `SessionAgentContext`. They remain workspace/agent/session/run-associated file-access resources with their own expiration policy, not shared root-tree resources.
- Keep Skill projection and loading session-scoped. Even though available Skills are discovered from registered Projects, subagents do not share a common Skill projection or active/adopted Skill revision through `SessionAgentContext`.
- Apply `SessionAgentContext` Project changes at deterministic run/turn boundaries. Project row mutations are persisted immediately, but already-running parent or child runs do not receive mid-run prompt/tool-context mutation. Each `AgentSession` reads the latest context Project set during its next run preparation or deterministic adoption boundary.
- Project changes do not share or force-update Skill projections across the tree. Each `AgentSession` continues to use its own Skill sync/adoption lifecycle after Project changes.
- Do not expose Project registration or removal as model-visible subagent collaboration tools. `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` never mutate the shared Project set.
- Mutate `SessionAgentContext` Projects only through user-facing API/UI flows or explicit operation TurnActions such as `create_git_worktree`. A child subagent that needs a new Project must ask the parent or user through normal agent messaging rather than registering it directly.
- Keep Agent-level Project presets, defaults, and catalog entries outside `SessionAgentContext`. They remain Agent-owned UI/path-memory projections for creating or browsing sessions, not the root-tree resource source of truth.

### Tool exposure and nested subagents

Accepted so far:

- Child subagents inherit the same configured tool access as the parent by resolving tools from the same `Agent` configuration and shared `SessionAgentContext`, but with the child's own `AgentSession` lifecycle and Toolkit State.
- Do not copy the parent run's resolved Toolkit instances or provider-facing tool catalog into the child. Toolkit instances remain owned by each child `AgentSession` lifecycle so run/turn-scoped values such as run id, actor user, publish hooks, stop checkers, and session-scoped Toolkit State do not leak from parent to child.
- Treat Codex-style "same tools" as same configured access under the child context, not byte-identical parent instance reuse. Ambient Azents boundaries such as workspace membership, Agent access, ToolkitConfig attachment, runtime provider policy, and `SessionAgentContext` Projects still apply.
- Exclude the Goal Toolkit from subagent-mode auto-binding by default. Goal idle continuation and Goal lifecycle control remain root/user-facing session behavior unless a later design explicitly opts subagents into their own Goal capability.
- Split the current memory auto-bound behavior into Memory Read and Memory Write Toolkit capabilities so subagent-mode permission is controlled at Toolkit granularity rather than by ad-hoc per-tool filtering inside one generic builtin toolkit.
- Allow Memory Read in subagent mode when memory is enabled. Memory Read exposes read/search behavior such as `list_memories`, `get_memory`, and `search_memories`.
- Exclude Memory Write from subagent-mode auto-binding by default. Memory Write exposes mutation behavior such as `save_memory` and `delete_memory`, and requires an explicit later design to grant it to subagents.
- Allow the remaining auto-bound tools in subagent mode, including runtime file/shell tools, AGENTS.md and Claude Rules appendix loaders, session-local Skill projection/loading, session-local Todo, and the subagent collaboration tools.
- Keep subagent collaboration tools available in subagent mode by default. Child subagents may call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`, enabling nested subagents within the same root `SessionAgent` tree.
- Toolkit State remains scoped to the child `AgentSession` for subagents. Toolkit State users such as Todo, Skill projection/loading, GitHub selected installation, AGENTS.md dedupe, and Claude Rules dedupe operate independently between parent and child sessions.
- Rename the current runtime-independent `builtin` auto-bound Toolkit concept into explicit Memory Read / Memory Write Toolkit capabilities in the redesign. Its purpose is memory prompt and memory tools, not generic builtin behavior.
- Use `runtime` as the slug/name for the Runtime Toolkit in the redesign instead of `shell`, because it exposes the broader runtime tool surface: process execution, file operations, exchange/artifact import/export, and runtime instruction appendices.

### Events, transcript, and model lowering

Accepted so far:

- Do not introduce separate parent-transcript durable summary events such as `subagent_created`, `subagent_message_sent`, `subagent_result_observed`, or `subagent_interrupted` for the core collaboration flow.
- The parent `AgentSession` transcript records subagent coordination through ordinary collaboration tool calls and tool results: `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents`.
- Treat those parent tool call/result events as the durable parent-side coordination and audit source of truth. For example, a `wait_agent` tool result records what child output the parent observed and when it observed it.
- Store child execution details only in the child `AgentSession` transcript. The child transcript is the source of truth for the child-visible input, child assistant output, child tool calls/results, run markers, and terminal child output.
- Store parent-to-child delivered input as a distinct `agent_message` event kind in the target child `AgentSession`, not as a user-authored `user_message` and not as a `system_reminder`.
- Use `agent_message` for initial spawn tasks, queue-only `send_message` deliveries that are materialized into the child transcript, and `followup_task` assignments. The payload records `message_kind` such as `spawn_task`, `send_message`, or `followup_task`, source/target `SessionAgent` IDs and paths, message content, and optional parent tool-call/event provenance.
- Lower `agent_message` into model input as user-role-compatible delegated task/message content with explicit source labeling such as "Message from parent agent /root". Parent agent messages are delegated task content, not higher-priority system/developer instructions.
- Store an explicit terminal result projection on each terminal child `AgentRun` for `wait_agent` consumption. Do not make `wait_agent` infer child output by scanning backward through the child transcript at read time.
- Create the `AgentRun` terminal result projection during run finalization from only that run's output/error/interruption boundary. The projection includes the terminal result kind, a parent-readable message, optional source event ID, and creation timestamp.
- If a completed child run has no final assistant message in that run, store an explicit fallback such as completed-with-no-final-message instead of falling back to an earlier run's output. Failed, stopped, interrupted, and cancelled runs store status-appropriate terminal result messages.
- `wait_agent` returns only stored terminal result projections newer than the parent observation cursor, then advances the cursor for results it returns. The parent transcript still stores the observation only as the `wait_agent` tool result.
- Build UI/live subagent tree projections by joining `SessionAgent`, linked `AgentSession` run state, latest `AgentRun` state, parent collaboration tool history, and child transcripts when detail views need them. Do not duplicate child lifecycle summaries into extra parent transcript events for projection convenience.
- Treat the DB projection as the source of truth for subagent tree UI state. Tree/list APIs reconstruct state from durable rows instead of reading a durable subagent summary event stream.
- Use non-durable live updates only as cache/invalidation or incremental UI update signals, not as source-of-truth state. Reconnect and refresh must recover the same subagent tree state from DB projection.
- Child detail views read the child `AgentSession` history/live APIs directly rather than relying on copied parent transcript summaries.

### Worker, broker, and run scheduling

Accepted so far:

- Use producer-owned fixed wake semantics for parent-to-child delivery. Tool callers do not pass a generic wake option.
- `spawn_agent` creates the child `AgentSession` and child `SessionAgent`, inserts the initial `agent_message` input for the child, and sends a broker wake-up for the child session.
- `followup_task` inserts an `agent_message` task assignment for the existing child session and sends a broker wake-up for that child session.
- `send_message` inserts an `agent_message` delivery for the target child session but does not send a broker wake-up. It remains queue-only communication.
- Broker wake-up signals remain payload-free. The recoverable source of truth for child work is the child session's pending input buffers and promoted `agent_message` transcript events.
- Treat user-facing stop/cancel as a subtree control operation. Stopping the root session interrupts the root run and all running child/nested `AgentSession` runs in the same root `SessionAgent` tree.
- Stopping from a child detail/control surface interrupts that child `AgentSession` run and running descendants in that child's subtree.
- Keep model-visible `interrupt_agent` target-scoped. It interrupts only the addressed child agent's current run, does not delete or close the child, and does not automatically interrupt descendants.
- Stop propagation must operate over durable `SessionAgent` tree membership and linked `AgentSession` run state rather than runtime process ownership alone.
- Treat parent and child `AgentSession` execution as fully independent at the session execution layer. Each session owns its own `AgentRun` rows, retry state, pending command state, stop intent, run heartbeat, and failed-run recovery path.
- Parent run retry/recovery must not automatically retry, replay, discard, or mutate child runs. Child run retry/recovery must not mutate parent run state.
- A failed child run is surfaced to the parent only through the child `AgentRun` terminal result projection and `wait_agent` observation. The parent may choose to send a new `followup_task`, and the user may retry from the child detail surface, but there is no implicit cross-session retry coupling.
- User-facing subtree stop is an orchestration operation over multiple independent sessions, not evidence that parent and child share one execution lifecycle.

### Frontend and observability

Accepted so far:

- Show subagent coordination inside the parent chat transcript through the actual collaboration tool call/result cards. `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` results remain visible as ordinary tool interactions.
- Add a projection-based Subagent Tree panel or section to the parent session UI. The panel shows the current root tree, nested child paths, projected status, last task/message preview, unread/observed result state when available, and child detail entrypoints.
- Keep the parent chat timeline source-aligned with the durable transcript. Do not insert synthetic durable-looking subagent lifecycle cards into the parent timeline beyond the actual tool call/result events.
- Build the Subagent Tree panel from DB projection and non-durable live update signals, not from copied parent transcript summary events.
- Provide child transcript inspection in two layers: a quick in-context detail surface from the parent session UI, and a full child detail route for long transcripts, refresh, deep links, and debugging.
- On desktop, the quick child detail surface may be a side panel or modal that preserves parent chat context. It reads the child `AgentSession` history/live APIs directly.
- On mobile, avoid cramped nested side panels. The Subagent Tree opens as a full-height drawer or dedicated screen, and selecting a child opens a mobile-friendly full-screen child detail view with a clear back path to the root session.
- Child `AgentSession` rows remain hidden from ordinary Agent session lists. Child detail routes are reachable only through the root session's subagent tree context or direct authorized deep links.
- Keep subagent tree projection separate from the root session chat `/live` payload. Provide a dedicated subagent tree projection API for the root `SessionAgent` tree instead of embedding the full tree in every chat live response.
- Use non-durable WebSocket/live signals such as `subagent_tree_changed` only as invalidation or incremental update triggers. On reconnect or refresh, clients refetch the dedicated tree projection API as the source of truth.
- The dedicated tree API may evolve independently with nested tree shape, projected status, last task/message preview, unread result indicators, and child detail links without expanding the core chat live contract.

### Rollout and compatibility

Accepted so far:

- There is no legacy subagent runtime/API compatibility target for this redesign. The previous implementation has been removed, so this work implements only the new `SessionAgent`-based model.
- Do not restore removed legacy subagent roles, routes, events, or tool wrappers as compatibility layers.
- Roll out implementation in foundation-first stacked phases rather than a single vertical slice. Persistent ownership boundaries and invariants must land before collaboration tools, worker scheduling, and frontend surfaces.
- Phase 1: DB/domain foundation. Add `session_agents`, `session_agent_contexts`, `session_agent_context_projects`, `session_agent_context_git_worktrees`, `agent_sessions.session_kind`, and `agent_runs` terminal-result projection fields, plus repository/domain invariants.
- Phase 2: context-aware Project/runtime/tool resolution. Move Project reads/writes and worktree allocation ownership to `SessionAgentContext`, update Runtime Toolkit project prompt loading, and keep Skill/Todo/Toolkit State session-scoped.
- Phase 3: collaboration tools and mailbox input. Implement `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` with `agent_message` input materialization and fixed wake semantics.
- Phase 4: worker, stop, wait, and recovery behavior. Implement child run scheduling, terminal result projection finalization, wait observation cursors, subtree user stop orchestration, and independent parent/child retry boundaries.
- Phase 5: frontend and observability. Add parent chat tool-card rendering support as needed, dedicated Subagent Tree projection API, tree panel/drawer, child quick detail, full child detail route, mobile full-screen flows, and live invalidation signals.
- Run spec review and update living specs after the staged implementation reaches a coherent behavior boundary, with final E2E/QA covering nested subagents, wait/interrupt, subtree stop, reconnect, and mobile detail navigation.
- Do not add a feature flag for the new subagent model. Once each staged implementation reaches its usable behavior boundary, expose it directly rather than maintaining a flag-gated compatibility or rollout path.
- Avoid partially exposing incomplete tool/API/UI surfaces during intermediate phases by keeping unfinished endpoints/tools unregistered until their phase is ready, not by hiding completed code behind a runtime feature flag.

## Consequences

- The new design prioritizes Codex mental-model compatibility over extra subagent-specific safety mechanisms.
- Implementation should focus on subagent identity, mailbox communication, and shared runtime semantics before specialized UI polish.
- Future specs must describe current behavior after implementation; this ADR records the baseline decision and topic map.

## Migration provenance

- Historical source filename: `0096-codex-first-subagent-redesign.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
