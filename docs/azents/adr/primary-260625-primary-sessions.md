---
title: "Primary Agent Sessions and Team-First Multi-Session UX"
created: 2026-06-25
tags: [architecture, backend, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: primary-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0074-primary-agent-sessions.md"
---

# primary-260625/ADR: Primary Agent Sessions and Team-First Multi-Session UX

## Context

Azents originally forced an agent-centered single-session model. That decision was intentional.

Single-session benefits:

1. **External communication continuity** — Slack, GitHub, alerts, issue comments, and other external interfaces often participate in one workflow. If every external channel or thread becomes a separate session, context does not naturally move from Slack discussion to code work to PR review and back to Slack. Requiring users to understand and choose session IDs for integrations is not acceptable product UX.
2. **Short-term working context continuity** — Users often perceive the same agent as one contributor. If related alert or PR work is split into multiple hidden sessions, users expect knowledge to transfer but it will not. Long-term memory is not a good substitute for short-term session context sharing because the agent cannot know what another session needs in real time.
3. **Agent as an individual contributor** — The product direction is that an agent becomes an IC-like teammate. It must accumulate feedback from its own work, PR reviews, corrections, and team preferences. Overly ephemeral sessions weaken that feedback loop.

However, the single-session model also creates hard limitations:

1. **Parallelism** — A development agent that can only do one thing at a time is too constrained. Creating many separate agents is not a good substitute because agent creation, runtime resources, configuration, and accumulated expertise are not cheap.
2. **Privacy** — Even for a team agent, not every interaction should be visible to the team. A user may want to ask the same agent a private question, use a different language, draft something before sharing, or use user-specific credentials without putting the conversation in a team transcript.
3. **Scheduled/background work isolation** — Scheduled work should not interrupt an unrelated user conversation in the same transcript.

The target must preserve the continuity benefits of single-session usage while allowing explicit parallel sessions later.

## Decision

### primary-260625/ADR-D1 — Runtime and session are sibling models under Agent

`AgentRuntime` and `AgentSession` are both owned by `Agent`.

Target ownership:

- `AgentRuntime` owns physical runtime workspace, provider lifecycle, runner connectivity, sandbox identity, and runtime control-plane state.
- `AgentSession` owns transcript, input buffers, run state, heartbeat, pending commands, stop requests, goal/todo/toolkit session state, history/live streams, and session project registrations.

`AgentSession` must not be modeled as a child of `AgentRuntime`. Runtime-owned session selection, including `AgentRuntime.current_session_id` and runtime-keyed active session lookup, is implementation debt and must be removed.

### primary-260625/ADR-D2 — Team primary session is the continuity-preserving default

Each agent has one non-deletable **team primary session**.

Product meaning:

- It is the default team-visible conversation for the agent.
- It is the default target for shared external channels, such as Slack channels, GitHub events, shared alerts, and other non-private integration inputs.
- It is the continuity-preserving replacement for the old single active session behavior.
- It can be cleared in a future feature, but not deleted.

Early implementation should focus on team sessions only.

### primary-260625/ADR-D3 — Private sessions are target-compatible but implementation-deferred

Private sessions are not required in the first implementation phase.

The target model must still leave room for future private sessions:

- A future user-specific primary session can exist for each `(agent_id, user_id)`.
- Slack DM and other private external inputs should eventually route to the user's private primary session.
- Private session content must not automatically become team-visible transcript or team-shared durable memory.

For the initial implementation, all user-visible sessions can be treated as team-visible. Do not implement private session authorization or private session routing until the product scope is explicitly opened.

### primary-260625/ADR-D4 — Session list UX is divided into Team and Private sections

The eventual session list UX is organized by visibility sections, not as a single mixed list with ambiguous visibility.

Target UX shape:

```text
Team sessions
  Team primary session
  Team session A
  Team session B
  + New team session

Private sessions
  My private primary session
  Private session A
  Private session B
  + New private session
```

The first implementation may only show the Team sessions section. Private sessions are a future extension.

This avoids ambiguous creation flows. Users do not create a generic "new session" and then wonder whether it is team-visible or private. The section and button define the visibility.

### primary-260625/ADR-D5 — Selected Web session is route state

The selected Web UI session is represented by route state, not runtime state.

Canonical target shape:

```text
/w/{handle}/agents/{agent_id}/sessions/{session_id}
```

The agent chat root route may resolve to the team primary session and redirect or replace navigation to the canonical session URL.

### primary-260625/ADR-D6 — External routing defaults to primary sessions and hides arbitrary mappings

Do not expose arbitrary external channel to session mapping as a primary user concept.

Initial routing rule:

```text
shared external input -> team primary session
```

Future private routing rule:

```text
private external input -> user's private primary session
```

User-editable channel/session mapping is rejected for the initial product direction because it would make the product hard to understand. Any future override must be introduced as a narrow workflow action, not as a general mapping table users are expected to manage.

### primary-260625/ADR-D7 — Primary session is not runtime current session

The old `active-session` vocabulary represented two different things:

- Product default conversation behavior.
- Runtime-owned `current_session_id` selection.

The product default behavior remains necessary until multi-session UX is fully available. The runtime-owned selection part must be removed.

During migration, existing active-session APIs may be kept as compatibility entrypoints only if they resolve the agent's primary session without reading or writing runtime current-session state. The target terminology should move toward primary/default session vocabulary.

### primary-260625/ADR-D8 — Projects are session-owned working context

Project registrations belong to `AgentSession`, not to `AgentRuntime`.

Target meaning:

- A project is a repo/path working context registered for one session.
- The runtime owns the physical workspace where paths live.
- The session owns the list of projects it uses inside that workspace.
- Multiple sessions may register projects that point to the same physical path.
- A session may have multiple projects when a task spans multiple repositories.

Do not introduce runtime-owned current project, selected project, or active project state.

### primary-260625/ADR-D9 — New sessions copy projects from the team primary session

When a new team session is created, it starts with a snapshot copy of the team primary session's project registrations.

This keeps newly created sessions useful without making projects runtime-global. The copied projects are session-owned rows after creation. Later changes to the primary session's project list do not automatically mutate existing sessions.

### primary-260625/ADR-D10 — Git worktree automation is deferred

Git is not currently a first-class Azents domain; it is available through runtime shell tools.

The target model does not require automatic git worktree creation for session independence. A future feature may add explicit worktree creation and then register the created path as a session project. That automation is not part of this decision.

### primary-260625/ADR-D11 — Primary clear behavior is deferred

Primary sessions are non-deletable. A future clear/reset feature may define how old transcript, input buffers, goal/todo state, and context windows are hidden, archived, or generation-split. This ADR does not decide clear semantics.

## Rejected Options

### Channel-per-session routing as default

Rejected. It breaks cross-channel workflow continuity and makes Slack/GitHub/alert knowledge transfer difficult.

### User-managed arbitrary channel/session mappings

Rejected for the initial product. It is powerful but too hard to understand. Users should not need to understand session IDs or mapping tables to connect Slack, GitHub, and alerts to an agent.

### Cross-session short-term awareness layer

Rejected for the current direction. The main hidden-context problem comes from routing related external events to different sessions. If external routing sends related inputs to the correct primary session, a separate cross-session short-term context sharing layer is not needed initially.

### Removing active-session behavior immediately

Rejected. Multi-session is not fully available yet, and external integrations still need a default session target. Remove runtime-owned active/current implementation, not the product default-session behavior.

### Complex user-facing session taxonomy

Rejected. Do not expose work/scheduled/system/private/team as a large user-facing taxonomy. The primary user-facing split should be Team sessions first, with Private sessions as a future section.

### Runtime-owned project catalog or current project state

Rejected. It recreates hidden runtime-global selection state. Projects are session working context.

## Current Implementation Findings

The current codebase still has several gaps relative to this decision:

- `agent_sessions.agent_runtime_id` is still present and required. This is target-model debt because session ownership should be through `agent_id`, not through runtime.
- The current unique active-session constraint is runtime-keyed (`agent_runtime_id WHERE status = 'active'`). The target needs team primary-session uniqueness by agent, and later user-private primary uniqueness by `(agent_id, user_id)`.
- Current Web Agent Chat does not have a session ID in the route.
- Existing session list API is workspace-wide and does not expose agent-scoped team session ordering or primary placement.
- Current system scheduler implementation is system-periodic infrastructure, not the user-facing scheduled-agent-work product described by older ADRs.
- Older design documents contain several historical directions such as thread-per-session or run-per-session. This ADR supersedes those directions for the primary agent session product model.

## Consequences

Implementation should be phased around these architectural constraints:

1. Preserve or restore default session behavior as team primary behavior.
2. Remove runtime-owned session selection.
3. Introduce agent-owned primary session invariants.
4. Make projects session-owned.
5. Add URL-selected Web session routing.
6. Add multiple team sessions.
7. Defer private sessions, private visibility enforcement, git worktree automation, and primary clear semantics until the team-session model is stable.

## Migration provenance

- Historical source filename: `0074-primary-agent-sessions.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
