---
title: "Archived Session Retention and Durable Purge Implementation Plan"
created: 2026-07-19
tags: [backend, frontend, scheduler, session, retention, admin, testenv]
---

# Archived Session Retention and Durable Purge Implementation Plan

## Feature summary

Implement the approved archived-session lifecycle from [Archived Session Retention and Durable Purge](../design/archived-session-retention-and-purge.md) and [ADR-0168](../adr/0168-archived-session-retention-and-purge.md).

The shipped feature will:

- use a DB-backed instance-wide retention setting with a 30-day default, whole-day finite values, and Unlimited mode;
- let system administrators apply a retention revision only to future archives or durably recalculate existing archives whose purge fencing has not started;
- archive, list, and restore complete root SessionAgent trees;
- permanently purge expired root trees through durable leased work;
- delete ModelFile, Artifact, bound ExchangeFile, preview, and Azents-owned worktree resources before final DB deletion;
- bind ExchangeFiles to one root retention unit at the user-input acceptance boundary;
- remove the ordinary user-facing permanent session delete surface;
- expose Admin and Main Web workflows with deterministic E2E coverage.

## Delivery stack

All PRs use the prefix `Archived session retention` and are stacked in this order.

| PR | Title | Scope | Depends on |
| --- | --- | --- | --- |
| 1/10 | Design | Approved ADR and feature design | `main` |
| 2/10 | Implementation plan | This phased delivery and validation plan | 1/10 |
| 3/10 | Phase 1 — Retention foundation | DB-backed settings, archive metadata, durable recalculation applications, purge-job persistence, migrations, repository/service tests | 2/10 |
| 4/10 | Phase 2 — Archive, restore, and fencing | Subtree archive/list/restore APIs, worktree preservation during archive, worker/write admission guards, restore/purge race handling | 3/10 |
| 5/10 | Phase 3 — ExchangeFile ownership | Nullable root-retention ownership, preview ownership, atomic input claims, same-root authorization, creation-path coverage | 4/10 |
| 6/10 | Phase 4 — Durable purge | Five-minute purge task, per-root leases, stop/fencing, broker cleanup, targeted file and worktree cleanup, final subtree deletion | 5/10 |
| 7/10 | Phase 5 — Product surfaces | OpenAPI/client regeneration, Admin retention controls and recalculation progress, Main Web archived browser and restore, permanent-delete removal | 6/10 |
| 8/10 | E2E validation | Deterministic fixtures, full user-visible matrix, external-resource assertions, implementation/spec drift report, fixes found during validation | 7/10 |
| 9/10 | Spec promotion | Current conversation, file storage, periodic execution, and Admin behavior specs; mark design implemented | 8/10 |
| 10/10 | Cleanup | Remove this temporary implementation plan and stale plan references | 9/10 |

The complete stack is created before CI monitoring. CI failures are fixed on the responsible branch, then dependent branches are rebased with the stacked-PR workflow.

## Phase 1 — Retention foundation

### Data and domain changes

- Add a typed singleton system file-lifecycle settings model with:
  - `archived_session_retention_days` as a required nullable non-negative integer;
  - optimistic `revision`;
  - updater and timestamp audit fields.
- Add root archive metadata to AgentSession:
  - `archived_at`;
  - `purge_after`;
  - `archive_policy_revision`;
  - `archive_retention_days_snapshot`.
- Add a partial due-deadline index for archived roots.
- Add durable retention recalculation application state with target revision/value, bounded cursor/progress, counters, leases, retries, and operator-safe error summaries.
- Add per-root purge jobs with deadline, status, `fencing_started_at`, lease/retry state, policy revision, counters, and terminal tombstone timestamps.
- Generate new Alembic revisions and update `db-schemas/rdb/revision`; do not modify executed migrations.

### Service behavior

- Read/update settings through Admin-only service boundaries.
- Preview future-only versus existing-archive recalculation impact.
- Apply `new_archives_only` synchronously by updating the settings revision.
- Apply `recalculate_existing` through a durable bounded scheduler task.
- Recompute from `archived_at + target retention`.
- Create, reschedule, or cancel only purge jobs whose `fencing_started_at` is null.
- Reject retention-value changes while a recalculation application is active.

### Tests

- Migration shape and default-row behavior.
- Strict whole-day/null validation and optimistic revision conflicts.
- Preview counts for shorter, longer, finite-to-Unlimited, and Unlimited-to-finite changes.
- Recalculation batching, retries, races, and applied/skipped counters.
- `purge_after <= now` eligibility without synchronous deletion.

## Phase 2 — Archive, restore, and fencing

### Backend behavior

- Make a root SessionAgent tree the archive unit.
- Lock root and descendants in stable order and reject archive when any subtree session or AgentRun is active.
- Snapshot the current setting revision and deadline on the root.
- Mark every linked AgentSession archived.
- Create finite purge work without deleting file or worktree resources.
- Add archived-session list and restore service/API paths.
- Restore only when `fencing_started_at` is null, cancel eligible purge work, clear root archive metadata, and reactivate the subtree.
- Stop archive-time worktree cleanup.

### Execution fencing

- Require active status for owner-generation claims, run transitions, input admission, command admission, wake-up handling, and recovery.
- Ensure delayed broker messages cannot reactivate archived sessions.
- Preserve existing access control and 404-safe cross-workspace behavior.

### Tests

- Root/child/nested archive and restore.
- Team-primary, subagent-direct, active-child, and running-run rejection.
- Archive/restore/recalculation/purge-claim races.
- Delayed wake-up and recovery rejection for archived sessions.
- Archive preserves file and worktree resources.

## Phase 3 — ExchangeFile ownership

### Schema and repository

- Add nullable `retention_root_session_id` and `retention_bound_at` to ExchangeFile.
- Add bounded lookup indexes.
- Keep pre-session uploads unbound.
- Bind files created from an existing root or child session immediately to the resolved root.
- Bind source and preview rows as one ownership set.

### Input acceptance

- Centralize ExchangeFile claim at every user-input acceptance boundary.
- Lock/deduplicate attachment rows in stable order.
- Validate workspace membership, Agent scope, status, and retention root.
- Atomically persist session/input and claims in one DB transaction.
- Make same-root retries idempotent and reject cross-root rebinding.
- Update the first-message session-creation path so it no longer bypasses ownership.
- Resolve later attachment access against the root retention owner, while allowing root/child sessions in the same tree.

### Tests

- Pre-session upload remains unbound.
- New-session first input claims source and preview.
- Existing-session message/input/edit paths use the same claim boundary.
- Existing-session-created artifacts/previews bind immediately.
- Concurrent cross-root claim has exactly one winner and no partially accepted input.
- Same-root child access succeeds; another root fails.
- Historical unbound rows continue to use ordinary TTL.

## Phase 4 — Durable purge

### Scheduler and job execution

- Register `archived_session_purge` at a five-minute interval with bounded backoff.
- Claim due per-root jobs with `FOR UPDATE SKIP LOCKED` and leases.
- Set `fencing_started_at` before irreversible work.
- Resolve and persist the complete subtree resource boundary.
- Record system stop intent and send stop signals for unexpectedly active sessions.
- Retry until no subtree AgentRun remains active.
- Add a broker abstraction operation to clear message queue, ownership lock, heartbeat, and activity state without reaching into Redis from the purge service.

### External-resource cleanup

- Mark/delete all subtree ModelFiles independently of model-input-head GC.
- Expire and delete all subtree Artifacts.
- Expire and delete all ExchangeFiles and previews bound to the root.
- Treat already absent blobs as successfully deleted.
- Preserve metadata and retry when object deletion fails.
- Add context/tree worktree cleanup that uses each allocation's recorded creator ownership and typed runner operations.
- Require every worktree allocation to be cleaned before context deletion.

### Finalization

- Revalidate archived subtree state, inactive runs, broker cleanup, file deletion, and worktree cleanup.
- Invoke an internal-only subtree delete operation.
- Persist a content-free completed purge tombstone.
- Remove the public backend session hard-delete path only when purge finalization is available.
- Backfill existing archived roots with activation-time-plus-30-day grace deadlines.

### Tests

- Lease expiry and concurrent scheduler instances.
- Zero-day archive becomes due on the next task pass.
- Partial file cleanup and retry without DB subtree loss.
- Already missing object idempotency.
- Root- and child-created worktree cleanup and ownership failures.
- Broker state clearing and stale-worker fencing.
- Completed purge removes the subtree and external resources.

## Phase 5 — Product surfaces

### API and generated clients

- Add Admin settings GET/PATCH, recalculation preview, and application-progress endpoints.
- Add Main Web archived-session list and restore endpoints.
- Include server-provided `archived_at`, `purge_after`, and retention mode.
- Remove the public permanent session DELETE route.
- Regenerate OpenAPI specifications and all affected Python/TypeScript clients through the repository generation workflow; do not edit generated clients manually.

### Admin Web

- Add whole-day retention input and Unlimited control.
- Default application scope to `New archives only`.
- Add explicit `Recalculate existing archives` scope.
- Show preview counts for changed, immediately eligible, cancelled, newly scheduled, and excluded roots.
- Require confirmation before existing deadlines change.
- Show durable recalculation progress and final counts.
- Warn that overdue roots become eligible for the next five-minute purge pass.

### Main Web

- Add an archived-session browser under the Agent session area.
- Show title fallback, archive time, deletion time or Unlimited, and Restore.
- Do not expose permanent delete.
- Include the configured retention in archive confirmation copy.
- Preserve current layout and session navigation except for the new archived surface.

### Tests

- API permission and revision-conflict tests.
- Admin component and route tests for all application scopes and preview states.
- Main Web list/restore/error states.
- Permanent-delete route and UI absence.
- TypeScript format, lint, typecheck, and build.

## E2E primary validation matrix

| Scenario | Required evidence |
| --- | --- |
| Default retention | Admin API/UI show 30 days and future-only scope |
| Permission boundary | system admin can update; workspace owner/member cannot |
| Future-only update | old deadlines remain; new archive uses the new revision |
| Shorter existing recalculation | preview count matches; overdue roots become due |
| Longer existing recalculation | pending purge deadline moves later |
| Finite to Unlimited | deadline clears and unstarted job is cancelled |
| Unlimited to finite | deadline and job are created |
| Purge-started exclusion | fencing/cleaning root is shown and skipped |
| Recalculation progress | Admin UI reaches authoritative completed counts |
| Archive list | archived root disappears from active list and appears in archived list |
| Restore | complete subtree returns before fencing |
| Active-child safety | archive fails while a descendant is active |
| Delayed wake-up fencing | archived root/child does not resume |
| Zero-day purge | archive succeeds; next manual scheduler pass owns deletion |
| ModelFile cleanup | blob is deleted before metadata disappears |
| Artifact cleanup | root and child blobs are deleted |
| ExchangeFile claim | pre-session source/preview atomically bind to one root |
| ExchangeFile purge | bound source/preview are deleted; unbound file remains |
| Object-store failure | purge stays retryable and session remains |
| Worktree cleanup | root/child allocations and branches are removed safely |
| Runner failure | purge remains retryable with ownership metadata intact |
| Final subtree deletion | root, child, nested sessions and DB-owned rows disappear |
| Public surface | permanent-delete API and UI are absent |
| Migration grace | historical archive is not immediately deleted |

## Fixture and prerequisite requirements

Required deterministic fixtures:

- system administrator, workspace owner, and ordinary workspace member;
- Agent with team-primary and non-primary roots;
- root/child/nested SessionAgent tree with inactive and active variants;
- finite and Unlimited archive settings revisions;
- recalculation applications in pending, running, retrying, and completed states;
- purge jobs in pending, fencing, cleaning, retry-wait, and completed states;
- ModelFiles and Artifacts with present and already-missing blobs;
- unbound ExchangeFile and root-bound source/preview pairs;
- root- and child-created Git worktree allocations;
- pre-feature archived-session migration data.

Object storage uses the deterministic local test service. Worktree behavior uses the typed runner test implementation in required CI. A real runtime-provider filesystem check may run as optional testenv evidence only when its prerequisite is available; once available, functional failure must fail rather than skip.

No live cloud credentials are required. Test evidence must not contain file bodies, transcripts, secrets, or OAuth credentials.

## Validation commands

Backend commands run from `python/apps/azents`:

- `uv run ruff check --fix .`
- `uv run ruff format .`
- `uv run pyright`
- targeted `uv run pytest ...` during each phase;
- full relevant backend suite before validation completion.

TypeScript commands run from `typescript`:

- `pnpm run format`
- `pnpm run lint`
- `pnpm run typecheck`
- `pnpm run build`

E2E commands run from `testenv/azents/e2e` through the existing deterministic environment and manual scheduler trigger boundary.

The validation PR records exact commands, environment, results, screenshots for Admin/Main Web states, external-resource assertions, and a strict implementation/spec comparison table.

## Spec impact candidates

- `docs/azents/spec/domain/conversation.md`
  - archive metadata, subtree archive/restore, archived browser, purge boundary, hard-delete removal;
  - ExchangeFile root retention ownership.
- `docs/azents/spec/flow/file-exchange-storage.md`
  - ownership claim, same-tree access, purge as an earlier terminal boundary.
- `docs/azents/spec/flow/periodic-execution.md`
  - retention recalculation and archived-session purge tasks.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - archived-session execution admission and broker fencing.
- A new or existing Admin/system domain spec for DB-backed settings, impact preview, and recalculation applications.

Spec promotion occurs only after E2E validation. The design receives `implemented: 2026-07-19` only in the spec-promotion PR if all required behavior is implemented and verified.

## Rollout and migration

- Add only new Alembic revisions and update the revision pointer.
- Create the default settings row with 30 days.
- Preserve historical archived timestamps where available, but assign existing archived roots a new activation-time-plus-30-day deadline.
- Do not infer historical ExchangeFile ownership from event URIs; legacy rows remain unbound on existing TTL.
- Deploy schema and admission fencing before enabling purge finalization.
- Use bounded jobs and scheduler leases so horizontal scheduler instances remain safe.
- Observe overdue age, retries, cleanup failures, and recalculation progress before operationally lowering retention.
- Do not add environment-variable fallback for the Admin-managed setting.

## Known blockers and manual actions

No known implementation blocker exists.

Potential environment limitation:

- real runtime-provider worktree filesystem E2E may be unavailable in standard CI. The typed runner test is required; real-provider evidence is optional only when the declared prerequisite is absent.

Required manual actions:

- GitHub review and merge are outside implementation execution. No PR is merged without explicit approval.

## Cleanup

After implementation, E2E validation, and spec promotion:

- remove this plan in PR 10/10;
- retain ADR-0168 as immutable decision history;
- retain the implemented design for rationale;
- use living specs and code as the current-behavior source of truth.
