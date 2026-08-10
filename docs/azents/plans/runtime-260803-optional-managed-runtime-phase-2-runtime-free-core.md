---
title: "Optional Managed Runtime Phase 2 Runtime-free Core"
created: 2026-08-10
tags: [agent, runtime, engine, worker, toolkit, backend]
---
# Phase Execution Plan

- Phase: `2 — Runtime-free core`
- Branch/base: `azents/runtime-optional-capability-2-runtime-free-core` →
  `azents/runtime-optional-capability-1-foundation`
- PR boundary: Activate Runtime-free Agent creation and model-only Session admission,
  introduce one server-owned Runtime capability catalog/resolver, make Runtime
  execution identity optional, and filter Runtime-dependent Worker/Engine/Toolkit
  projection and admission while retaining compatible model, remote Toolkit,
  managed VFS Skill, Memory, Goal, Todo, subagent, attachment, and External Channel
  execution.
- Inputs: Phase 1 persistence foundation commit `5c47f2306`; confirmed
  `runtime-260803/REQ`; accepted `runtime-260803/ADR-D1` through `ADR-D6`;
  approved `runtime-260803/DESIGN` revision 3.
- Deliverables:
  - Omitted or null Runtime Profile creates a `none` Agent without consulting the
    Workspace default and persists `shell_enabled=false`.
  - Explicit available Profile creation remains `managed`, preserves the explicit
    shell choice, and schedules configuration reconciliation without allocating
    active compute.
  - Human model input and empty-workspace root Session creation work with no
    AgentRuntime row; internal Runtime identity is nullable.
  - Managed Agents may retain conditional logical Runtime ensure, while `none` and
    `removing` never ensure Runtime from model-only admission.
  - Root Session context creation can create an unbound Runtime-free context and a
    pending managed context without inventing a filesystem path; Phase 3 owns later
    binding transitions and resource authority.
  - One immutable server capability catalog and resolver combines Agent capability,
    capability version, and `shell_enabled` for both projection and authoritative
    admission.
  - Runtime Toolkit, Runtime prompts, Claude rules filesystem hooks, filesystem
    Skill synchronization/loading, and Runtime credential environment collection
    are suppressed or rejected before Runtime ensure, Profile resolution, secret
    collection, or Runner dispatch when capability is unavailable or stale.
  - Runtime-independent and managed-VFS functionality remains available.
- Non-goals: Session binding/rebinding/invalidation lifecycle, Project and worktree
  authority implementation, Runtime add/rearm/control APIs, removal coordination,
  unified public Runtime read model, generated clients, Web UX, E2E rollout, and
  Living Spec promotion.
- Interfaces:
  - Stable server-only Runtime capability identifiers and pure resolver decisions.
  - Exact Agent Runtime capability/version snapshot passed from Worker projection
    into Runtime-dependent Toolkit admission.
  - Nullable `agent_runtime_id` in internal input results.
  - Root Session context initialization for `none`, `pending`, or currently `bound`
    state; no fixed path fallback.
  - `resolve_agent_tools` receives capability projection rather than a shell-only
    boolean authority.
- Approved Design mechanisms: `M1`, `M4`, `M8`, `M9`, `M15`.
- Authority references: `runtime-260803/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`,
  `REQ-6`, `REQ-9`, `REQ-10`; `runtime-260803/ADR-D1`, `ADR-D4`, `ADR-D5`;
  approved Design revision 3.
- Design delta: `None`
- Removal obligations:
  - Remove new-Agent Workspace-default Runtime selection.
  - Replace unconditional input-time AgentRuntime ensure with capability-aware
    optional Runtime identity.
  - Replace `shell_enabled` as complete Runtime authority with the shared resolver.
  - Remove Runtime-dependent prompt, filesystem Skill, hook, and credential
    projection from Runtime-free and removing runs.
- Absence verification:
  - Agent creation contains no unconditional managed assignment or Workspace-default
    Runtime Profile resolution.
  - Runtime-free input tests assert no `ensure_for_agent`, Runtime row, Runtime ID,
    Runtime setup action, or filesystem path.
  - Worker contains no `runtime_tools_enabled=agent.shell_enabled` authority.
  - Denied Runtime bindings never reach `build_tool_catalog`/`update_context`.
  - Filesystem Skill and credential collection paths fail before Runtime/Runner
    access, while `azents://` Skill tests continue to pass.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Capability catalog and Toolkit admission | `phase2-capability-catalog-scout` | `python/apps/azents/src/azents/core/runtime_capabilities.py`, `services/runtime_capability/`, `engine/run/resolve.py`, `engine/tools/{builtin,skill,claude_rules}.py`, focused tests | Phase 1 Agent state/version | Shared projection/admission resolver, Runtime/Skill/hook/env guards | Resolver, resolve, builtin, Skill, Claude rules tests; Ruff/ty |
| Agent and Session admission | `phase2-agent-runtime-admission-scout` | `services/agent/`, `services/agent_session_input.py`, `services/root_agent_session_creation/`, `repos/agent_session/`, focused tests | Capability interface | Runtime-free defaults, optional identity, initial none/pending/bound context | Agent/input/root/repository tests; absence searches |
| Worker integration | `phase2-worker-engine-scout` | `worker/run/executor.py`, `worker/run/executor_test.py` | Capability interface and Toolkit resolver | Capability snapshot propagation for active and idle-continuation paths | Worker focused tests; log/assertion updates |
| Integration and phase documentation | `root` | Phase plan, research note, cross-workstream integration, final fixes | All workstreams | Stable Phase 2 diff and checkpoint | Pre-commit, Ruff, format, ty, focused/full pytest, diff checks |

- Integration order: Capability value types and pure resolver → Agent/Session
  admission and initial context state → Toolkit guards and managed Skill split →
  Worker active/idle propagation → integration tests and absence verification.
- Independent review: `hardtack` reviews the complete Phase 2 diff against M1/M4/
  M8/M9/M15, with emphasis on stale capability-version rejection, no Runtime or
  credential side effects before admission, Runtime-free Session correctness,
  managed-VFS preservation, and Phase 3 resource-fencing boundaries.
- Final validation:
  - Focused Agent, input, root Session, AgentSession repository, capability,
    resolve, Runtime Toolkit, Skill, Claude rules, Worker, subagent, External Channel,
    and model-only execution tests.
  - `uv run ruff check .`, `uv run ruff format --check .`, and
    `uv run ty check --error-on-warning` in `python/apps/azents`.
  - Full `uv run pytest -q` in `python/apps/azents`.
  - Repository pre-commit, `git diff --check`, and exact absence searches recorded
    in the phase checkpoint.
- Scope-drift check: Every activated behavior maps to M1/M4/M8/M9/M15. The phase
  must not implement Phase 3 current-Runner Session binding authority, Phase 4
  transition APIs, Phase 5 cleanup, or Phase 6+ public/Web contracts. It must not
  add persisted capability catalog state, legacy fallback authority, or a second
  execution path.
- Context checkpoint: Phase 1 supplies durable capability/version and nullable
  context fields. Phase 2 activates Runtime-free model execution and shared product
  capability policy. Phase 3 will add exact Session binding and resource-specific
  authority; Phase 4 will add explicit transition/control semantics; Phase 5 will
  coordinate irreversible removal.
