---
title: "Abandoned Multi-Active AgentSession Migration Overview"
tags: [backend, engine, architecture, migration]
created: 2026-06-25
updated: 2026-06-25
---

# Abandoned Multi-Active AgentSession Migration Overview

## Status

This design is abandoned before implementation.

It is superseded by:

- [ADR-0074: Primary Agent Sessions and Team-First Multi-Session UX](../adr/0074-primary-agent-sessions.md)
- [Primary Agent Sessions Target Design](./primary-agent-sessions.md)
- [Primary Agent Sessions Migration Phases](./primary-agent-sessions-migration-phases.md)

## Why This Was Abandoned

This document treated multi-active sessions mostly as the direct removal of the old single-current-session model. That was incomplete.

The revised model keeps the product value of the old single-session behavior through a stable **team primary session**, while still removing runtime-owned current-session state. The old design also did not account for session-owned projects or the explicit decision to defer private sessions, git worktree automation, and primary clear semantics.

The migration target is now:

- `AgentRuntime` and `AgentSession` are sibling models under `Agent`.
- Runtime owns physical workspace and lifecycle only.
- Session owns transcript, input, run state, and projects.
- Each agent has a team primary session.
- Additional team sessions can be created explicitly.
- The Web selected session is route state.
- Private sessions are target-compatible but implementation-deferred.
- Git worktree automation and primary clear semantics are future features.

Do not use this abandoned document for implementation planning.
