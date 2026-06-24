---
title: "ADR-0001: Move Sandbox Scope from Agent to Session"
created: 2026-04-24
tags: [architecture, engine, infra]
---

# ADR-0001: Move Sandbox Scope from Agent to Session

## Context

The current nointern sandbox uses a **per-agent** model: one `RDBAgent` maps to one persistent container shared by multiple sessions. This design was chosen for the product value of "the whole team talks to one agent," and lifecycle, hibernation, and snapshot infrastructure was built across Phases 1-3 (`docs/nointern/design/agent-home.md`, `phase3-snapshot-hibernation.md`).

However, the following problems became clear:

1. **Contention between sessions**: Multiple sessions can send exec calls into one container at the same time, causing possible file conflicts and process interference. The allocation step in `agent_home_manager.py` has a lock, but the execution step is not serialized.
2. **No failure isolation**: A runaway process in one session can break the entire agent container.
3. **Billing unit mismatch**: An agent-level container remains alive even when idle, which does not align with usage-based billing.
4. **Poor coding UX**: The rootfs of a long-running coding session can be disturbed by another session.

Meanwhile, the industry—Devin, OpenAI Codex cloud, OpenHands, Cursor Background Agents, E2B, and Modal—has converged on the pattern of **session/task-scoped ephemeral sandboxes plus agent-level snapshots**. Research: Discussion [#2968](https://github.com/azents/azents/discussions/2968).

## Decision

Move sandbox scope to **per-session**. To preserve the value of a shared team agent, separate the layers as follows:

- **`RDBAgent` (DB)**: shared identity — name, instructions, attached toolkits, credentials, memory flag. No change.
- **`RDBConversationSession` (DB)**: runtime owner — lifecycle lease, snapshot reference, and TTL state are managed from this table.
- **Filesystem 3-layer model**:
  - Persistent `/data/agent`, `/data/user/{user_id}`, `/platform` — agent/user/platform scope, EFS (`agent-home-efs` PVC). No change.
  - Long-lived `/home/sandbox` — session scope, EFS session subPath (`sessions/{session_id}/home-sandbox`). 30-day idle TTL.
  - Remaining volatile rootfs — session scope, container rootfs. Hibernation snapshot TTL of 1 day.
- **Session-scoped hibernation**: Reuse the Phase 3 snapshot/hibernation infrastructure with the same semantics and behavior, but move its scope down to session. After 30 minutes idle, commit a snapshot and tear down the container. When a message arrives, restore from the snapshot.
- **Big-bang cutover**: Switch all at once without a dual-mode feature flag. Existing active sandboxes are terminated at cutover. Conversation context remains in the DB, so users only see that the conversation resumes in a "new sandbox."

For detailed implementation decisions (Discussion [#2971](https://github.com/azents/azents/discussions/2971), A-G), see the design document [per-session-sandbox.md](../design/per-session-sandbox.md).

## Consequences

### Positive

- **Eliminates concurrency contention at the source**: each session gets an independent container. Files and processes are not shared.
- **Failure isolation**: OOMs or runaway processes in one session do not propagate to other sessions.
- **Billing alignment**: session-level compute measurement becomes natural, and the telemetry integration point is clear ([Issue #2685](https://github.com/azents/azents/issues/2685)).
- **Better coding UX**: the session = task mental model matches user expectations and industry patterns such as Devin and Codex.
- **WarmPool potential**: some constraints from a fixed agent-level EFS subPath are removed, enabling a second-stage optimization.

### Negative

- **More frequent cold starts**: sessions opening and closing more often increases hibernate/restore frequency. This needs measurement.
- **More ECR images**: session snapshots multiply the image count. The ECR lifecycle policy must be adjusted to the 1-day snapshot TTL.
- **More EFS subPaths**: session count is unbounded. A cleanup job is required, and EFS usage must be monitored.
- **Big-bang migration risk**: all active session containers are disconnected at cutover, though conversations remain. Announcement and retry UX are required.
- **Large implementation scope**: 8-phase stacked PR with DB migration, refactor, and test rewiring.

## Alternatives

### Dual-mode feature flag, similar to A3/F3

Keep the session model and agent model side by side behind a flag and migrate gradually.

**Rejected**: Maintaining dual code paths costs more than a big-bang cutover. At nointern's scale, an announced cutover is sufficient. Conversation context is preserved, so user impact is limited.

### Keep the per-agent model and serialize session execution

Keep the current sandbox and serialize exec calls per session to remove contention.

**Rejected**: This only partially solves concurrency contention. Failure isolation, billing, and UX problems remain. It also does not solve preservation needs for long-running coding sessions.

### Fully copy Devin: agent base snapshot plus per-session restore

Restore a fresh container from an agent-level snapshot when a session starts. If the session ends with meaningful changes, update the base snapshot.

**Rejected**: Managing the owner and permission model for the agent-level "base" snapshot is complex in a shared team-agent context. The 3-layer model provides clearer responsibility separation.

### 2-layer filesystem: persistent + volatile

Omit the long-lived `/home/sandbox` layer and keep only persistent storage plus rootfs.

**Rejected**: This does not preserve installed packages and caches well enough for long-running coding sessions. A roughly 30-day idle lifetime is needed to keep the feel of "my assistant's desk."

### Per-user sandbox (workspace × user)

Use an independent sandbox per user within the same agent.

**Rejected**: User count × agent count may be smaller than session count, but it loses task-level isolation for coding work. Session scope is more granular and better aligned with industry practice.

## References

- Research Discussion: [#2968](https://github.com/azents/azents/discussions/2968)
- Implementation design Discussion: [#2971](https://github.com/azents/azents/discussions/2971)
- Original issue: [#2837](https://github.com/azents/azents/issues/2837)
- Design document: [per-session-sandbox.md](../design/per-session-sandbox.md)
- Related infrastructure documents:
  - `docs/nointern/design/agent-home.md` — previous per-agent design
  - `docs/nointern/design/phase3-snapshot-hibernation.md` — infrastructure to reuse
  - `docs/nointern/design/sandbox-daemon.md` — in-container daemon
  - `docs/nointern/design/memory-system.md` + `shared-storage-and-skills.md` — memory/skills, persistent `/data` layer
- Telemetry integration: [Issue #2685](https://github.com/azents/azents/issues/2685), [PR #2762](https://github.com/azents/azents/pull/2762)

## Status

**Accepted** (2026-04-24). Implementation is planned as an 8-phase stacked PR via `/ship-feature`.
