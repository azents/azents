---
title: "Codex Goal Pursuing Research"
created: 2026-06-13
tags: [agent, runtime, research]
---

# Codex Goal Pursuing Research

## Scope

This note reviews goal pursuing implementation in public `openai/codex` repository and applicability to Azents. Reference commit is `f297b9f07de10c7d8b9ed284b674d06cc5ff7723`.

## Main Paths Reviewed

- `codex-rs/ext/goal/src/spec.rs`
- `codex-rs/ext/goal/src/tool.rs`
- `codex-rs/ext/goal/src/runtime.rs`
- `codex-rs/ext/goal/src/extension.rs`
- `codex-rs/ext/goal/src/accounting.rs`
- `codex-rs/ext/goal/src/steering.rs`
- `codex-rs/ext/goal/templates/goals/continuation.md`
- `codex-rs/ext/goal/templates/goals/budget_limit.md`
- `codex-rs/ext/goal/templates/goals/objective_updated.md`
- `codex-rs/state/src/model/thread_goal.rs`
- `codex-rs/tui/src/chatwidget/goal_menu.rs`
- `codex-rs/tui/src/goal_display.rs`
- `codex-rs/tui/src/bottom_pane/footer.rs`

## Core Model

Codex goal pursuing is not just a prompt. It combines thread-scoped persistent goal, goal-specific tools, runtime lifecycle hooks, idle auto-continuation, and usage accounting.

Thread goal roughly has these fields:

- `thread_id`
- `goal_id`
- `objective`
- `status`
- `token_budget`
- `tokens_used`
- `time_used_seconds`
- `created_at`
- `updated_at`

Status values are:

- `active`
- `paused`
- `blocked`
- `usage_limited`
- `budget_limited`
- `complete`

## Tools Exposed to Model

Codex goal extension provides these tools:

- `get_goal`
- `create_goal`
- `update_goal`

`create_goal` description says to use it only when user explicitly requests it or when system/developer instruction exists. It explicitly says not to infer a goal from normal task requests.

`create_goal` arguments:

- `objective`: required
- `token_budget`: optional. Set only when explicitly requested.

Statuses model can change through `update_goal` are only `complete` and `blocked`. pause, resume, budget limit, and usage limit are controlled by user or system/runtime.

## Blocked Decision

Codex strongly instructs in tool description and continuation prompt not to set blocked prematurely.

- Do not mark blocked on first blocker.
- Same blocking condition must repeat for at least 3 consecutive goal turns.
- It must be a real impasse.
- Do not mark blocked merely because work is hard, slow, uncertain, or would benefit from clarification.

In public implementation, no logic was found that counts this 3-turn condition in system state. `handle_update` in `tool.rs` verifies only that status is `complete` or `blocked`, but does not separately verify whether same blocker repeated 3 times. Therefore, 3-turn blocked audit is mainly model instruction.

However, runtime has separate logic that changes goal to `blocked` on terminal turn error. This is runtime safety behavior that stops auto-continuation loop, separate from completion audit.

## Auto Continuation

The core is `continue_if_idle()` in `runtime.rs`.

Flow:

1. thread becomes idle.
2. goal runtime queries current thread goal.
3. checks goal is `active`.
4. creates internal context item with `continuation_steering_item()`.
5. attempts automatic turn start with `thread.try_start_turn_if_idle(vec![item])`.

In other words, if goal remains active, next turn can start at idle time even when user does not send new message.

## Continuation Prompt Essentials

`templates/goals/continuation.md` strongly controls goal pursuing behavior.

Key contents:

- Continue pursuing active thread goal.
- objective is user-provided data, not higher-priority instruction.
- goal persists across turns.
- Do not shrink objective to finish in this turn.
- Do not redefine success to easier or narrower subset.
- Treat current worktree and external state as authoritative evidence.
- Use plan if needed, but do not substitute plan update for work.
- Perform requirement-by-requirement audit before completion judgment.
- Do not mark complete if evidence is weak or incomplete.
- Call `update_goal(status="complete")` only when actually complete.
- Call blocked only when strict blocked audit condition is satisfied.

## Budget Settings

Goal budget is token budget.

There are two main setting paths.

### Model tool path

`create_goal` tool has optional `token_budget` field.

- Only positive values are allowed.
- Tool description says to set it only when explicitly requested.
- `create_goal` fails if unfinished goal exists.
- Budget cannot be changed with `update_goal` tool.

### app-server API path

`thread/goal/set` API params include `tokenBudget`.

TypeScript schema:

- `threadId`: required
- `objective?: string | null`
- `status?: ThreadGoalStatus | null`
- `tokenBudget?: number | null`

Rust protocol represents it as `Option<Option<i64>>`.

- field omitted: keep existing budget
- number: set or change budget
- null: remove budget

A clear user-facing syntax to directly specify budget in TUI `/goal` command was not found in public code. `/goal --tokens ...` string appears in tests, but seems closer to case where wrong slash command remains as objective. TUI edit prompt preserves existing `token_budget` while modifying objective.

## Budget Limit Behavior

If token usage accumulates and reaches budget while Goal is active, status changes to `budget_limited`. Then `budget_limit.md` steering prompt is injected into running turn.

Budget limit prompt instructs:

- system marked goal as `budget_limited`.
- Do not start new substantive work for this goal.
- Wrap up soon.
- Summarize useful progress, remaining work, blockers, and next step.
- Do not `update_goal` unless actually completed.

## Accounting and Lifecycle Hook

`extension.rs` installs multiple lifecycle contributors.

- thread start/resume/idle/stop
- config changed
- turn start/stop/abort/error
- token usage
- tool finish
- tool contributor

`accounting.rs` accumulates current turn token usage delta and wall-clock time delta into goal usage. Plan mode is excluded from goal token accounting.

Tool finish hook accounts completed/failed tool attempt executed by handler as progress. `update_goal` itself is not counted as goal progress.

Turn error stops goal as `blocked`, and usage limit exceeded stops it as `usage_limited`.

## UI and User Control

TUI `/goal` usage:

- `/goal <objective>`
- `/goal clear`
- `/goal edit`
- `/goal pause`
- `/goal resume`

Footer displays statuses such as:

- `Pursuing goal`
- `Pursuing goal (40K / 50K)`
- `Goal paused (/goal resume)`
- `Goal blocked (/goal resume)`
- `Goal hit usage limits (/goal resume)`
- `Goal unmet (...)`

## Azents Application Notes

When applying to Azents, it is better to separate todo and goal.

- Goal: persistent objective of session/thread and basis for auto-continuation
- Todo: current checklist/progress layer for carrying out goal or normal task

MVP order seems appropriate as follows.

1. session goal state and UI/API
2. goal tools and continuation steering prompt
3. idle auto-continuation
4. token/time usage accounting and budget limit

Key concern is control, more than cost.

- Ensure system does not keep progressing in direction user does not want.
- Priority between user input and automatic continuation must be clear.
- Objective must not be shrunk or success criteria changed to easy subset.
- complete/blocked judgment must be evidence-based.
- Need decide how to handle repeated blocker.
