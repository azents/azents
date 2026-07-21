---
title: "Model Unread Run Results as Session-Shared State"
created: 2026-07-20
tags: [conversation, backend, frontend, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: shared-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0174-session-shared-unread-run-result-state.md"
---

# shared-260720/ADR: Model Unread Run Results as Session-Shared State

## Context

Azents needs to distinguish an AgentSession whose latest completed Run result has not yet been reviewed in the Web UI. The Agent rail should display this attention state after a Run finishes and remove it after the result is reviewed.

AgentSessions are workspace-shared conversation boundaries. Multiple workspace members may open the same Session and inspect the same durable transcript. The unread result state therefore needs an explicit ownership scope rather than being inferred from `AgentSession.run_state`, `updated_at`, or browser-local state.

## Decision

Unread Run result state is **shared by the AgentSession**, not tracked separately for each user or workspace membership.

- The feature applies only to active root AgentSessions shown in the ordinary Agent Session list.
- Archived AgentSessions are outside the feature surface. Archive and restore operations do not add feature-specific unread clearing, preservation, reset, or display behavior.
- Subagent AgentSessions do not acquire or display this unread state; their execution remains visible through the parent Session and Subagent Tree surfaces.
- Every terminal Run status in an eligible root Session makes that Session unread: `completed`, `failed`, `stopped`, `interrupted`, and `cancelled`.
- Terminal Runs are included even when cancellation occurred before useful model output was produced.
- When any authorized workspace member reviews the qualifying result, the AgentSession becomes read for every member.
- Opening or selecting the Session route alone does not acknowledge the result.
- Web review is acknowledged only after the latest history/live resync has completed, the document is visible, and the UI is following the latest timeline rather than browsing detached historical pages.
- If a Run becomes terminal while a member is already viewing the latest visible timeline, the Session becomes read after that terminal result is rendered.
- Hidden browser tabs, failed or incomplete initial loading, and detached history browsing do not clear unread state.
- The state is durable server-side state and is consistent across browsers and devices.
- The Agent Session list renders unread state as one small accent dot beside the Session title. It does not add bold title styling or an `Unread` text badge.
- The indicator includes an accessible label even though the visible treatment is dot-only.
- Unread state does not affect Session ordering. The team primary Session remains first, and other Sessions retain the existing `last_user_input_at` ordering.
- Existing terminal Runs are treated as reviewed when the feature is introduced. Only Runs that become terminal after the schema and runtime behavior are deployed can create unread state; no historical Run backfill marks Sessions unread.
- The UI may call the feature an unread Session indicator, but the state specifically represents an unreviewed terminal Run rather than arbitrary Session updates.

Shared unread state is persisted as a sparse one-to-one `agent_session_unread_runs` row keyed by `session_id`. The row records the terminal `run_id` and session-scoped `run_index` that currently require review; absence of a row means the Session is read.

A Run terminal transition upserts this row in the same database transaction, replacing the boundary only when the new `run_index` is greater. Review acknowledgement names the terminal Run actually observed by the client and conditionally deletes the row only when the stored boundary is not newer. This prevents acknowledgement of Run N from clearing a concurrently completed Run N+1.

The public Session projection exposes the unread terminal Run ID. An authenticated Session read acknowledgement endpoint validates the observed Run and clears the shared boundary idempotently.

## Consequences

- The data model does not need a user/session read-receipt table.
- Session list responses can expose one shared unread result projection without requester-specific joins.
- A review by one member clears the indicator for all other members.
- The feature represents team-level acknowledgement, not proof that every individual member saw the result.
- Future personal notification or inbox features must use a separate user-scoped state instead of reinterpreting this shared Session state.

## Alternatives Rejected

### User-specific read cursor

Track the last reviewed Run independently for each workspace member.

Rejected because the selected product behavior treats review as a shared acknowledgement of the Session result. User-specific attention tracking may still be introduced later as a separate notification feature.

### Browser-local unread state

Store unread Session IDs in local storage.

Rejected because it would diverge across devices, browsers, and workspace members and could not be reconciled reliably with durable Run completion.

## Migration provenance

- Historical source filename: `0174-session-shared-unread-run-result-state.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
