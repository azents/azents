---
title: "Interactive terminals"
created: 2026-11-04
tags: [wiki]
---

# Interactive terminals

Brings together Session-owned terminal identity and authenticated Runner transport. A terminal is an interactive resource, not an Agent model turn or a durable shell-process observation.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Runtime control](../flow/agent-runtime-control.md)
- [Conversations and events](../domain/conversation.md)
- [Runtime tool execution and network authority](../tools/runtime-execution.md)

## Session terminal identity and lifecycle

One active interactive Terminal may exist per concrete `AgentSession`. Terminal identity is
independent from Session identity and is indexed by Session, Agent, Runtime, desired
generation, Runner generation, and attachment generation. The browser first reads a
content-free projection whose state is `absent`, `stopped`, `starting`, `unavailable`,
`ready`, `active`, or `ended`. The projection separately exposes whether Runtime start
is available, whether open-or-attach is available, a bounded denial reason/scope, and
an optional content-free Terminal summary containing lifecycle, attachment state,
timestamps, final reason, aggregate byte counts, and replay truncation. Projection and
ticket issuance never start a stopped Runtime.

An available browser receives a 30-second, one-time, exact-resource ticket and then
uses the dedicated `azents.terminal.v1` WebSocket. The socket requires the configured
Main Web origin and Terminal subprotocol, consumes the ticket once, and revalidates
current authority before attachment and while connected. Terminal frames never enter
Chat history, live Chat actions, Mailbox, operation events, Goal, Todo, or context
compaction.

The active PTY and bounded input/output replay state are volatile. Redis and in-memory
coordination implementations share one contract; loss fails the Terminal path closed
without changing durable Session, Runtime, Project, or Agent Workspace state. Browser
disconnect releases only the attachment and starts the bounded reattach grace. A
reattachment keeps the Terminal ID and PTY when generation and authority remain current.
Explicit terminate ends the PTY; collapsing or moving between docked and focused
presentation does not.

Capacity is bounded to one active Terminal per Session, eight per user, and sixteen
per Runtime. Binary data chunks are at most 16 KiB, pending input is at most 64 KiB,
and live unacknowledged output is at most 256 KiB. Retained replay is bounded by both
1 MiB and 64 chunks and reports truncation instead of inventing missing output. A
Terminal has a 30-minute idle timeout, an eight-hour absolute lifetime, and separate
two-minute browser-attachment and Runner-stream reconnection grace periods.

Terminal availability is effective server authority. Runtime-free Sessions are absent;
stopped Runtime is explicit and never auto-started; policy, access, Runner capability,
working-folder, lifecycle, generation, and coordination failures are bounded denial
states. Runtime stop, restart, reset, recreation, repair, removal, Runner replacement,
Session archive, or access revocation invalidates the Terminal without becoming a
Runtime lifecycle lock or wait condition.

## Authenticated terminal control

The Runner advertises hidden capability `terminal.v1`. Runtime Control carries only
bounded open and terminate intents on the existing Runner Control stream. Each active
Terminal then uses one dedicated outbound bidirectional Runner gRPC stream for opaque
PTY input/output, resize, acknowledgement, status, and exit events. Existing Runner
operation and Runtime transfer streams never carry PTY bytes.

Terminal admission freezes Runtime ID, desired generation, current Runner connection
generation, Session working-folder authority, and Terminal identity. The Runner PTY
registry rejects stale generations, duplicate opens, malformed sequences, and unknown
Terminal IDs. Control-stream disconnect or a newer Runner generation terminates every
old-generation PTY. A data-stream interruption may reconnect only during the bounded
grace while Control generation remains current; ordered input and replay evidence
resume the same PTY without replaying accepted input.

Each coordination snapshot sends a newer coalesced resize to the Runner before pending
input from that snapshot. A resize accepted before subsequent browser input therefore
reaches the PTY before that input executes, without fixed timing delays or a separate
resize acknowledgement round trip.

Server coordination admits at most one active Terminal per Session, eight per user,
and sixteen per Runtime; the Runner independently enforces the Session and Runtime
ceilings. Terminal data frames are limited to 16 KiB, queued input to 64 KiB, live
unacknowledged output to 256 KiB, and replay to the smaller of 1 MiB or 64 chunks.
Tickets expire after 30 seconds. PTY authority has a 30-minute idle deadline, an
eight-hour absolute deadline, and two-minute browser and Runner-stream grace periods.
These bounds are the same for Redis and in-memory coordination.

Natural process exit and requested termination remain asynchronous Runner outcomes.
The Runner keeps a terminating stream alive for final status/exit delivery and retries
a failed or interrupted final flush by reconnecting within the overall stream grace.
The browser receive path likewise waits for the final exit or revocation control after
requesting termination instead of treating the terminate request itself as completion.
Authority invalidation or exhausted grace still closes the path fail-closed.

Runtime lifecycle always has priority. Stop, restart, reset, recreation, repair,
removal, and Runner replacement publish Terminal invalidation and proceed immediately;
they never acquire a Terminal lock, wait for browser acknowledgement, or wait for PTY
cleanup. The Linux Runner owns PTY allocation, process-session cleanup, TERM/KILL
escalation, idle and maximum lifetime, and complete Session-wide teardown. Shared
protocol contracts remain OS-neutral so another Runner backend can implement the same
surface later.

Terminal shell-exit waits own their shielded waiter through success, timeout,
child failure and owner cancellation, joining it before returning or propagating
the original outcome. This does not change POSIX session signals or grace periods.

Terminal coordination is separate from ordinary Runtime operation coordination while
sharing the Redis-or-memory deployment choice. It stores bounded volatile attachment,
sequence, replay, quota, heartbeat, and revocation state only. PostgreSQL receives no
Terminal bytes or transcript. Structured logs and metrics retain identifiers, bounded
lifecycle reasons, durations, byte counts, truncation, quota, and cleanup outcomes,
never command, output, environment, or working-directory content.
The Redis implementation uses the `runtime-terminal:v2` namespace and stores accepted
Runner connection generations as canonical fixed-width decimal strings. It does not
read or migrate the retired volatile namespace.

## API route entrypoints

- `/terminal/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}`
- `/terminal/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ticket`
- `/terminal/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ws`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/runtime/control_protocol`](../../../../python/apps/azents/src/azents/runtime/control_protocol)
- [`python/libs/azents-runtime-control`](../../../../python/libs/azents-runtime-control)
