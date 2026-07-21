---
title: "Archived Session Retention and Durable Purge"
created: 2026-07-19
tags: [architecture, backend, frontend, scheduler, session, retention, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: archived-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0171-archived-session-retention-and-purge.md"
---

# archived-260719/ADR: Archived Session Retention and Durable Purge

## Context

[archive-260626/ADR](./archive-260626-archive-policy.md) introduced AgentSession archive as a soft transition for inactive non-primary sessions. It intentionally omitted an archived-session browser and restore flow, and it did not define a retention deadline. Archived session data therefore remains indefinitely unless the existing public hard-delete API is called.

The SessionAgent tree model introduced after [archive-260626/ADR](./archive-260626-archive-policy.md) gives a root AgentSession ownership of child and nested SessionAgent nodes and their linked child AgentSessions. A retention policy must delete this ownership tree as one unit rather than treating only the visible root session as the lifecycle boundary.

Session deletion also crosses external-resource boundaries. ModelFiles, Artifacts, and ExchangeFiles have physical object-storage blobs, and Azents-owned Git worktrees have filesystem and Git branch state whose ownership metadata is stored under the shared SessionAgentContext. Deleting AgentSession rows first can erase the durable metadata needed to finish or retry external cleanup.

ExchangeFile upload currently begins before a new AgentSession necessarily exists, and current rows are workspace/Agent-scoped. However, an ExchangeFile is not intended to be reused across independent root sessions. This requires an explicit retention owner that can be assigned when the first input is accepted without preventing pre-session uploads.

The product direction is that archive is reversible temporary removal, while expiration is the only ordinary permanent-deletion path.

## Decision

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-155). Archived sessions use an admin-managed retention deadline

Archived root sessions receive a retention deadline calculated in whole days. The default retention is 30 days, and system administrators may configure unlimited retention.

The setting is instance-wide and belongs to DB-backed Admin-managed system settings. A finite value is a non-negative integer number of days. `null` represents unlimited retention. Zero days makes the session immediately eligible for the asynchronous scheduler purge; it does not delete synchronously in the archive request.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-156). Archive snapshots the deadline and administrators choose change scope

Archive stores an explicit `archived_at` and snapshots the current policy into `purge_after`. Unlimited retention stores `purge_after = null`.

When changing or explicitly reapplying the retention setting, a system administrator chooses one of these application scopes:

- **New archives only**: the safe default. Existing archived-session deadlines remain unchanged.
- **Recalculate existing archives**: apply the new policy to archived roots whose purge has not entered fencing or cleanup.

Existing-session recalculation uses the original `archived_at` and computes `purge_after = archived_at + new retention`. It also updates the policy revision and retention snapshot. A finite deadline at or before the current time becomes eligible for the next asynchronous purge pass. Changing to unlimited clears the deadline and cancels purge work that has not started; changing from unlimited to finite creates purge work.

The Admin surface must preview affected, immediately eligible, and already-started counts before confirmation. Recalculation runs as durable, bounded work tied to the new settings revision. A purge already in fencing or cleanup is irreversible and is not changed.

Restoring and archiving the same session again always snapshots the then-current policy.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-157). Archive remains reversible until purge starts

Users can browse and restore archived sessions before their purge workflow begins. The product does not expose a separate permanent-delete action or API.

Archive itself must not perform irreversible external cleanup. In particular, it no longer removes Azents-owned Git worktrees. A restored session therefore retains its session tree and owned worktree resources. File resources may still expire under their ordinary TTL while the session is archived; restore does not recreate expired resources.

Once the durable purge workflow has entered its fencing or cleanup phase, restore is rejected. After final deletion, the session is not recoverable.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-158). The root SessionAgent tree is one retention unit

Archiving a root AgentSession transitions every linked descendant AgentSession in the SessionAgent subtree out of active execution. Purge permanently removes the root AgentSession, every descendant SessionAgent and child AgentSession, and all DB-owned rows that cascade from those sessions.

Child subagent sessions do not receive independently configurable archive deadlines. Their retention follows the root session.

Team-primary sessions remain non-archivable. Archive continues to require the entire subtree to be inactive.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-159). Purge is a durable scheduled workflow

Expiration creates or activates durable per-root purge work. The scheduler claims due work with leases and bounded retries.

The workflow must fence execution, stop or wait for any unexpectedly active subtree work, and complete required external-resource cleanup before deleting AgentSession rows. A transient object-storage, runtime, Git, or database failure leaves durable retry state and must not be converted into successful deletion.

FastAPI background tasks and request-path hard deletion are not purge ownership mechanisms.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-160). ModelFiles are deleted during purge

All ModelFiles owned by AgentSessions in the purged subtree are transitioned to deleted state and their physical blobs are deleted during purge. Final session-row deletion waits until required ModelFile blob deletion has succeeded or the blob is already absent.

This purge path is separate from ordinary model-input-head garbage collection.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-161). Artifacts are deleted during purge

Artifacts keep their ordinary TTL, but the purge of their owning AgentSession subtree is an earlier terminal lifecycle boundary. Purge transitions every remaining subtree Artifact to a terminal state, deletes its physical blob, and records deletion success before final session-row deletion.

An Artifact whose TTL cleanup already deleted the blob is already complete for purge. A transient deletion failure keeps the purge retryable.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-162). ExchangeFiles gain a root-session retention owner

ExchangeFile upload may occur before an AgentSession exists, so new uploads begin unbound and continue to use their ordinary TTL. At the first successful user-input acceptance, every referenced ExchangeFile and its generated preview resource are atomically claimed by the target root AgentSession retention unit. ExchangeFiles created from an existing AgentSession are bound to that root retention unit at creation.

A claim is idempotent for the same root and rejected for a different root. Event or message URI scanning is not lifecycle authority. A bound ExchangeFile keeps its ordinary TTL, but root-session purge is an earlier terminal boundary: purge deletes any remaining bound blob and metadata before deleting the session tree. Unbound abandoned uploads remain governed only by their independent TTL.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-163). Worktree cleanup moves from archive to purge

Azents-owned Git worktree and branch cleanup occurs during durable purge, not during archive. Cleanup uses the authoritative SessionAgentContext worktree allocation rows and each allocation's recorded creator ownership.

Final deletion must not remove SessionAgentContext or worktree ownership metadata before every required worktree cleanup has completed. Cleanup failure keeps the purge retryable.

### [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-164). Archived sessions cannot resume execution

Worker ownership claim, run-state transitions, input admission, pending-command admission, and durable wake-up handling must reject archived sessions. Archive and purge also fence stale worker generations and clear subtree broker state at the appropriate lifecycle boundary.

A delayed Redis wake-up must not reactivate an archived session.

## Consequences

- Archived-session retention becomes a predictable product policy rather than indefinite storage.
- Users gain an archived-session browser and restore flow but no permanent-delete control.
- A root SessionAgent tree has one archive and purge lifecycle.
- Admin setting changes alter existing purge deadlines only when an administrator explicitly selects recalculation after reviewing an impact preview.
- Retention recalculation requires its own durable, revision-bound batch progress in addition to per-session purge work.
- Worktrees remain allocated during the archive retention window, increasing temporary runtime storage use in exchange for real restore semantics.
- Purge requires durable per-session workflow state in addition to the existing global scheduled-task state.
- Public hard-delete routes must be removed or made internal-only.
- ModelFile, Artifact, bound ExchangeFile, and worktree cleanup metadata remains available until external cleanup succeeds.
- ExchangeFile input admission needs atomic root-retention ownership claims, including preview resources.
- Existing unbound ExchangeFiles remain on their ordinary TTL because historical event URI scanning is not adopted as ownership authority.
- Existing archived sessions need a rollout grace period before automated purge is enabled.

## Superseded decisions

This ADR supersedes these parts of earlier decisions:

- [archive-260626/ADR](./archive-260626-archive-policy.md)'s initial omission of an archived-session browser and restore flow.
- [archive-260626/ADR](./archive-260626-archive-policy.md)'s implicit indefinite retention of archived durable data.
- [azents-260703/ADR-D5](./azents-260703-azents-git-worktree-ownership-and-cleanup.md)'s rule that archive initiates worktree cleanup.
- [simplified-260627/ADR-D1](./simplified-260627-simplified-file-lifecycle-policy.md) through D3 only where they make TTL the exclusive terminal boundary for Artifact and ExchangeFile. Ordinary TTL remains valid, while owning-session purge may delete these resources earlier.
- [file-260601/ADR](./file-260601-file-media-resource-lifecycle.md)'s independent ExchangeFile retention only where it excludes an earlier owning-session purge boundary.

[archive-260626/ADR](./archive-260626-archive-policy.md)'s team-primary and running-session archive restrictions remain in effect. [azents-260703/ADR](./azents-260703-azents-git-worktree-ownership-and-cleanup.md)'s explicit ownership validation remains in effect and is reused by purge. Unbound ExchangeFiles remain exclusively TTL-owned under [simplified-260627/ADR](./simplified-260627-simplified-file-lifecycle-policy.md).

## Alternatives

### Keep archived sessions indefinitely by default

Rejected. It does not provide a bounded lifecycle and makes storage policy dependent on a separate user hard-delete feature.

### Recalculate every archived deadline automatically on every setting change

Rejected. A policy edit could unexpectedly make existing sessions immediately eligible for irreversible deletion. Existing-session recalculation requires an explicit application-scope choice and impact preview.

### Never allow an administrator to update existing archived deadlines

Rejected. Administrators need a controlled way to shorten, extend, enable, or remove retention for archives that have not entered irreversible purge work.

### Delete synchronously in the archive request when retention is zero

Rejected. External cleanup is multi-resource, failure-prone, and retryable. The archive request must not own a distributed destructive transaction.

### Delete DB rows before external cleanup and rely on best-effort orphan collection

Rejected. The DB rows contain the authoritative ownership and retry metadata for ModelFiles and worktrees. Removing them first can create untraceable storage and filesystem leaks.

### Continue removing worktrees during archive

Rejected. A restored session would not recover its previously owned workspace state, so archive would not be meaningfully reversible.

### Keep ExchangeFiles exclusively Agent-scoped and TTL-owned

Rejected. ExchangeFiles are not intended to cross independent root sessions, and leaving them outside the purge graph retains blobs after their only owning session has been permanently removed.

### Reconstruct ExchangeFile ownership by scanning event URIs during purge

Rejected. Reverted, forked, compacted, or partially materialized history is not an authoritative ownership index. Ownership is recorded prospectively at the input acceptance boundary.

### Use a many-to-many ExchangeFile session reference table

Rejected. Cross-root sharing is not a product requirement. A nullable root-retention owner supports pre-session upload, same-tree use, atomic claim, and direct purge lookup with less lifecycle complexity.

## Migration provenance

- Historical source filename: `0171-archived-session-retention-and-purge.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
