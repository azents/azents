---
title: "Transaction Ownership Phase 27: Terminal and Mailbox Prerequisites"
created: 2026-10-02
tags: [backend, engine, mailbox, architecture, database]
---

# Phase Execution Plan

- Phase: `27, canonical terminal and Mailbox database compositions`.
- Branch/base: `refactor/transaction-ownership-261002-15-terminal-prerequisites`
  → `refactor/transaction-ownership-261002-14-engine-input` at `456d1c39c`.
  Phase 26 PR #2049 passed CI before rebasing; its new head reruns CI after
  the Historical Memory integration. No merge is authorized.
- PR boundary: extract the database-only Mailbox admission, AgentMailbox, and
  terminal-finalization primitives into canonical repositories; replace the
  terminal-result repair service's three direct scopes with completed operations.
  This removes the service dependencies that block later Engine/Worker ownership.
- Inputs: Phase 26; current Mailbox/terminal caller inventory and authority/lock
  evidence at `4b05fc9f6`; existing narrow repositories and terminal semantics.
- Deliverables: canonical admission DTOs and database composition, canonical
  AgentMailbox and terminal-finalization repositories, completed repair operations,
  updated direct callers/DI/tests, no obsolete forwarding service APIs.
- Non-goals: enclosing Chat/External Channel acceptance transactions, Engine
  output/generated-file/terminal ownership, Worker lifecycle callback ownership,
  public contracts, schemas, retry/delivery policy, new locks or configuration.
- Interfaces: preserve admission idempotency/upsert behavior and pre-read created
  flag, sorted distinct wakes and replay wake reapplication, idle no-wake,
  tree/Session prelock and existing lock order, queue-only parent results,
  `agent_result:{run.id}`, Stop precedence, activity/delivery-marker atomicity,
  safe result text, cancellation and distinct repair vs suppression semantics.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Execution Loop Spec.
- Design delta: `None`.
- Removal obligations: remove MailboxService's two admission DTO definitions and
  five admission methods; remove the DB-only AgentMailbox/terminal service units
  after relocating their canonical definitions and callers; remove three repair
  service-owned scopes. No aliases, re-exports, forwarding façade, optional-session
  dual mode, general DB callback, or repository-to-service dependency is added.
- Absence verification: defining-module/caller/import searches, direct-context
  checks, completed-operation/rollback tests and preserved prelock order.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Mailbox admission and application callers | `/root/tx-chat-inventory` | new repos/mailbox/admission_data.py, admission.py, admission_test.py; services/mailbox.py, agent_session_input.py, chat/__init__.py, chat_write.py, external_channel/ingress_queue.py, mailbox_ingestion_store.py; their tests and worker/session/idle_continuation_test.py | narrow Mailbox/AgentSession repositories | canonical admission primitives/DTOs, completed batch; obsolete service methods removed | replay/profile race, sorted wakes, no-wake, rollback and closure; preserved surrounding tests |
| AgentMailbox and terminal compositions | `/root/tx-runtime-inventory` | canonical AgentMailbox/terminal/repair repository modules/tests; services/agent_mailbox.py, terminal_finalization.py, subagent_terminal_result.py and corresponding tests; engine/events/execution.py, finalization.py, engine_adapter.py and their tests; worker/session/lifecycle.py and related tests | canonical admission API | no repository service dependency; completed repair; canonical terminal caller wiring | prelock order, Stop precedence, parent-result idempotency/rollback, distinct repair failure semantics |
| Integration and documentation | `/root` | phase/master plans, related Specs, integration corrections | both stable workstreams | integrated checkpoint and PR | root-owned full pytest/ty/pre-commit, independent review and CI |

- Shared contract: `MailboxAdmissionRepository` receives required injected
  session_manager, mailbox_item_repository and agent_session_repository.
  `enqueue_in_session`, `enqueue_many_in_session` and
  `enqueue_idle_continuations_in_session` are DB-only composition primitives;
  completed `enqueue_many` owns a transaction. DTOs are defined directly in
  `repos/mailbox/admission_data.py`. Runtime owns AgentMailbox and its tests,
  including their caller migration; Chat must not edit those files.
- Integration order: admission data/primitive, caller rewiring; AgentMailbox
  composition; terminal composition and completed repair; direct Engine/Worker
  import/DI updates; root integrates documentation and validation.
- Atomic groups: normal admission stays inside its existing larger acceptance
  operation; terminal Run/mailbox/activity/delivery marker remains one transaction.
  Single-attempt execution prelock occurs before Run mutation; it is not replaced
  with a retrying lock while prior locks or writes are retained.
- External-effect boundary: all new repositories execute database and pure work
  only. Repair best-effort logging/counting stays in the application after completed
  operations; existing external notifications/publication remain outside DB work.
- Independent review: `/root/phase25-independent-review`, read-only, requested by
  root for the complete stable integrated diff after validation.
- Final validation: root focused admission/terminal/repair/Chat/input/ingress/idle/
  Engine/Worker tests, full backend pytest and `ty --error-on-warning`, pre-commit,
  removed-symbol/import/session checks, and applicable required PR CI.
- Scope-drift check: no behavior, schema, dependency, provider, API, delivery,
  retry, fallback, queue, configuration, or new locking mechanism. Do not unify
  coordinator suppression with repair's existing ValueError/best-effort outcomes.
- Context checkpoint: the admission prerequisite alone removes one unused
  service scope, not thirteen admission calls. Nine larger mutation contexts,
  Chat creation's companion read, and Engine/Worker terminal outer groups remain
  assigned residual violations until their complete repository compositions
  migrate. Directly invoking an in-session repository primitive from those
  transitional application callers is not counted as REQ-1 completion.
- Test replacement: the old Worker idle fake repository incorrectly composed a
  mixed-I/O MailboxService and must be rewritten around canonical idle input/
  completed-operation evidence; production idle-continuation orchestration is not
  changed to accommodate that obsolete fake.

## Implementation and Validation Checkpoint

- Mailbox admission and its two detached DTOs now have canonical repository
  definitions. The five old service admission methods and all old DTO imports
  are removed. The twelve new admission cases cover real PostgreSQL transaction
  closure, sorted distinct wakes, replay and no-wake behavior, late failure,
  task cancellation, profile rollback, and returned upsert-race validation.
- AgentMailbox and normal terminal finalization now compose only database
  repositories. Historical repair uses completed candidate/direct-child/delivery
  operations; its service retains only best-effort logging and outcome counting.
  Canonical safe terminal text and finalization outcomes have one defining module.
- Engine/Worker dependency wiring and all 59 static execution constructors are
  updated. The terminal collaborator remains nullable with the same behavior,
  but every caller explicitly chooses its value. No fallback is introduced.
- Root integrated focused validation: `336 passed`. Full backend validation:
  `6842 passed, 3 skipped`. The skips are memory variants of one Redis-only
  retention test and two Redis-only stale-index tests, not failed prerequisites.
- Full backend `ty --error-on-warning`, all pre-commit hooks, and
  `git diff --check` passed with explicit zero exit markers. Implementation-owner
  focused results were `327 passed` for Chat/Mailbox and `171 passed` for terminal,
  independently of root's integrated counts.
- Removed service symbols/imports, old admission calls, and new repository
  service/Worker imports are absent. Application direct-context candidates are
  610 across 111 files, down from the Phase 26 checkpoint of 615; these are
  discovery counts, not a claim of full ownership completion.
- Nine acceptance mutation scopes, Chat creation's companion read, and the
  eleven Engine contexts remain assigned subsequent work. Existing atomicity
  is preserved during the explicit in-session prerequisite transition.
- Independent review of all 49 changed files found no issues; the reviewer
  independently passed 72 PostgreSQL/admission/terminal/repair/idle cases.
- Design delta: `None`; no new lock, schema, retry, or public behavior.

## Rebase Checkpoint

- The requester reported a conflict in PR #2049 after the Historical Memory
  stack merged. The stack was rebased onto `main` at `cf881e8c5`, preserving
  both documentation records and advancing Spec versions monotonically.
- Phase 26 now uses execution Spec 198; this phase uses execution Spec 199,
  Toolkit Spec 128, and Conversation Spec 177. Only changelog/version metadata
  conflicted. The range-diff confirms no change to the reviewed Python code.
- Latest-base full backend validation: `6931 passed, 3 skipped`. Full backend
  `ty --error-on-warning`, pre-commit, and diff checks passed again.
- The 610-context checkpoint above belongs to the pre-Historical-Memory
  inventory. Newly integrated Memory/VFS application paths are explicitly
  assigned incremental inspection before the final coverage claim.
