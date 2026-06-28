---
title: "ADR-0083: User Stop Terminates Session-Owned Runtime Exec Processes"
status: accepted
date: 2026-06-28
tags: [backend, engine, runtime, runner, stop, process]
---

# ADR-0083: User Stop Terminates Session-Owned Runtime Exec Processes

## Context

ADR-0081 introduced runner-owned runtime exec processes exposed through `exec_command` and `write_stdin`. Those processes are owned by an `AgentSession` and live in Runtime Runner memory. ADR-0052 defines user stop as a preemptive interrupt: the run must close promptly as interrupted and must not wait for foreground tools to finish.

Without an explicit exec-process stop policy, user stop can interrupt the worker-side tool wait while leaving the already-started runner process alive. That is undesirable for user intent: when a user presses stop during a running shell command, they expect work started by that session to stop too. At the same time, worker graceful shutdown or handover is not user intent. It is an execution-owner transition and should not kill useful runner-owned processes merely because one worker is exiting.

## Decision

### ADR-0083-D1. User stop sends TERM to all live exec processes owned by the stopped AgentSession

When user stop interrupts a run, runtime exec tools must issue a best-effort session-wide termination request to the active Runtime Runner. The Runner sends TERM to every live exec process whose `owner_session_id` matches the stopped `AgentSession`.

The engine must not wait for process termination before closing the current run as interrupted. Follow-up KILL/escalation, process reap, output drain, and missing/terminated observations remain Runner lifecycle responsibilities.

### ADR-0083-D2. Worker graceful shutdown/handover does not terminate runner-owned exec processes

Worker graceful shutdown, process handover, or execution-owner transition interrupts worker-side waits for recovery, but it must not send TERM to runner-owned exec processes by itself. These processes remain runner-owned and may later be observed, cleaned up by normal lifecycle limits, or handled by a resumed owner.

### ADR-0083-D3. Termination is control-plane behavior, not an LLM-visible tool

This decision does not add `terminate_process` to the LLM-visible toolkit surface. Session-wide termination on user stop is an internal control-plane action. The model still observes process termination only through normal tool observations when applicable.

## Consequences

- User stop better matches user intent for long-running shell commands.
- Worker shutdown/handover no longer risks destroying runner-owned process work unintentionally.
- Runtime-control and Runner need a session-wide process termination operation or equivalent internal API.
- Tool cancellation hooks for `exec_command` and `write_stdin` must distinguish user-stop cancellation from non-user-stop worker interruption by relying on the engine cancellation path: only user stop requests foreground tool cancellation.

## Alternatives Considered

### Leave processes alive on user stop

Rejected. This surprises users and can keep expensive or destructive commands running after explicit stop.

### Terminate only the active process id from the interrupted tool call

Rejected for first implementation. A user stop is session-level, and a run can have multiple active foreground process tool calls or already-running session-owned processes. Session-wide ownership gives clearer semantics.

### Terminate processes on worker graceful shutdown

Rejected. Worker shutdown/handover is not a user stop and should preserve continuation/recovery opportunities.
