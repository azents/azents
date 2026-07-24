---
title: "Team Session execution boundaries phase 3: userless Engine and capability projection"
created: 2026-07-24
tags: [session, authorization, engine, toolkit, memory, security]
---

# Team Session execution boundaries phase 3: userless Engine and capability projection

## Phase Execution Plan

- Phase: `3 — Userless Engine and Team capability projection`
- Branch/base: `feature/team-session-userless-engine` → `feature/team-session-canonical-execution`
- PR boundary: generic execution-contract User removal, source-stable Session Toolkit lifecycle, and Team-only capability projection
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Multi-phase plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)

## Deliverables

- `InputMessage`, `InvokeInput`, `RunContext`, `ToolkitContext`, `ResolveContext`, and `TurnContext` have no `user_id` field.
- Team runtime removes `SessionType.USER` / `SessionType.SYSTEM` inference and obsolete interface context carriers.
- Session-managed Toolkit lifecycle keys use stable Toolkit source identity and source revision, not a Human sender or a system fallback identity.
- Normal execution, recovery, idle continuation, scheduler, and subagent paths construct the same Userless generic Engine and Toolkit contexts.
- Team capability resolution uses Workspace Toolkit configuration, Agent attachment, Toolkit-level OAuth, Workspace model integration, Runtime, Session, Goal, Todo, Skill, External Channel, system, and subagent authority without User identity.
- Team Runs project Agent-scope Memory only. User-scope Memory remains reachable only through requester-authorized management APIs.
- Runtime resolution does not retain MCP per-user OAuth or GitHub per-user PAT fallback behavior.

## Non-goals

- Resource ownership, Exchange provenance, ModelFile lineage, Artifact creation, Runtime file materialization, MCP Artifact persistence, and provider-output Userless conversion. Those are Phase 4 work.
- User Session persistence, User capability construction, User-brought Tools, or personal credential design.
- Public requester authorization, OAuth management, or sender provenance semantics.
- Broker, canonical execution snapshot, migration replay, cutover, E2E, and living-spec promotion work.

## Stacked Transition Boundary

This phase is a coordinated-cutover prerequisite and is not independently deployable. Until phase 4
adds Session/Run resource authority:

- transcript FileParts lower through the existing unavailable-content placeholder when no
  request-local ModelFile materialization is authorized;
- MCP resources retain their text or unsupported-content fallback instead of creating Artifacts;
- resource-producing provider and client outputs remain unavailable; and
- no path may recover those capabilities by inferring or falling back to a User.

## Boundary Contract

A Team Run has only canonical Session, Agent, Workspace, SessionAgent tree, Run, Runtime, Toolkit source, and system authority. An authenticated requester authorizes a public operation, and a Human sender remains metadata on one admitted input; neither identity enters generic Engine or Toolkit contracts.

Session Toolkit reuse is keyed by a Toolkit source identity. A changed source revision replaces the entered Toolkit instance. The same source and revision reuse the same instance regardless of Human sender, External Channel invocation, recovery, continuation, or subagent execution.

## Workstreams

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Generic contracts | `src/azents/core/tools.py`, `src/azents/engine/run/**`, Engine context constructors | Userless generic context types and call sites | constructor/type coverage |
| Session lifecycle | `src/azents/worker/session/toolkit_scope.py`, `src/azents/worker/session/runner.py`, `src/azents/engine/tooling/session_toolkits.py` | source-stable Toolkit reuse | sender/recovery/continuation lifecycle tests |
| Capability projection | `src/azents/engine/run/resolve.py`, `src/azents/engine/tools/**` | Team capability set with Agent-only Memory | Memory, MCP, GitHub, Runtime, Goal/Todo/Skill, subagent tests |
| Regression coverage | affected backend tests | removal and behavior proofs | Ruff, Pyright, focused pytest, diff check |

## Final Validation

- Focused Ruff format/check and Pyright from `python/apps/azents`.
- Focused pytest for Engine contracts, resolve, Session Toolkit lifecycle, Memory, MCP/GitHub, Runtime, Goal/Todo/Skill, subagent, continuation, and Worker boundaries.
- `git diff --check`.
- Scope review confirming no Phase 4 Userless resource-authority behavior is pulled forward and requester-aware management/OAuth APIs retain their explicit public boundary.
