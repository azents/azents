---
title: "Session archive, restore and purge"
created: 2026-11-04
tags: [wiki]
---

# Session archive, restore and purge

Owns root-tree pinning, automatic/manual archive, retention snapshots, restore and irreversible purge. Agent deletion and External Channel cleanup participate in these boundaries rather than redefining them.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Conversations and events](../domain/conversation.md)
- [Agent deletion](../domain/agent-deletion.md)
- [External Channel lifecycle](../flow/external-channel-lifecycle.md)
- [Periodic execution](../flow/periodic-execution.md)

## Archive, pinning, retention and purge

`POST /chat/v1/agents/{agent_id}/sessions/{session_id}/archive` archives the complete root
`SessionAgent` tree for an active non-primary root session. The service locks the root and descendant
sessions in stable order and rejects the request while any subtree session or `AgentRun` is active.
Team-primary roots cannot be archived because they remain the stable default conversation anchor for
an Agent.

Every Session has a non-null `last_activity_at` baseline and a root-level `pinned` flag. Durable user,
Agent, and tool transcript events advance `last_activity_at` monotonically; list ordering remains
based on the separate user-input projection. One mailbox promotion batch advances both projections
with one conditional Session update based only on newly inserted events. Session updates and retained
Session row locks acquire the referenced Agent in FK-compatible `KEY SHARE` mode first, preserving one
`Agent -> AgentSession` lock order across input admission and promotion. An Agent's positive
`auto_archive_ttl_days` configuration defaults to 30 days. The `session_auto_archive` scheduler task considers only active, non-primary,
unpinned root Sessions, locks each complete tree, and rechecks the current Agent TTL, root pin,
maximum `last_activity_at` across all tree Sessions, subtree run state, and active runs. A tree is
eligible only when its maximum activity is at least the configured TTL in the past. It then invokes
the same archive lifecycle as manual archive, including retention snapshot, lifecycle participants,
external-channel cleanup, and post-commit worktree cleanup. Pinning is preserved through archive and
restore and only excludes automatic archive; it never changes manual archive eligibility.

The active Agent-session list projects `auto_archive_after` from the maximum `last_activity_at`
across each complete root tree plus the Agent's current TTL. Team-primary and pinned roots project
null because automatic archive does not apply to them. The Agent rail shows an Archives soon badge
when the projected deadline is within `min(floor(auto_archive_ttl_days / 2), 5)` whole days. A
zero-day result disables the badge, so a one-day TTL has no warning badge. Active Sessions whose
deadline has already passed remain marked until the asynchronous archive transition completes.

`PATCH /chat/v1/agents/{agent_id}/sessions/{session_id}/pin` accepts `{ "pinned": boolean }` for an
accessible active non-primary root Session and returns the updated Session projection. Subagent
Sessions are read-only, while inactive and team-primary roots are not found or rejected,
respectively. The Agent rail shows a pin icon on protected Sessions and offers Pin or Unpin from the
non-primary root Session action menu.

Archive snapshots the current instance retention revision, whole-day value, `archived_at`, and finite
`purge_after` deadline on the root. Unlimited retention stores a null deadline and snapshot value.
Every linked descendant `AgentSession` is marked archived so direct worker, command, input, wake-up,
and recovery boundaries can reject it without resolving the tree again. Zero-day retention completes
the archive transaction and only makes the root eligible for the next asynchronous purge pass.
Archive preserves durable transcript data, run rows, and file metadata. After the complete archive
transaction commits, it makes one best-effort forced cleanup attempt for every non-cleaned
Azents-owned worktree allocation in the root tree. The attempt may remove modified or untracked
contents, the Azents-created branch, linked Project and catalog rows, and an empty session-scoped
worktree parent directory. Runtime unavailability, Git failure, ownership mismatch, or any other
cleanup failure is logged and may remain in allocation state, but it does not roll back archive,
change the successful response, or create retention retry work. A crash or cancellation after commit
may skip the attempt. Restore does not recreate a worktree removed during archive.

`GET /chat/v1/agents/{agent_id}/sessions?status=archived` returns archived roots as one paginated
directory status. Each item includes `archived_at`, `purge_after`, and the immutable retention
snapshot; the page response also includes the current instance retention value as policy metadata.
`POST /chat/v1/agents/{agent_id}/sessions/{session_id}/restore` restores the complete tree only while
the root purge job has not started fencing. Restore cancels eligible unstarted purge work, clears the
root archive snapshot, marks every linked session active, and returns the root session. A root that
has crossed the purge fence returns a conflict and cannot become active again.

The Agent rail keeps rename and the archive-backed removal action in the existing session action
menu. The action is available only for inactive non-primary roots. Main Web labels it Delete, uses a
trash icon, and confirms only that the session will be removed from the list; the confirmation omits
retention, preservation, restoration, and permanent-deletion claims. The mutation still archives the
root tree. The bounded sidebar renders separate Pinned and Recent groups from the sidebar summary,
never requests archived rows, visually treats those groups as subordinate to the Sessions section,
and exposes an All sessions link to
`/w/{handle}/agents/{agent_id}/sessions`. The directory supports `?status=active|archived&page=N`,
page navigation through Mantine's Pagination control, direct session links, and Restore on archived
rows. It shares the Agent context header and content inset used by other Agent detail screens. If the
selected session is archived, Main Web navigates to
`/w/{handle}/agents/{agent_id}/sessions/new`.

The public `DELETE /chat/v1/sessions/{session_id}` route is absent. Permanent database deletion is
owned only by durable purge after fencing. Purge deletes subtree ModelFile, Artifact, bound
ExchangeFile and preview blobs, broker state, lifecycle context rows, worktree allocation rows, and
the database Session subtree. It never asks a Runtime Runner or Runtime provider to inspect or mutate
a Git repository, branch, path, or worktree, and physical Git state cannot block deletion.
`session.git-worktrees@1` remains in durable participant snapshots as a database-only compatibility
tombstone: incomplete legacy checkpoints advance normally without Runtime access and unblock
`session.context`. Its allocation table is a pure database child deleted explicitly by the finalizer
before restrictive context rows, regardless of recorded cleanup status.
Irreversible purge fencing also snapshots the required participant keys and policy versions. A fenced
job executes only that immutable snapshot across retries and deployments; later registry additions
apply only to newly fenced jobs. Persisted keys, policy versions, and dependencies must remain
supported, and an unsupported snapshot remains retryable rather than silently changing its required
work.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/archived_session_retention.py`](../../../../python/apps/azents/src/azents/services/archived_session_retention.py)
- [`python/apps/azents/src/azents/services/archived_session_purge.py`](../../../../python/apps/azents/src/azents/services/archived_session_purge.py)
- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
