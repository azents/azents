---
title: "Session Model Change Implementation Plan"
created: 2026-08-19
tags: [model, session, chat, migration, api, engine, frontend, testenv]
---

# Session Model Change Implementation Plan

- Requirements: [`model-260819/REQ`](../requirements/model-260819-session-model-change.md)
- Decisions: [`model-260819/ADR`](../adr/model-260819-session-model-change.md)
- Approved Design: [`model-260819/DESIGN`](../design/model-260819-session-model-change.md)
- Approved Design revision: `2`
- Approved mechanism IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M9`, `M10`, `M11`
- Design delta: `None`
- Implementation owner: Primary agent (`/root`)
- Independent reviewer: `/root/model-260819-implementation-reviewer`

## Delivery Shape

The feature ships as four stacked PRs. Each phase has a tracked execution plan, a
non-overlapping implementation boundary, focused validation, and review by the same
independent reviewer. Each phase PR is opened before the next phase begins. All four
PRs are created before stack-wide CI monitoring begins.

| Phase | Branch | Base | PR title | Approved mechanisms | Primary boundary |
| --- | --- | --- | --- | --- | --- |
| 1 | `feature/model-260819-1-session-profile-foundation` | `origin/main` | `Session model change [1/4]: Add the applied profile foundation` | `M1`, `M2`, `M3`, `M10` | applied/prepared state split, forward migration, repository/API/idempotency, OpenAPI and generated clients |
| 2 | `feature/model-260819-2-admission-turn-boundaries` | Phase 1 | `Session model change [2/4]: Apply profiles at admission and turn boundaries` | `M4`, `M5`, `M6`, `M9`, `M10` | explicit-input admission, promotion removal, fresh main-model boundary resolution, retry/recovery and fail-closed behavior |
| 3 | `feature/model-260819-3-composer-application` | Phase 2 | `Session model change [3/4]: Connect the Composer to Session model state` | `M7`, `M8`, `M11` | effective Composer baseline, model-only Apply, Stop coexistence, cache convergence, browser/local relay removal |
| 4 | `feature/model-260819-4-validation-specs` | Phase 3 | `Session model change [4/4]: Validate and document Session model changes` | full `M1`–`M11` validation | deterministic E2E, migration/release evidence, Living Specs, implementation dates, plan cleanup |

## Fixed Interfaces and Integration Boundaries

- `AgentSession` owns nullable applied label and nullable effort as the durable public
  and future-turn intent. The retained complete `current_*` physical group is prepared
  recovery state only.
- The existing public response names `current_model_target_label` and
  `current_reasoning_effort` remain stable but read applied fields. Physical model,
  provider, settings, limits, and resolution time remain private.
- Agent selectable options remain the only authority for physical model mapping and
  supported explicit effort values.
- `PUT /chat/v1/sessions/{session_id}/model-profile` is the sole transcript-free human
  model mutation. It is root-only, full-replacement, idempotent, and creates no
  mailbox row, transcript event, Run, wake-up, provider call, or WebSocket frame.
- Model-profile replay authorization and Session locking precede idempotency lookup;
  a matching accepted result is returned before current Agent option validation. Only
  a new key validates and mutates.
- Explicit message, edit, and TurnAction profiles apply atomically at admission under
  the canonical Agent-parent-then-Session lock order. Mailbox/event profile fields
  remain immutable request provenance and promotion never mutates applied intent.
- Every fresh main-model boundary resolves current Session intent through current
  Agent options and commits a complete prepared snapshot after Agent/Session and
  owner-generation revalidation. Same-call retry/recovery reuses its prepared state.
- Null applied intent derives the current Agent main/default profile at each fresh
  boundary and as the server-supplied Composer baseline without materializing intent.
- Deterministic late mapping or effort drift fails before provider dispatch without
  fallback, intent rollback, prepared overwrite, or invented physical provenance.
- The Composer alone owns unapplied selection in component memory. Session query and
  authoritative write/refetch projections own applied state. Browser profile
  persistence and concrete-Session profile relays are removed without compatibility
  readers or cleanup writes.
- Lightweight/compaction model behavior, AgentRun lifecycle ownership, implicit
  trigger request shapes, external pickers, and existing WebSocket contracts remain
  unchanged.
- Migration, API, workers, generated clients, and frontend require a coordinated
  release. Mixed old/new inference semantics are unsupported after applied-intent
  traffic begins.

## Phase Dependencies and Context Checkpoints

### Phase 1 — Applied profile foundation

Inputs: approved Design revision 2, current migration head `c05f9971773f`, existing
AgentSession and chat-write idempotency contracts.

Outputs:

- explicit applied-intent and prepared-state domain/repository projections;
- new nullable applied columns, consistency constraint, complete/all-null backfill,
  partial legacy-state failure, and updated migration revision marker;
- retained prepared physical columns and invariant with no AgentRun inference state;
- public Session responses sourced from applied fields;
- idempotent model-profile service and PUT with minimal response and no execution side
  effects;
- OpenAPI plus generated Python and TypeScript public clients; and
- focused domain, repository, migration, service, API, and contract tests.

Checkpoint to Phase 2: stable applied-intent repository/service interfaces, prepared
state retained independently, model-profile PUT available, and explicit-write response
projection shape fixed.

### Phase 2 — Admission and fresh turn boundaries

Inputs: Phase 1 applied/prepared repository types and public/internal response
interfaces.

Outputs:

- explicit message/edit/TurnAction and first-message Team/User admission validate and
  update applied intent in the same transaction as idempotency, mailbox, attachments,
  and Session creation;
- duplicate replay never revalidates or reapplies historical intent;
- promotion no longer writes Session applied intent or chooses freshness through
  equal-label prepared-state reuse;
- every fresh main-model dispatch resolves current Session intent/current Agent
  mapping with final lock and owner-generation revalidation;
- same prepared call retry/recovery remains immutable;
- implicit triggers inherit current Session intent; and
- deterministic late drift uses the existing typed no-provider failure boundary.

Checkpoint to Phase 3: backend semantics are complete and generated/public contracts
are stable for authoritative frontend integration.

### Phase 3 — Composer integration and local-state removal

Inputs: Phase 2 backend behavior and Phase 1 generated TypeScript client.

Outputs:

- effective Composer baseline from explicit applied Session intent or server Agent
  main/default profile;
- pending V2 picker/action visuals, Send-with-profile and empty model-only Apply;
- simultaneous Stop and Apply when both are applicable;
- Session query invalidation after model PUT and explicit-profile writes;
- removal of profile localStorage, draft `inference_profile`, container latest-human
  profile state, concrete `ChatSessionView` relay, `ChatView` callback, and
  subscription-derived profile authority;
- preservation of text/action drafts and command/file/TurnAction behavior; and
- focused component/container/story/browser-facing tests.

Checkpoint to Phase 4: all user-visible behavior and source-of-truth removals are
implemented with stable selectors and deterministic lower-level coverage.

### Phase 4 — Validation, Specs, and cleanup

Inputs: stable Phase 3 diff, migration/client artifacts, testenv prerequisites, and
fresh provider-journal state.

Outputs:

- deterministic public API and browser E2E for model-only application, send,
  null-intent baseline, active-call/next-turn behavior, Agent remap, external/scheduled
  inheritance, idempotency, ordering, permissions, late drift, repair, reload,
  persistence absence, and Stop/Apply coexistence;
- bounded AIMock or continuation barriers with no fixed-sleep ordering;
- migration/cutover and removal/absence evidence;
- Living Spec updates in Conversation, Agent Execution Loop, and Agent; Model Catalog
  re-verification;
- matching `implemented: 2026-08-19` on Requirements and Design after all required
  validation succeeds; and
- deletion of this implementation plan and every model-260819 phase plan.

Checkpoint: all four PRs exist, the full stack is authority-complete and validated,
and no PR is merged without explicit requester approval.

## Workstream Ownership

| Workstream | Owner | Primary paths | Interfaces produced or consumed |
| --- | --- | --- | --- |
| Phase 1 state, migration, API, generated clients | `/root/model-260819-foundation-owner` coordinated by `/root` | `python/apps/azents/src/azents/{core,rdb/repos/services/api/public/chat}/**`, `python/apps/azents/db-schemas/rdb/**`, public OpenAPI/client packages | applied/prepared domain types, repository methods, model-profile request/response and idempotency |
| Phase 2 admission and worker | `/root/model-260819-worker-owner` coordinated by `/root` | `agent_session_input.py`, `chat_write.py`, `mailbox.py`, `worker/run/**`, `engine/run/resolve.py`, focused tests | admission-time applied intent, fresh-boundary prepared state, typed failure and recovery |
| Phase 3 frontend | `/root/model-260819-frontend-owner` coordinated by `/root` | `typescript/apps/azents-web/src/features/chat/**`, chat tRPC router, stories/tests | effective baseline, model-only mutation, cache invalidation, removal of browser/local relay |
| Phase 4 E2E and Specs | `/root/model-260819-validation-owner` coordinated by `/root` | `testenv/azents/e2e/**`, migration validation, `docs/azents/spec/**`, snapshot metadata/plans | deterministic evidence, promoted current behavior, cleanup |
| Independent review | `/root/model-260819-implementation-reviewer` | read-only across every phase plan and diff | authority, security/data-loss, migration, interface, removal, and scope-drift report |

Owners edit only their assigned phase paths after that phase plan is active. The
primary agent integrates shared interfaces, generated artifacts, plans, commits,
branches, PRs, and validation. The reviewer never edits files.

## Removal Obligations

| Removal | Owning phase | Replacement | Absence verification |
| --- | --- | --- | --- |
| combined Session inference state as public applied and physical prepared authority | 1 | separate nullable applied intent and retained complete prepared state | repository divergence tests; public responses read applied fields only; no physical public fields |
| missing transcript-free Session model mutation | 1 | dedicated idempotent model-profile PUT | API/service tests show no mailbox/event/Run/wake/provider/WS effects |
| AgentRun inference snapshot addition | 1 | retained Session prepared group | schema/source search proves no AgentRun inference columns |
| equal label/effort as permission to reuse a stale physical snapshot at a fresh boundary | 2 | current Agent mapping resolution and final revalidation | worker tests and source search prove every fresh boundary pulls current state |
| promotion-time Session applied-intent mutation | 2 | admission-time update; mailbox fields remain provenance | ordering tests and source search find no promotion applied-field writes |
| stale prepared/default/alternate fallback after late drift | 2 | typed fail-closed pre-provider boundary | provider journal remains empty; state preservation assertions |
| `azents.chat.lastSelectedInferenceProfile.*` | 3 | none | source search and browser storage assertions |
| Composer draft `inference_profile` and compatibility restoration | 3 | text and selected-action draft only | serializer/parser tests and reload/browser evidence |
| `latestHumanInferenceProfile`, concrete `ChatSessionView` profile relay, `ChatView` callback, and pending-profile subscription authority | 3 | Session query/effective baseline; `ChatInput` pending memory only | source search and container/component tests |
| new model-profile WebSocket frame | all | ordinary REST response and Session refetch | OpenAPI/live-contract diff and source search |
| mixed old/new binaries after applied-intent writes | 4/release | coordinated drain, migration, and deployment | release evidence and explicit-profile mailbox count-zero query |
| temporary model-260819 plans | 4 | implemented snapshot plus current Living Specs | final tree source search |

## Validation Matrix

- Phase 1: AgentSession domain/repository and ORM tests, generated Alembic migration
  tests, chat-write idempotency/service/API/data-contract tests, OpenAPI dump, Python
  and TypeScript public-client generation, Python Ruff/format/type checks.
- Phase 2: agent-session admission, chat-write, mailbox promotion, resolver, executor,
  recovery, owner-generation, failure, and no-fallback tests plus source-search absence
  checks.
- Phase 3: ChatInput/ChatView/ChatSessionView/container/tRPC tests and stories,
  storage/draft absence checks, TypeScript format/lint/typecheck/build, stable browser
  selectors and responsive visual evidence.
- Phase 4: migration suite; required public E2E; new Main Web Composer E2E; external
  channel and Scheduled Task trigger coverage; full Python/TypeScript/testenv quality;
  provider request journal/order evidence; documentation validators and spec review.
- Deterministic synchronization uses authoritative database/API state or explicit
  barriers. Fixed sleeps or scheduler yields never establish ordering.
- Optional live-provider checks may skip only for an explicit missing-credential reason
  and never replace deterministic release evidence.

## Prerequisites, Risks, and Blockers

- PostgreSQL and the repository migration harness are required for schema and
  idempotency integration tests.
- OpenAPI generation requires the Azents Python environment; Python and TypeScript
  client generators must run from their documented subprojects.
- Required E2E uses AIMock request journals and API/UI-only state changes. No live
  provider credential is required.
- Active-call/next-turn E2E needs an explicit bounded model-call or client-tool
  continuation barrier; adding that test substrate is an agent-owned validation detail,
  not a product mode.
- Main Web currently lacks a Composer E2E and stable selectors; Phase 3 adds only the
  selectors required for deterministic behavior verification.
- Existing uncommitted `ChatInput.tsx` and `ChatInput.stories.tsx` visual-review changes
  are preserved outside Phase 1/2 and reconciled only in Phase 3.
- Cutover drain/deployment is documented and tested but no live database, worker,
  broker, or Kubernetes mutation occurs in this implementation session.
- Any new persisted authority, fallback, queued-switch mode, public frame, or
  user-visible contract returns to feature design. Local implementation refinements
  remain `Design delta: None`.

## Review and Stack Policy

The exact independent reviewer for every phase is
`/root/model-260819-implementation-reviewer`. Review inputs are the confirmed
Requirements, accepted ADR, approved Design revision 2, current Specs, the phase
execution plan, and the stable phase diff. Blocking priorities are Requirements or
Design violations, security/privacy, authorization, data loss, migration safety,
idempotency, lock order, stale-worker/provider duplication, source-of-truth
reintroduction, removal omissions, compatibility fallbacks, and scope drift.

Each phase is committed and opened as a PR before the next phase starts. All four PRs
are created before CI monitoring. Dependent branches are rebased with the repository
stacked-PR workflow when an earlier phase changes. PRs are never merged without
explicit requester approval.
