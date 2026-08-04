---
title: "Session Working Folder Implementation Plan"
created: 2026-08-03
updated: 2026-08-03
tags: [session, workspace, filesystem, backend, frontend, testenv]
---

# Session Working Folder Implementation Plan

## Feature Summary

This plan delivers one context-owned working folder for each root Session tree.
The folder is the preferred location for non-Project work, is always represented
in the existing-session Projects browser, and is subject to one bounded
best-effort deletion attempt after archive commits.

The plan decomposes only the approved mechanisms in
`session-260803/DESIGN`. It does not introduce a new lifecycle, ownership model,
retry coordinator, compatibility fallback, or destructive authority.

## Authoritative Inputs

- Requirements:
  [`session-260803/REQ`](../requirements/session-260803-session-working-folder.md)
- ADR:
  [`session-260803/ADR`](../adr/session-260803-session-working-folder.md)
- Approved Design:
  [`session-260803/DESIGN`](../design/session-260803-session-working-folder.md),
  revision 1, authority `M1` through `M11`
- Current Specs:
  - `docs/azents/spec/domain/conversation.md`
  - `docs/azents/spec/domain/workspace.md`
  - `docs/azents/spec/flow/agent-runtime-persistence.md`
  - `docs/azents/spec/flow/agent-execution-loop.md`
- Project constraints:
  - migrations are generated only through `alembic revision`;
  - the migration chain remains linear;
  - generated public clients are never hand-edited;
  - required E2E state is established through user-facing paths rather than
    direct database writes.

## Approved Mechanisms and Delivery Ownership

| Mechanism | Delivery phase | Authority |
| --- | --- | --- |
| `M1` — exact context-owned path and bounded cleanup state | Phase 1 persistence; Phase 3 cleanup writes; Phase 4 contract migration | `REQ-1`, `REQ-5`, `REQ-6`, `ADR-D1` |
| `M2` — DB-only unique path assignment and migration | Phase 1 expand/backfill; Phase 4 contract migration | `REQ-1`, `REQ-4`, `REQ-7`, `ADR-D1` |
| `M3` — system-only queue-first non-blocking setup action | Phase 1 | `REQ-1`, `REQ-2`, `ADR-D4` |
| `M4` — Runtime guidance and omitted-workdir default | Phase 2 | `REQ-2`, `REQ-4`, `ADR-D4` |
| `M5` — fixed first `session_folder` Projects entry | Phase 2 | `REQ-3`, `ADR-D2` |
| `M6` — protected folder-root mutation policy | Phase 2 | `REQ-3`, `REQ-6`, `ADR-D2` |
| `M7` — new worktrees under the stored folder; legacy paths retained | Phase 3 | `REQ-6`, `REQ-7`, `ADR-D1`, `ADR-D2` |
| `M8` — commit-first Git and whole-folder archive cleanup | Phase 3 | `REQ-5`, `REQ-6`, `REQ-7`, `ADR-D1`, `ADR-D3` |
| `M9` — managed-root validation and lexical symlink-safe deletion | Phase 3 | `REQ-6`, `ADR-D1`, `ADR-D3` |
| `M10` — adoption, explicit retry, and restore enqueue; no reset coordinator | Phase 1 adoption/restore; Phase 2 retry | `REQ-1`, `REQ-3`, `REQ-7`, `ADR-D4` |
| `M11` — database-only retention purge | Phase 3 regression proof; Phase 4 integrated proof | `REQ-5`, current Specs |

Design delta: None.

## Delivery Shape

The implementation spans persistence, mailbox/worker execution, Runtime defaults,
public API and generated clients, Web UI, workspace mutation policy, Git worktree
lifecycle, Runner deletion, archive behavior, and deterministic E2E. These
interfaces have sequential dependencies and distinct destructive-safety review
boundaries, so delivery uses four stacked PRs.

Stack title prefix: `Session working folder`

| Order | Branch | PR title | Deliverable | Base |
| --- | --- | --- | --- | --- |
| 1 | `feat/session-working-folder-1-context-setup` | `Session working folder [1/4]: Persist context and setup action` | Context path/cleanup schema, expand/backfill migration, queue-first system setup action, adoption and restore enqueue | `main` |
| 2 | `feat/session-working-folder-2-runtime-projects` | `Session working folder [2/4]: Add Runtime default and Projects UX` | Prompt/workdir default, fixed manifest entry, retry API, protected-root policy, generated clients, Web UX | Phase 1 |
| 3 | `feat/session-working-folder-3-worktree-archive` | `Session working folder [3/4]: Enforce worktree and archive safety` | New worktree placement, legacy classification, post-commit cleanup, symlink-safe Runner deletion, purge regression | Phase 2 |
| 4 | `feat/session-working-folder-4-e2e-spec-cleanup` | `Session working folder [4/4]: Verify E2E and promote specs` | Contract migration after zero-null proof, integrated E2E, current-Spec promotion, snapshot implementation marking, plan cleanup | Phase 3 |

Each phase gets a tracked execution plan before implementation. Each PR requests
the exact independent reviewer `hardtack`. All four PRs are created before
stack-wide CI monitoring. No PR is merged without explicit requester approval.

## Stable Ownership and Review

| Role | Owner | Responsibility |
| --- | --- | --- |
| Primary implementation owner | `/root` | Plans, implementation, generated artifacts, integration, validation, branches, PRs, and checkpoints |
| Independent reviewer | `hardtack` | Read-only review against Requirements, ADR, approved Design, phase contract, destructive-safety boundaries, and final diff |

There is one implementation owner, so path ownership does not overlap. The
reviewer does not implement corrections and is requested on every phase PR.

## Stable Interfaces

The following interfaces are fixed before implementation:

- `SessionAgentContext.working_folder_path` is the exact destructive-ownership
  path. No consumer derives it from a handle or naming convention.
- New paths use
  `/workspace/agent/.azents/sessions/{root_session_handle}`.
- Cleanup state is bounded context metadata; it is not a retry queue or durable
  physical-existence projection.
- `create_session_working_folder` is a pathless system TurnAction. The stored
  context supplies the target.
- Initial setup is enqueued first with `QUEUE_ONLY`. A requested worktree or user
  input supplies the wake and FIFO executes setup first.
- Setup failure terminalizes normally and does not invalidate context or block
  later input/model work.
- Existing `file.mkdir` Runner operation is reused. No new Runtime protocol is
  introduced.
- User-authored action request schemas exclude the system action; durable and
  response projections can decode it.
- Existing-session Projects manifests prepend a backend-owned `session_folder`
  source. Preview manifests remain Project-only.
- The Session-folder entry is not a Project registry row and supplies no
  Project-scoped instructions, Skills, Git lifecycle, or registry removal.
- Product mutation services and the dedicated file-delete tool protect the exact
  root and operations that would remove or overwrite it. Descendant operations
  remain allowed.
- New worktrees allocate beneath the stored path; existing allocation rows retain
  their recorded paths.
- Archive commits lifecycle state before external I/O, attempts each typed Git
  cleanup once, then attempts exact folder deletion once regardless of Git
  outcomes.
- Folder cleanup never follows root or descendant symlinks.
- Restore queues setup but restores no bytes. Retention purge is database-only.

## Phase 1 — Context Persistence and Setup Action

### Approved scope

- Mechanisms: `M1`, `M2`, `M3`, and the adoption/restore part of `M10`.
- Add context path and cleanup fields plus the PostgreSQL cleanup enum.
- Generate an expand migration that adds nullable fields, backfills every context
  from its root Session handle, fails on invalid ownership input, initializes
  cleanup state, and adds transitional uniqueness for populated paths.
- Make every new root context write the exact generated path transactionally.
- Add a system-only `create_session_working_folder` action before worktree setup
  and user input.
- Preserve empty-Session behavior by using `QUEUE_ONLY` without a Runtime wake.
- Ensure the next eligible existing-session input adopts a missing setup action
  before the new input, using a context-scoped deterministic idempotency key.
- Queue the same action after restore without waking only for folder creation.
- Execute the action through existing Runner `file.mkdir`, classify bounded
  outcomes, terminalize existing/create success, and let failure continue FIFO.
- Split action unions where required so the system action cannot be submitted as
  a public user-authored action while public execution/history projections remain
  decodable.
- Regenerate OpenAPI and public clients if the response discriminator changes.

### Dependencies and integration boundary

This phase depends only on the approved snapshot and the current linear migration
head. It creates the persistence and action contracts consumed by all later
phases. It does not change command workdir, Projects manifests, workspace root
mutation policy, worktree allocation, archive cleanup, or UI retry.

### Context checkpoint

Record the generated migration revision, backfill and invariant evidence, exact
new repository/action interfaces, FIFO and no-wake evidence, restore/adoption
evidence, generated-artifact changes, remaining nullable-contract obligation,
risks, and Phase 2 inputs.

## Phase 2 — Runtime Default and Projects UX

### Approved scope

- Mechanisms: `M4`, `M5`, `M6`, and explicit retry from `M10`.
- Inject the exact stored path and four-category lifetime guidance into Runtime
  instructions.
- Substitute the stored path only when `exec_command` omits `workdir`; explicit
  workdirs retain precedence.
- Add the first backend-owned `session_folder` manifest entry and its
  `prepare_session_folder` capability.
- Add the authenticated active-root retry route that enqueues the pathless setup
  action and wakes the Session.
- Protect all non-purged context folder roots and relevant ancestors/destinations
  in workspace delete/move/bulk services and the dedicated file-delete tool.
- Regenerate OpenAPI and public clients.
- Render the fixed entry, disposable lifetime, missing/failed visibility, retry,
  protected root controls, and system setup execution without a user bubble.

### Dependencies and integration boundary

Consumes the exact context path and setup-action projection from Phase 1. It does
not relocate worktrees or enable archive folder deletion.

### Context checkpoint

Record prompt/workdir snapshots, manifest/API schema changes, generated clients,
protected-root test evidence, Web states and stories, retry behavior, and Phase 3
inputs.

## Phase 3 — Worktree and Archive Cleanup Safety

### Approved scope

- Mechanisms: `M7`, `M8`, `M9`, and regression preservation of `M11`.
- Allocate new worktrees below
  `{working_folder_path}/worktrees/{repository_leaf}` and retain recorded legacy
  paths unchanged.
- Classify new and legacy cleanup paths explicitly; retain legacy parent cleanup
  only for legacy allocations.
- Set folder cleanup `pending` in the archive transaction.
- After commit, attempt every eligible typed Git cleanup once and then one exact
  folder deletion regardless of Git results.
- Persist the bounded terminal folder-cleanup result without changing archive
  success.
- Change delete-specific Runner resolution to lexical `lstat` behavior so a root
  symlink is unlinked and descendant symlinks are not followed.
- Preserve restore no-byte-recovery and database-only purge behavior.

### Dependencies and integration boundary

Consumes the exact stored path, protected root policy, and setup/retry behavior
from Phases 1 and 2. It is the only phase that activates destructive Session-folder
deletion.

### Context checkpoint

Record new/legacy allocation evidence, archive commit-before-I/O evidence, Git
failure followed by folder deletion, symlink sentinel preservation, bounded state
results, purge absence proof, and Phase 4 prerequisites.

## Phase 4 — Integrated E2E, Contract Migration, Spec Promotion, and Cleanup

### Approved scope

- Reverify mechanisms `M1` through `M11`; introduce no new mechanism.
- Validate zero null `working_folder_path` values after expand/backfill behavior
  has been exercised in the equivalent deployment environment.
- Generate the contract migration that makes the path non-null and replaces the
  transitional unique index with the final unique constraint.
- Run deterministic API/Runtime/Web E2E for the complete Design matrix.
- Run migration, backend, Runner, generated-client, TypeScript, and testenv checks.
- Run `/spec-review` and promote verified current behavior to the affected Specs.
- Mark Requirements and Design implemented with the same verified KST date.
- Delete this implementation plan and all Session-working-folder phase plans
  after Specs become authoritative.

### Dependencies and integration boundary

The contract migration is blocked until zero-null evidence exists. The phase does
not deploy, reset Runtimes, delete live data, or merge PRs.

### Context checkpoint

Record the complete validation matrix, environment and prerequisite snapshot,
contract-migration evidence, final authority and removal audit, promoted Specs,
remaining operational risks, and the complete PR stack.

## Removal and Replacement Obligations

| Existing unit or behavior | Owning phase | Required absence evidence |
| --- | --- | --- |
| Ordinary-output prompt/default points to `/workspace/agent` | Phase 2 | Four storage categories in prompt snapshots; omitted workdir uses stored folder |
| Active Projects mode may be empty and only Project-row-backed | Phase 2 | Session entry is first without a Project row; preview remains unchanged |
| New worktrees always use the legacy managed-worktree root | Phase 3 | New allocation path tests use stored folder; existing rows remain unchanged |
| New cleanup may remove the legacy parent directory | Phase 3 | New-path cleanup never calls legacy parent removal; legacy coverage remains |
| Delete resolves a root symlink before `lstat` | Phase 3 | Root-symlink deletion removes only the link and preserves external target |
| Workspace mutation guards protect only Agent Workspace root | Phase 2 | Exact root, ancestor, overwrite, and bulk atomic rejection tests |
| Archive has only Git cleanup after commit | Phase 3 | Folder delete is observed after Git success and failure |
| Action/catalog completion acts as physical setup truth | Phases 1–2 | Failed action followed by Agent/UI repair is reflected by Runner stat/list without DB physical-state enum |
| Retention purge has no filesystem participant | None; verify in Phases 3–4 | Tests prove no Runtime, Git, or filesystem call |

No obsolete persistence table, compatibility fallback, legacy path rewrite, Runtime
reset coordinator, post-delete Git repair, or purge retry may be added.

## Validation Matrix

| Boundary | Required validation |
| --- | --- |
| Persistence | Alembic single-head check; upgrade/backfill/contract tests; context repository tests; zero-null and uniqueness evidence |
| Mailbox/action | Initial ordering, empty no-wake, FIFO-first wake, system provenance, user-write rejection, idempotency, adoption, restore, cancellation, failure continuation |
| Runtime setup | Existing directory, creation, concurrent convergence, missing Runtime, malformed path, file/symlink target, bounded result, no context invalidation |
| Runtime default | Prompt snapshots, explicit workdir precedence, omitted workdir substitution, Agent repair command guidance |
| Project Browser/API | First system entry, missing state, no registry row, duplicate nested/top-level worktree, preview unchanged, retry authorization |
| Workspace mutation | Exact root, ancestor, destination overwrite, bulk prevalidation, descendant operations, purged-context release, dedicated delete tool |
| Worktree | New path allocation, legacy path retention, Project registration, new/legacy cleanup classification |
| Archive/Runner | Commit-before-I/O, one attempt, Git failure continuation, lexical root symlink, descendant symlink, already absent, Runtime unavailable, bounded result, restore and purge |
| Generated clients | OpenAPI dump, Python public-client generation/checks, TypeScript public-client generation/typecheck |
| Web | Container/component tests, pure-state stories, root-control states, action-state refresh, desktop/mobile browser assertions |
| E2E | New empty Session, default work, root/subagent sharing, worktree duplicate navigation, setup failure and repair, root protection, archive sentinel, restore, legacy worktree |
| Documentation | `git diff --check`, docs validator/index pre-commit, `/spec-review`, final authority/removal audit |

Required deterministic tests fail rather than skip when fixtures or Runtime
prerequisites are absent. No external credentialed or live-provider test is
required.

## Rollout, External Actions, and Rollback

1. Phase 1 supplies the expand/backfill migration and nullable application schema.
2. Phases 1–3 activate behavior against populated stored paths.
3. Phase 4 records zero-null evidence before adding the contract migration.
4. Deployment and live-database verification are external actions and are not
   performed by this implementation plan without explicit approval.
5. Rollback before destructive archive activation may ignore additive metadata.
   Rollback after archive deletion cannot restore bytes, move legacy worktrees, or
   derive a replacement path.

No Kubernetes write, live Runtime reset, archive operation, or other live
infrastructure mutation is authorized by this plan.

## Blockers and Scope-Drift Rules

Current blockers: None.

The following findings require returning to feature design before implementation:

- a need to derive a destructive path instead of using the stored path;
- a new setup retry daemon, Runtime-reset coordinator, or execution-admission gate;
- a new Session-folder registry or allocation authority;
- changed user-visible retention or archive semantics;
- selective folder preservation after Git failure;
- purge-time filesystem cleanup;
- a different canonical Agent Workspace root.

Local helper names, bounded result reason names, query shapes, fixture composition,
and equivalent module boundaries remain implementation-owned details.

## Plan Cleanup

This plan and every Session-working-folder phase execution plan are temporary.
Phase 4 removes them only after:

- all approved mechanisms and removal obligations are implemented and verified;
- contract-migration prerequisites are satisfied;
- deterministic E2E and required quality checks pass;
- current Specs are promoted; and
- Requirements and Design receive the same verified implementation date.
