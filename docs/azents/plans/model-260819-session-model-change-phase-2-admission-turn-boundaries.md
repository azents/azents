---
title: "Session Model Change Phase 2 Admission and Turn Boundaries Plan"
created: 2026-08-19
tags: [model, session, admission, mailbox, worker, engine]
---

# Session Model Change Phase 2 Admission and Turn Boundaries Plan

## Phase Execution Plan

- Phase: `2 — Admission-time application and fresh main-model boundaries`
- Branch/base: `feature/model-260819-2-admission-turn-boundaries` →
  `feature/model-260819-1-session-profile-foundation`
- PR boundary: apply explicit human profiles atomically at admission, remove
  promotion-time applied-profile authority, and resolve current Session intent through
  current Agent mapping at every fresh main-model boundary while preserving same-call
  prepared recovery
- Inputs: completed Phase 1 applied/prepared domain and repository interfaces,
  migration `936373d16d53`, model-profile API/idempotency contract, approved
  `model-260819/DESIGN` revision 2
- Deliverables: admission-time profile validation/application for message, edit,
  TurnAction, and first-message Team/User creation; explicit-write response projection;
  promotion provenance without Session applied writes; fresh-boundary current mapping
  resolution and final Agent/Session/owner-generation revalidation; immutable same-call
  retry/recovery; implicit-trigger inheritance; typed no-provider late-drift failure
- Non-goals: Composer/model-only Apply wiring; browser persistence removal; visual
  behavior; public/browser E2E; Living Spec promotion; live deployment/cutover
- Interfaces: Phase 1 `SessionAppliedInferenceProfile`, independent prepared
  `SessionInferenceState`, AgentSession applied/prepared repository methods,
  `ChatSessionModelProfileResponse`, existing requested-profile mailbox/event
  provenance, existing typed inference-resolution failure codes
- Approved Design mechanisms: `M4`, `M5`, `M6`, `M9`, `M10`
- Authority references: `model-260819/REQ-3`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-9`;
  `model-260819/ADR-D3`, `ADR-D4`, `ADR-D6`; current Conversation, Agent, and Agent
  Execution Loop Specs
- Design delta: `None`
- Removal obligations: promotion-time Session applied-intent mutation; equal-label and
  equal-effort stale physical snapshot reuse as fresh-boundary authority; fallback to
  prior prepared/default/alternate state on deterministic late drift
- Absence verification: source search finds no promotion write to applied fields;
  worker tests prove current Agent remap at every fresh boundary; provider journal and
  state assertions prove no fallback/provider call/prepared overwrite on late failure;
  recovery tests prove same-call prepared snapshot reuse remains

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Explicit admission | `/root/model-260819-worker-owner` | `python/apps/azents/src/azents/services/agent_session_input.py`, `services/chat_write.py`, first-message/root creation integration and focused tests | Phase 1 applied-intent repository and response types | locked Agent-option validation plus atomic applied intent for message/edit/TurnAction/Team/User creation | admission/idempotency/rollback/permission tests |
| Mailbox promotion removal | `/root/model-260819-worker-owner` | `python/apps/azents/src/azents/services/mailbox.py`, related data/tests | admission owns intent | requested-profile provenance retained; promotion never mutates applied intent or selects stale physical state | mailbox ordering/provenance/no-write tests and source search |
| Fresh-boundary resolution | `/root/model-260819-worker-owner` | `python/apps/azents/src/azents/worker/run/executor.py`, `worker/session/lifecycle.py`, `engine/run/resolve.py`, focused tests | Phase 1 applied/prepared split | current Session intent/current Agent mapping resolve, candidate drift retry, final Agent→Session/owner-generation fence, prepared commit | executor resolver remap, same-Run, owner-drift tests |
| Retry, recovery, and late failure | `/root/model-260819-worker-owner` | worker executor/lifecycle, mailbox failure paths and tests | fresh-boundary helper | same-call recovery uses prepared snapshot; deterministic late drift fails closed without fallback/provider dispatch | recovery/failure/repair/no-provider tests |
| Integration validation | `/root` | shared Phase 2 diff and focused command execution | stable owner diff | cross-service integration, generated/public contract consistency, absence checks | root-focused test matrix, Ruff/format/ty, diff check |
| Independent review | `/root/model-260819-implementation-reviewer` | read-only full Phase 2 plan and diff | stable Phase 2 diff | authority/security/data-loss/worker/recovery/removal report | explicit approval or blocking findings |

- Integration order: shared locked profile validator and explicit admission → first-message
  atomic application and write responses → remove promotion writes/equality authority →
  implement fresh-boundary candidate resolution/revalidation/prepared commit → preserve
  recovery path and add late-failure handling → focused integration validation →
  independent review → corrections/revalidation → commit and PR
- Independent review: `/root/model-260819-implementation-reviewer` reviews M4/M5/M6/M9/M10,
  admission rollback and replay ordering, canonical Agent-parent→Session locking,
  owner-generation fencing, old queued explicit-vs-later PUT ordering, implicit-trigger
  semantics, same-call recovery immutability, deterministic FIFO consumption, typed
  no-provider failure, no fallback, and removal of promotion/equality authority
- Final validation: from `python/apps/azents`, focused pytest for
  `agent_session_input_test.py`, `chat_write_test.py`, `mailbox_test.py`,
  `worker/run/executor_test.py`, `worker/session` tests, resolver and AgentSession
  repository tests; Ruff check/format and `ty check --error-on-warning`; source-search
  absence for promotion applied writes and stale equality authority; confirm OpenAPI and
  clients remain unchanged unless explicit-write response schema requires approved
  regeneration
- Scope-drift check: every Phase 2 change maps to M4/M5/M6/M9/M10; no Composer, browser,
  E2E, Living Spec, new persisted authority, Agent fanout/revision, queued switch,
  fallback, WebSocket frame, Redis correctness dependency, or new provider mode is added
- Context checkpoint: Phase 2 completes when every explicit human profile applies at
  admission, promotion is provenance-only, every fresh main-model dispatch resolves
  current Session/Agent state, same-call recovery remains prepared-state-based, late
  drift fails safely with no provider call, focused checks/review pass, and PR 2 is
  open. Remaining scope is Composer integration/removal and final E2E/Specs/cleanup.
