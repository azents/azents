---
title: "Optional Managed Runtime Phase 3 Session Bindings"
created: 2026-08-10
tags: [agent, runtime, session, workspace, project, git, backend]
---
# Phase Execution Plan

- Phase: `3 — Session bindings and Runtime-dependent surfaces`
- Branch/base: `azents/runtime-optional-capability-3-session-bindings` →
  `azents/runtime-optional-capability-2-runtime-free-core`
- PR boundary: Activate the durable Session working-folder binding lifecycle and
  replace stored-path authority across Runtime-backed Workspace, Project, Git,
  filesystem Skill, transfer, credential, Engine prompt/default-workdir, and
  archive-cleanup operations with capability/version, binding, and current Runner
  evidence.
- Inputs: Phase 2 commit `6806efe5c`; confirmed `runtime-260803/REQ`;
  accepted `runtime-260803/ADR-D1` through `ADR-D6`; approved
  `runtime-260803/DESIGN` revision 3; Phase 1 nullable context persistence and
  Phase 2 shared Agent capability resolver.
- Deliverables:
  - A root Session context created as `pending` can bind exactly once to one unique
    Session folder using the same logical Runtime and current-generation
    Runner-reported Workspace evidence.
  - Contexts in `none` or `invalidated` never bind, and a stored historical path is
    never sufficient authority for setup, prompt, browser, Project, worktree,
    Skill, transfer, credential, or cleanup work.
  - Runtime operation target resolution rejects Runtime-free, removing, stale
    capability-version, stale configuration/generation, disconnected Provider,
    stale Runner, and changed Workspace evidence before dispatch.
  - Agent Workspace operations require current managed capability and exact Runtime
    readiness without requiring a Session binding; Session-folder, Project, and
    worktree operations additionally require a current bound root context.
  - Engine Runtime prompts and default workdirs use only a current bound context.
    Pending contexts can acquire their binding only when the first authorized
    Runtime-dependent operation obtains current Runner evidence; projection alone
    does not start compute.
  - Filesystem Skill synchronization/materialization, Runtime transfer, and Runtime
    credential exposure retain Phase 2 capability checks and gain the applicable
    current binding/target recheck before Runner or credential side effects.
  - Archive cleanup remains independent: only a currently bound context may admit
    Runner folder cleanup. Runtime-free, pending, or invalidated contexts archive
    without dispatching a folder operation, while cleanup status remains the
    existing archive-owned enum.
  - Repository primitives needed by Phase 5 can terminally invalidate pending or
    bound contexts with bounded removal evidence, but this phase does not implement
    the removal coordinator or perform Agent-wide cleanup.
- Non-goals: Runtime add/rearm/control APIs, removal-operation orchestration,
  Agent-wide interruption, product cleanup batches, physical terminal deletion,
  public API/client changes, Web UX, E2E rollout, and Living Spec promotion.
- Interfaces:
  - One immutable Session working-folder authority projection contains context ID,
    Agent ID, logical Runtime ID, binding state, exact path when bound, and the
    Agent capability version captured for the operation.
  - Repository binding uses a locked compare-and-set from `pending` to `bound` and
    requires the expected context, logical Runtime, and null historical path.
  - Authoritative Session-folder resolution accepts current Runtime target evidence,
    validates the exact Runner Workspace root, and either returns an existing bound
    authority or performs the one allowed pending bind.
  - `none` and `invalidated` return stable fail-closed decisions; no helper exposes a
    nullable or historical path as usable authority.
  - Agent-global Runtime operations and Session-bound operations share the Phase 2
    server capability catalog but apply distinct context requirements.
- Approved Design mechanisms: `M4`, `M7`, `M13`, `M15`.
- Authority references: `runtime-260803/REQ-3`, `REQ-5`, `REQ-6`, `REQ-8`,
  `REQ-9`; `runtime-260803/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D4`;
  approved Design revision 3; current `workspace`, `agent-runtime-control`, and
  `agent-runtime-persistence` Specs.
- Design delta: `None`
- Removal obligations:
  - Replace mandatory/non-null or path-only Session folder authority.
  - Replace Runtime target resolution that can ensure/start a Runtime before
    checking current Agent capability.
  - Replace setup, browser, archive, Project, worktree, prompt/workdir, Skill,
    transfer, and credential paths that can use persisted historical paths or stale
    Runtime evidence.
  - Preserve archive cleanup state as a separate lifecycle rather than extending it
    into Runtime-removal authority.
- Absence verification:
  - Production consumers do not call a path-only
    `require_session_working_folder_path` authority helper.
  - Runtime-free or invalidated tests prove no Runtime ensure/start, credential
    collection, Runner dispatch, path normalization, or cleanup dispatch.
  - Pending-binding tests prove projection does not start compute and one current
    Runner-backed operation binds exactly once.
  - Stale capability/version, Runtime ID, generation, configuration digest, Runner
    Workspace, and binding-state tests fail before external side effects.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Binding authority and repository transitions | `root` | `repos/agent_session/`, `rdb/models/session_agent_context.py`, focused service boundary under `services/` | Phase 1 context fields and Phase 2 Agent capability snapshots | Locked pending bind, bound authority resolution, invalidation primitive, stable denied outcomes | Repository concurrency/CAS tests and binding service tests |
| Runtime target and Engine integration | `root` | `core/runtime_capabilities.py`, `services/agent_runtime/`, `engine/tools/{builtin,skill,claude_rules}.py`, `worker/run/executor.py` | Binding authority | Capability-fenced Runtime target, lazy pending bind on authorized use, bound-only prompt/workdir and Runtime-side projection | Runtime target, Runtime Toolkit, Skill, Claude Rules, Worker tests |
| Workspace, Project, Git, and browser fencing | `root` | `services/chat/workspace.py`, `services/project_browser_manifest.py`, `services/agent_{automatic_project,project_catalog}/`, `services/session_{workspace_project,git_worktree}/` | Runtime target and binding authority | Agent-global Workspace guard plus bound-only Session Project/worktree/browser operations | Focused service and stale-authority tests |
| Archive cleanup separation | `root` | `services/chat/__init__.py`, AgentSession repository cleanup methods | Binding authority | Bound-only cleanup admission; no Runner work for none/pending/invalidated contexts | Archive/restore/retention tests |
| Integration and phase documentation | `root` | Phase plan, research note, cross-surface integration | All workstreams | Stable Phase 3 diff and checkpoint | Ruff, format, ty, focused/full pytest, pre-commit, absence searches |

- Integration order: repository CAS and authority value → authoritative binding
  service → Runtime target capability fence → Engine lazy-bind and prompt/workdir →
  Workspace/Project/Git/browser consumers → archive cleanup → integration tests and
  absence verification.
- Independent review: `hardtack` performs one read-only review against M4/M7/M13/
  M15, focusing on path reuse, pending-bind races, stale capability/version or
  Runner evidence, pre-dispatch side effects, archive/removal lifecycle separation,
  and Phase 4/5 scope boundaries. Security/authorization corrections require a
  targeted re-review by the same reviewer.
- Final validation:
  - Focused AgentSession repository, binding service, Runtime target, Runtime
    Toolkit, Skill, Claude Rules, Worker, Workspace, Project browser/catalog,
    automatic/Session Project, worktree, and archive tests.
  - `uv run ruff check --fix .`, `uv run ruff format .`,
    `uv run ty check --error-on-warning`, and full `uv run pytest -q` in
    `python/apps/azents`.
  - Repository pre-commit, `git diff --check`, and exact stored-path/capability
    absence searches.
- Scope-drift check: Every behavior maps to M4/M7/M13/M15. This phase must not add
  Runtime transition APIs, removal orchestration, public contracts, Web behavior,
  feature rollout, compatibility fallback authority, or a second persisted
  capability catalog.
- Context checkpoint: Phase 2 activates Runtime-free model execution and Agent-only
  capability admission. Phase 3 makes Session and Runtime resource authority exact
  and stale-safe. Phase 4 will add explicit capability transitions; Phase 5 will
  consume the invalidation primitives in the irreversible removal coordinator.
