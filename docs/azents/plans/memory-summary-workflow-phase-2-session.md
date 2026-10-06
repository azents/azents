---
title: "Memory Summary Workflow Phase 2: Common Session Foundation"
created: 2026-10-06
tags: [memory, implementation, lifecycle, engine]
---

# Phase Execution Plan

- Phase: `2/3 - common execution Session, Conversation relation and retained audit lifecycle`.
- Branch/base: `feature/memory-summary-session-261006` -> `feature/memory-summary-workflow-261006` (`f61ce3bb7`, PR #2192).
- PR boundary: single-writer Conversation extraction, common owner/head/Run/Event projection, generic archive/retention/purge and real protected audit reads. Ordinary conversation identities and behavior preserved; Memory host activation remains phase 3.
- Inputs: approved `memory-261006` M5/M6 plus retained common execution policy M4/M7, existing Run/Event FKs and lifecycle participants.
- Deliverables: internal execution can exist without public Conversation placeholders; ordinary public reads require a Conversation relation; one lifecycle root/resource target and purge pipeline handles conversation groups and singleton internal execution; archived canonical records remain operationally inspectable.
- Non-goals: new Memory producer/submit activation, runtime document versioning, separate transcript/owner/purger, new admin UI/role, deadline or retention changes, production actuation.
- Interfaces: existing Session IDs remain `agent_sessions` Run/Event/FK identities; Conversation profile owns public fields; narrow common execution DTO/authority reads cannot construct public conversation data for profile-free rows. Existing public root/subagent relations remain domain associations only.
- Approved mechanisms: `M5, M6`, retained `M4, M7` boundaries.
- Authority: `memory-261006/REQ-6..11`, `memory-261006/ADR-D2/D3/D5`, `memory-261006/DESIGN`.
- Design delta: `None`.

## Preservation contracts

1. Backfill all existing root/subagent rows, switch public writers/readers and remove moved Session columns in their owning migration. No dual writer/legacy fallback.
2. Public handle/title/title-generation/pin/user-input and root/subagent product/primary semantics belong to Conversation. Common model context/owner/activity/stop/archive/retention state remains Session-owned.
3. Preserve exact active Team-primary DB uniqueness. A read-only DB-constrained Conversation index projection may reference common `(id, agent_id, status)` through one composite FK with update/delete cascade; this is materialization of existing uniqueness, not a second authoritative status or new primary policy. Do not add an independent current-primary selection source. Test actual status/FK contention, create/archive/restore and rollback.
4. Pair common+Conversation creation atomically; handle collisions roll back the full trial without orphan Session. Public get/list/history/source operations use a joined projection; common owner/head operations do not require it.
5. Extract common lifecycle-root/group membership from existing public-tree semantics. Conversation roots retain child grouping; an internal execution is its own singleton lifecycle root without fabricated SessionAgent. Revalidate exact target membership and active effects before finalization.
6. Shared owner validation/fencing applies at dependent writes; domain-specific lineage/mailbox projection stays separate. Do not retain a second Memory lease as a common owner substitute.
7. Admin diagnostics use existing system-admin authentication and bounded safe canonical Session/event/file reads. No ordinary Conversation API access to archived internal records.
8. Canonical durable files/events needed for audit survive archive and follow retention. Live Runtime/worktree cleanup is separate; current domain result/source/pending/outcome is outside temporary Session cascade.

## Workstreams and ownership

| Workstream | Owner | Owned paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Common/Conversation schema and conversation repository conversion | assigned storage implementer | RDB Session/Conversation + migration, core execution/Conversation DTO, repos/agent_session and repos/agent_execution | typed single storage writer/joins, preserved creation and primary invariants | migration/backfill/collision/public regression/typecheck |
| Common lifecycle target/archive/purge and operational read | assigned lifecycle implementer | retention/purge/lifecycle repositories/services + admin debug service/routes | one generic target/pipeline, retained diagnostic reads | actual archived audit endpoint, finite/Unlimited/active/purge/rollback/schema graph |
| Domain source/direct SQL consumers | root-assigned bounded implementation lane | historical/source/history/Memory-VFS direct readers, related tests | Conversation join boundary, no private source admission | exact-ID/source/cross-scope tests |
| Common owner/context/Worker integration and root final integration | /root | execution authority/head/compaction/Worker seams + tests | reusable common projection without public tree preconditions | stale-owner/ordinary run/context/recovery regressions |

Root binds exact non-overlapping assignments before edits. Shared schema/DTO interface changes are communicated before consumers change. Only root requests review, fixes integration, runs integrated validation and commits.

## Removal and absence evidence

- Remove conversation-only columns/indexes/checks from common Session and convert SQL consumers/fixtures; confirm no writes or public projections read the removed columns.
- Remove ROOT-only target assumption from common retention/purge/finalizer; absence of SessionAgent must not falsely complete an undeleted internal target.
- Remove common authority dependence on public Conversation DTO/root tree; retain it only in conversation projection.
- No fake handle/title/root, new per-kind scheduler/purger, double owner, early audit payload erase or old-column fallback.

## Validation and checkpoint

Root runs full backend Ruff/format/typechecker plus focused real PostgreSQL migration/Session/owner/lifecycle/source tests and protected admin route tests, then required public/Worker regressions and applicable generated-client checks. Use actual lock synchronization rather than sleeps. Document exact evidence; no production DB/cluster changes.

- Independent reviewer: `/root/memory-feature-reviewer` on the complete integrated stable phase diff after root validation.
- Scope-drift check: preserve all ordinary conversation creation/root/subagent/title/pin/primary/archive/restore/stop/context semantics; no unauthorized product policies.
- Context checkpoint: phase 1 PR #2192 is open; no CI monitoring yet. Phase 2 branch created. Scouts confirmed archive currently eagerly cleans live owned worktrees, admin debug lacks transcript read, active-primary unique index crosses the planned storage split, and retention/purge currently requires ROOT SessionAgent. These concrete seams are owning-phase work, not a reason to invent new services or stop the approved feature.

## Completed phase checkpoint

Validated on 2026-10-07 KST. `Design delta: None`.

- Common/public split, backfill, owner/head/Worker controls, generic retained
  lifecycle, current private files, protected audit endpoints, and all direct
  consumers are implemented. The active Team-primary role and uniqueness,
  ordinary Conversation behavior, and exact public scope fences remain intact.
- Profile conditional mutations recheck actual target predicates after the
  common row gate. Real two-connection reservation/title/command races pass.
  Lifecycle membership has an explicit partial index, verified after upgrading
  old root/child/Event data.
- Safe retained file content is redacted before paging. Real admin route tests
  prove authentication, scope denial, retained queryability and continuation
  credential redaction.
- Root full backend: `uv run pytest -q --tb=short` — **11,321 passed,
  3 skipped**, 481.48 seconds. The preceding full run exposed a one-second
  test-only claim-deadline setup assumption; the deadline test now permits three
  seconds of real preparation while retaining the same blocked-resolution,
  cancellation and no-late-dispatch assertions. Product timeout policy is
  unchanged.
- Backend Ruff/format/type checks and commit hooks pass. Admin OpenAPI and
  Python/TypeScript clients were source-generated. Python client template tests
  pass (12), diagnostic API/model imports pass, and admin client/web TypeScript
  checks pass.
- `/root/memory-feature-reviewer` completed independent review and targeted
  re-review. All findings are closed; no material scope drift or unauthorized
  versioning/fallback was found.
- Current Conversation, compaction and periodic lifecycle Specs are updated.
  The full feature's E2E, final spec promotion, plan cleanup and stack CI remain
  at the combined completion boundary.
- Next phase implements the already-approved summary-only input,
  explicit-submit/feedback/same-execution continuation and old contract removal.
  Internal Memory producer activation has not occurred in this phase.
