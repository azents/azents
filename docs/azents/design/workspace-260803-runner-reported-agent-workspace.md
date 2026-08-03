---
title: "Runner-Reported Agent Workspace Design"
created: 2026-08-03
implemented: 2026-08-03
tags: [runtime, workspace, runner, provider, backend, toolkit]
document_role: primary
document_type: design
snapshot_id: workspace-260803
---

# Runner-Reported Agent Workspace Design

- Snapshot: `workspace-260803`
- Document reference: `workspace-260803/DESIGN`
- Requirements: [Runner-Reported Agent Workspace Requirements](../requirements/workspace-260803-runner-reported-agent-workspace.md)
- ADR: [Runner-Reported Agent Workspace](../adr/workspace-260803-runner-reported-agent-workspace.md)

## Current Behavior and Gaps

Provider configuration chooses a mount path, injects it through
`AZ_AGENT_WORKSPACE_PATH`, reports the same value in lifecycle reports, and stores
it through the Provider state sink. Runner state only validates equality. Backend
workspace, Project, worktree, Toolkit, and publication units still contain
historical path constants, so the documented configurability is incomplete.

## Architecture and Ownership

1. Runtime infrastructure configures one durable mount and starts Runner with
   `HOME` and working directory set to that mount.
2. Runner resolves `--workspace-path` before `HOME`, validates and normalizes it,
   constructs its `Workspace`, and reports the value in existing registration and
   state messages.
3. Runtime Control validates the current-generation Runner value and persists it
   with Runner state in `agent_runtimes.workspace_path`.
4. Backend and Toolkit consumers load that value from `AgentRuntime`, normalize it
   once, and pass it explicitly into path-boundary helpers.

Provider reports retain lifecycle, persistence, configuration, and backend
identity evidence only.

## Runtime and Protocol Changes

- Remove `workspace_path` from `RuntimeProviderReport`, reserve its protobuf field,
  and remove Provider registration capability/metadata that advertises it.
- Remove Provider workspace missing and Provider/Runner mismatch failures.
- Extend Runner-state persistence to atomically store validated
  `workspace_path`.
- Runner startup exposes `--workspace-path`; absent input uses `HOME`.
- Docker and Kubernetes Providers set `HOME` and working directory from their
  configured workspace mount. The Docker Provider requires explicit mount
  configuration rather than embedding a Python default.
- The Runner image uses an ordinary image user home for standalone execution and
  does not identify the historical Runtime mount as a product constant.

No database migration is required because the nullable text column already exists.

## Backend Path Propagation

- Shared Agent Workspace path helpers validate absolute roots and descendants.
- Session Project normalization requires an explicit root.
- Agent project catalogs, automatic projects, root/session creation, browser
  manifests, and Git worktree services load the owning AgentRuntime root before
  validation.
- Generated worktrees use `<reported-root>/.azents/worktrees`.
- Agent-level Skills use `<reported-root>/.azents/skills`,
  `<reported-root>/.agents/skills`, and
  `<reported-root>/.claude/skills`.
- Runtime instruction context carries the root for AGENTS.md and Claude rules
  discovery.
- `present_file` receives the root from the ready Runtime and permits only strict
  descendants.
- Agent Workspace API path parsing continues to use `AgentRuntime.workspace_path`
  but removes its default root.

## Prompt and API Surface

Static Shell tool descriptions use phrases such as "absolute path in the Agent
Workspace" and do not include a deployment-specific path. Runtime Toolkit dynamic
prompt rendering displays the current reported root and registered Project paths.
API field descriptions refer to the owning Agent Workspace rather than a concrete
directory.

Generated public clients remain unchanged in this PR.

## Failure, Retry, and Recovery

- Runner startup fails before Control connection when neither explicit input nor a
  valid absolute `HOME` is available.
- Runtime Control records `RUNNER_WORKSPACE_PATH_MISSING` or
  `RUNNER_WORKSPACE_PATH_INVALID` and marks Runner state failed if malformed
  external evidence reaches the sink.
- A later valid current-generation Runner report replaces the stored root and can
  clear the current workspace-evidence failure.
- Provider stop/restart behavior and Agent Workspace persistence are unchanged.
- Paths stored under another root remain visible as persisted records but fail
  current-root validation; there is no rewrite or fallback.

## Security and Permissions

All user-facing destructive and publication operations remain confined to the
current Runner-reported root. Absolute Runner filesystem operations outside the
root remain available only where their existing tool contract already permits
them; they do not become Agent Workspace Projects or publishable durable files.

## Rollout and Rollback

Server, Runner, and bundled Providers are released together. Existing provider
configuration continues to choose the same mount by deployment values, so existing
data layout does not move. Rollback restores the previous Provider-authoritative
metadata behavior without schema changes.

## Observability

Runner startup and state logs include the resolved workspace path. Runtime failures
distinguish missing and invalid Runner evidence. Provider logs no longer claim
workspace metadata authority.

## Test Strategy

- Runner unit tests cover explicit input precedence, `HOME` fallback, normalization,
  and invalid values.
- Runtime Control tests prove Runner evidence persists the root and Provider
  reports do not mutate it.
- Docker/Kubernetes Provider tests prove mount, `HOME`, and working-directory
  configuration with an alternate path.
- Backend tests exercise Project, browser, worktree, Skill, AGENTS/rules, workspace
  API, and publication behavior with alternate roots.
- Static-source checks reject the historical path from production code and prompts
  while allowing deployment fixtures and explicit compatibility history.
- Focused Python, Helm, OpenAPI drift, and deterministic E2E checks validate the
  integrated change.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `workspace-260803/REQ-1` | M1, M3 |
| `workspace-260803/REQ-2` | M1 |
| `workspace-260803/REQ-3` | M2 |
| `workspace-260803/REQ-4` | M3, M4 |
| `workspace-260803/REQ-5` | M1, M3 |
| `workspace-260803/REQ-6` | M5 |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Persist validated current Runner workspace evidence and remove Provider workspace metadata authority. | `workspace-260803/REQ-2`, `workspace-260803/ADR-D1` | `decided` |
| M2 | Resolve Runner workspace from explicit startup input and then `HOME`. | `workspace-260803/REQ-3`, `workspace-260803/ADR-D2` | `decided` |
| M3 | Explicitly propagate the current root through every Agent Workspace path boundary with no fallback or rewrite. | `workspace-260803/REQ-1`, `REQ-4`, `REQ-5`, `workspace-260803/ADR-D3` | `decided` |
| M4 | Remove deployment-specific paths from static schemas and render the current root only in dynamic guidance. | `workspace-260803/REQ-4`, `workspace-260803/ADR-D3` | `decided` |
| M5 | Validate alternate roots across Runtime, Provider, backend, Toolkit, and deployment surfaces. | `workspace-260803/REQ-6` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Provider report `workspace_path`, registration capability, and server Provider-path failures | M1 | Runner registration/state evidence | Provider protocol, shared models, providers, sink, tests, specs | Provider reports cannot mutate `agent_runtimes.workspace_path` |
| Runner-required `AZ_AGENT_WORKSPACE_PATH` and image Runtime-home constant | M2 | `--workspace-path` then `HOME` | Runner startup, image, Provider process configuration | Runner tests pass without the legacy environment variable |
| Server and Toolkit Agent Workspace path constants | M3 | Explicit root parameters loaded from `AgentRuntime` | Project, worktree, browser, Skill, instruction, workspace, publication units | Production-source scan contains no historical Agent Workspace constant |
| Static prompt/schema concrete path examples | M4 | Generic static guidance plus dynamic Runtime root prompt | Shell tools, API descriptions, OpenAPI source | Prompt/schema tests and source scan |
| Provider-authoritative current Specs | M1, M3 | Runner-authoritative Living Specs | Workspace, Toolkit, Runtime Control, persistence specs | Spec review and updated verification dates |

## Feasibility

- M1 is feasible because Runner registration/state already transports
  `workspace_path` and the existing DB column can be updated by the Runner sink.
- M2 is feasible because both Provider implementations already control Runner
  environment and working directory.
- M3 is feasible because affected services already load or can load AgentRuntime;
  Runtime Toolkit already builds a per-turn instruction context.
- M4 and M5 are local schema, prompt, and test changes with no external dependency.

No implementation blocker or unresolved material decision remains.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-03`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: Runner-authoritative Agent Workspace path resolution, storage,
  propagation, fixed-path removal, and regression validation.
