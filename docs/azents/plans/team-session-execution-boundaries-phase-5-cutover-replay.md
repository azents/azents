---
title: "Team Session execution boundaries phase 5: migration replay and coordinated cutover"
created: 2026-07-24
tags: [session, authorization, migration, replay, cutover, operations, security]
---

# Team Session execution boundaries phase 5: migration replay and coordinated cutover

## Phase Execution Plan

- Phase: `5 — Migration replay and coordinated cutover`
- Branch/base: `feature/team-session-cutover-replay` → `feature/team-session-resource-authority` (`9260c199`)
- PR boundary: durable Postgres-only preflight/replay, deterministic historical provenance verification, strict old broker rejection, and coordinated-cutover operator evidence
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Multi-phase plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)

## Feasibility Decision

No new Alembic revision is required for this phase. The existing forward-only migrations already
implement the durable historical classification policy:

- `1ce295000a20` retains deterministic pending Human InputBuffer sender references and writes explicit
  `null` sender provenance for pre-cutover Human events without a durable source relation.
- `374a722fb9ee` classifies legacy ExchangeFiles as `migration` provenance and retains the prior
  uploader only as `source_user_id` when it exists.
- `8fae7b9ab00a` derives a ModelFile Run only from exact `(session_id, created_run_index)` identity
  and leaves unmatched historical lineage nullable.

Phase 5 verifies these outcomes without inventing a User or Run. Existing nullable historical values
remain explicit unavailable provenance. New runtime writes remain subject to the Phase 1 and Phase 4
contracts.

## Deliverables

- Add a bounded, read-only preflight that derives replay candidates exclusively from durable PostgreSQL
  Session, InputBuffer, pending command, Run, idle continuation, and stop state.
- Reuse canonical Session execution validation to reject inactive, stale, malformed, or otherwise
  invalid durable work before replay emits any broker notification.
- Add an idempotent replay operation that purges each candidate Session's old broker/ownership state
  and then sends only `SessionWakeUp(session_id=...)`.
- Make replay batch identity deterministic, bounded, content-free, and safe to repeat after an
  interruption. PostgreSQL remains the source of work; Redis is discarded notification state.
- Report candidate/work-category counts, replay counts, and invariant-failure codes without message
  contents, attachment names, payloads, credentials, requester IDs, sender IDs, or file bodies.
- Verify historical Human sender and Exchange provenance classification using deterministic migration
  fixtures: known references are retained only where the pre-cutover row stored them; unknown history
  remains null or `migration` provenance.
- Preserve strict rejection of rich/legacy broker payloads.
- Provide CLI help and an operator runbook covering admission pause, Worker/scheduler drain, database
  backup, old-process stop, forward migration, new deployment, broker/ownership discard, PostgreSQL
  replay, health checks, admission resume, and the pre-cutover database/image rollback boundary.

## Non-goals

- Performing an Alembic upgrade, downgrade, stamp, data write, Redis purge, deployment, Kubernetes
  operation, database backup, or production cutover from this implementation task.
- Adding a compatibility decoder, dual-read broker payload, User fallback, nullable execution User,
  or inferred sender/provenance.
- Replaying message contents, attachment data, credentials, model prompts, requester data, sender data,
  or resource payloads through the CLI or broker.
- E2E expansion, living-spec promotion, Requirements/Design implementation dates, or cleanup.

## Boundary Contract

A replay candidate is selected only from durable PostgreSQL work state. A candidate Session is valid
only when its current canonical Session/tree/Agent/Workspace/owner-generation snapshot validates and
contains actionable durable work. The service does not read Redis to decide work, does not use a
requester, sender, creator, owner, viewer, approver, uploader, or fallback User, and does not attempt
to reconstruct content.

For every approved bounded batch, replay first acquires cluster-safe per-Session Redis barriers that
block new Worker ownership. It then conditionally advances each exact preflight `owner_generation`,
revalidates the current durable work identity in one transaction, and commits the fences before any
broker mutation. Invalid or drifted candidates roll back the complete fence transaction and prevent
broker notification for that batch. For every fenced candidate, replay calls
`purge_session_state(session_id)` before `send_message(SessionWakeUp(session_id=session_id))`, then
releases the exact barriers. The service renews each exact token before every broker mutation and
bounds fence, acquire, renew, purge, wake, and release waits below the barrier TTL. If a process stops
between those calls, a repeated replay reconstructs the candidate from PostgreSQL and safely retries.
Barrier keys use the Session Redis hash tag so the ownership check remains Redis Cluster compatible.

## Operator Cutover Procedure

The CLI is an operator aid, not an automatic deployment controller. Do not run `replay --execute`
until every prerequisite below is complete and the maintenance window is active.

1. Pause public and External Channel admission.
2. Drain Workers and scheduler processes to durable recovery boundaries.
3. Take and verify a PostgreSQL backup. Record the deployed image identifiers.
4. Stop every old Worker, scheduler, and process that can publish or consume broker work.
5. Apply the reviewed forward Alembic migrations with the new release image.
6. Run `team_session_cutover preflight` from the new release image in bounded batches. Resolve every
   invariant failure before proceeding.
7. Run `team_session_cutover replay --execute` in the same bounded batches while old and new Workers
   remain stopped. Replay acquires the cutover barrier, fences stale durable ownership, discards old
   Redis queues/locks/heartbeats/activity, and sends only `SessionWakeUp(session_id=...)`.
8. Start the complete new Worker, scheduler, API, and supporting process population. Do not mix old
   and new Worker semantics.
9. Verify Worker, scheduler, database, broker, and application health checks; inspect only
    content-free counts and invariant codes.
10. Resume admission after replay and health verification complete.

The rollback boundary is before forward migration and new-image cutover. Restore the verified
pre-cutover database backup together with the recorded pre-cutover images. Do not attempt an
application-level downgrade, compatibility deployment, or mixed-version replay after the forward
cutover starts.

## Workstreams

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Durable replay projection | `src/azents/repos/session_execution/**`, related tests | deterministic bounded work candidates and content-free work counts | repeated-read, batching, stale/invalid-state tests |
| Preflight and replay service | `src/azents/services/team_session_cutover_replay.py`, related tests | Postgres-only validation, broker purge, pure wake-up emission, report data | ordering, idempotency, no-send-on-failure tests |
| Operator CLI | `src/cli/team_session_cutover.py`, related tests | `preflight` and explicit `replay` operator commands with content-free output | CLI argument/output and service-adapter tests |
| Migration and wire evidence | migration/broker tests | historical null/migration classification and rich-payload rejection | migration fixtures and strict decoder tests |
| Cutover operations | `docs/azents/operations/**` or equivalent operator documentation | coordinated cutover and rollback-boundary procedure | documentation validation and command/help review |

## Final Validation

- Focused Ruff format/check and whole-subproject Pyright from `python/apps/azents`.
- Focused pytest for the replay projection, preflight/replay service, CLI, canonical snapshot negative
  cases, migration classification fixtures, and broker strict-decoder behavior.
- Migration revision/head inspection without applying any migration to a shared environment.
- `git diff --check` and content-free logging/output review.
- Scope review confirming that no live cutover, Redis/Kubernetes/database write, compatibility path,
  or inferred User/provenance was introduced.
