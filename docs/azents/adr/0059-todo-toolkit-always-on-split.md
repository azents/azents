---
title: "ADR-0059: Split TodoToolkit as Always-on Toolkit"
created: 2026-06-13
tags: [backend, engine, frontend]
---

# ADR-0059: Split TodoToolkit as Always-on Toolkit

## Context

ADR-0058 decided to expose session Todo through existing Toolkit State and Chat Live State. Initial implementation placed `update_todo` inside builtin toolkit. However, todo has a different nature from builtin tool bundles such as shell/file/memory. It is not a feature users toggle in Toolkit settings UI; it is session-scoped control state for consistently showing progress of long-running work in every session.

Also, UI requirement is not to show todo as transcript tool card, but as one-line checklist preview attached immediately above input box and as read-only list modal.

## Decision

Split Todo into a separate always-on toolkit named `TodoToolkit`.

- `TodoToolkit` is not exposed in user Toolkit config UI.
- `TodoToolkit` is automatically bound in worker resolve path, like shell/builtin.
- `update_todo` tool name is exposed as-is without prefix.
- Todo item has only `content` and `status`. Do not add stable ID or ID-based reference operations.
- Todo Toolkit State namespace is `todo`, and state name is `todo`.
- When subagent updates todo, it also updates parent agent/session todo state.
- Chat UI does not render `update_todo` tool call/result as transcript card.
- Chat UI reads only `todo` from live/projection snapshot and displays it in one-line checklist preview and modal above input box.

## Consequences

- Todo can evolve independently from builtin memory/root AGENTS prompt.
- There is no path for users to remove TodoToolkit through settings or add prefix.
- Even if `update_todo` call remains as transcript event, user UI treats it as control state update.
- Existing Toolkit State store and Chat Live State flow remain in use, so no separate todo table/API is added.
