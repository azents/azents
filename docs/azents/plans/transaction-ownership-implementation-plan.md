---
title: "Repository Transaction Ownership Implementation Plan"
created: 2026-09-08
tags: [backend, architecture, database]
---

# Repository Transaction Ownership Implementation Plan

- Requirements: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
- Decisions: [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md)
- Design: [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md), revision 1
- Execution authority: direct requester implementation instruction for M1–M5.
- Design delta: None.
- Independent reviewer: `/root/phase25-independent-review` (read-only, retained
  for every integrated phase from Phase 26 onward; replaces the historical
  `/root/tx-review` role).
- Integration owner: `/root`.

## Current Delivery Limit — 2026-10-03

The requester clarified the current execution boundary: complete Phase37 through
integrated validation, the retained independent review, PR creation and exact-head
CI, then stop. Later phases and their discovery/planning/implementation are not
part of this continuation. Remaining migration coverage and issue #1718 stay open;
there is no Agent merge or whole-feature implementation marking. Earlier continuous
execution entries below remain historical checkpoints.

## Resumed Stack — 2026-10-01

The requester authorized continuous stacked-PR delivery until #1718 is complete.
The remaining current inventory is delivered in this branch chain before CI:

1. Runtime Control read ownership.
2. Engine read ownership.
3. Agent service repository operations.
4. Chat Workspace, Discord settings, idle continuation, and any evidence-backed
   residual application entrypoints.
5. Final inventory, validation, Spec promotion, implementation marking, and plan
   cleanup.

Each PR uses the previous phase branch as its base. Design delta remains `None`;
M1–M5 and REQ-1 through REQ-5 remain the complete authority.

## Stack Extension — 2026-10-01

The post-Phase-15 lexical checkpoint found 598 remaining session contexts across
122 non-repository application files. This is discovery evidence, not 598 confirmed
violations, and it invalidates the earlier assumption that one residual PR plus one
validation PR would complete the issue. Keep the existing PR numbering as historical
stack labels, but continue sequential stacked delivery by bounded domain batches until
every context has a call-path-backed corrected or excluded disposition. Phase 16 owns
the already assigned Chat Workspace, Discord lifecycle/settings, and idle-continuation
slice. Later branches must cover Engine execution/tools, Chat and mailbox, Runtime and
lifecycle workers, account/workspace/configuration services, API/CLI entrypoints, and
other residual groups before final validation and plan cleanup.

Phase 17 starts the Engine execution/tools group with Tool Search working-set,
AGENTS.md and Claude Rules appendix-dedupe, and Todo Toolkit State. It moves the
assigned persisted payloads to pure core models and their completed transaction
lifetimes to repository operations while preserving compaction's existing atomic
working-set reset. Later Engine phases retain model execution, provider output,
MCP/cloud snapshots, and residual event-compaction ownership.

Phase 18 continues that group with Raw MCP, AWS, GCP, and GitHub MCP tool
snapshots plus GitHub selected-installation state. Provider discovery and token
exchange remain outside completed repository operations; MCP OAuth/configuration,
model execution, provider output, and compactor ownership remain later phases.

Phase 19 moves model-visible Memory CRUD/search, Memory prompt scope and summary
reads, and Session History authority/read compositions into completed repository
operations. Runtime behavior/project reads, Scheduled/Subagent tools, MCP OAuth,
model execution, provider output, and compactor ownership remain later phases.

Phase 20 moves Runtime Toolkit behavior/configuration and Session Project reads,
plus MCP OAuth connection load and refresh success/failure finalization, into
completed repository operations. OAuth provider HTTP refresh remains outside
database transactions, and stale credential snapshots still yield to concurrent
refresh. Scheduled/Subagent tools, model execution, provider output, and
compactor ownership remain later phases.

Phase 21 moves the five Scheduled Toolkit and eight Subagent Toolkit direct
session contexts behind completed repository operations. Scheduled channel
registration/deletion and Subagent broker wake/stop plus tree invalidation remain
post-commit effects. Spawn retains one final atomic child-creation transaction
that revalidates the invoking Run and root-tree capacity after detached pure
inference/fork preparation. Model execution, provider output, and compactor
ownership remain later phases.

Phase 22 moves Provider Output scope, retry-preflight, and cleanup-protection
reads into completed repository operations while retaining the existing
database-only metadata admission inside the same transaction as model/tool Event
commit. Object upload and compensation delete remain outside database
transactions. Engine execution and compactor/filter ownership remain later
phases.

Phase 23 moves compaction plan capture and atomic summary finalization into
completed repository operations. Summary generation and enrichment remain
between transactions, while stale-plan revalidation, marker/summary append,
model-input-head movement, compaction model-operation success, and Tool Search
working-set clearing remain one atomic database operation. Engine execution
ownership remains a later phase.

Phase 24 moves standalone execution phase updates, conditional STOPPING
transitions, and ModelFile pin admission into completed repository operations.
Phase publication remains post-commit, and the obsolete session scope around
pure cancelled-result projection is removed. Model-input preparation, output and
tool-result admission, and terminal finalization remain later execution phases.

Phase 25 moves ordinary and generated-file-failure tool-result admission into a
completed repository operation while retaining the same in-session primitive for
atomic user-stop recovery. Successful generated-file metadata admission,
model-output admission, model-input preparation, and terminal finalization remain
later execution phases.

## Continuous Completion — 2026-10-02

The requester renewed continuous execution through the point at which issue #1718
can be closed. PR #2033 is merged; the new baseline is `origin/main` at
`4b05fc9f6`. Remaining delivery is not limited to one Engine slice. Keep opening
reviewable sequential phases, own corrective work and CI to completion, and do
not merge or close the issue before all confirmed violations and coverage gaps
have a verified disposition.

The refreshed AST candidate inventory finds 616 managed session contexts in 113
non-repository, non-RDB backend files, including a test-infrastructure candidate.
This is not a confirmed violation count. Counts also differ from earlier lexical
checkpoints because the baseline and discovery method changed. Read-only domain
scouts classify Chat/Mailbox/External Channel, Runtime/Worker/Scheduler, and
Account/Workspace/Configuration/API entrypoints while Engine implementation
continues. Empty scopes, dependency factories, migrations, test setup and
read-only diagnostics receive explicit exclusions; reachable helpers and live
transaction callbacks remain covered.

Phase 26 moves the complete model-input atomic group into a domain repository:
head and transcript reads, tool-result reconciliation, PREPARING_INPUT mutation,
and persisted availability projections. Concrete database-only repository
composition replaces the live-session pre-lower filter API. Output publication
and compaction remain after transaction completion. Phase 26 PR #2049 passed
all applicable CI at commit `833bd9c59`.

Phase 27 is stacked on that commit and extracts canonical Mailbox admission,
AgentMailbox, terminal finalization, and completed terminal-result repair
operations. The Mailbox and terminal workstreams have non-overlapping ownership;
root retains integration, validation, and the same independent reviewer. Preserve
single-attempt tree/Session prelock before Run writes, queue-only direct-parent
results, activity/delivery-marker atomicity, and the distinct repair/coordinator
failure semantics. Larger Chat/External Channel acceptance contexts and
Engine/Worker terminal outer contexts remain explicit residual violations until
their complete atomic compositions migrate. This prerequisite does not claim
complete repository ownership for those callers.

The Historical Memory stack subsequently advanced `main` to `cf881e8c5`.
The requester's conflict report triggered a stack rebase; Phase 26 now has tip
`456d1c39c`. Documentation-only conflicts retain both feature records, with
execution Specs 198/199 and Toolkit Spec 128. Latest-base full backend validation
passed 6,931 cases with three existing Redis-only memory-variant skips. New
Historical Memory/VFS paths receive incremental entrypoint/callback inspection;
the earlier 616/610 lexical checkpoints remain dated discovery evidence rather
than a claim of current complete coverage.

Phase 28 starts after both rebased PR #2049 and stacked PR #2050 have no
failed or pending normalized CI checks. It removes the entire assigned Event
execution/output/terminal boundary and the Worker failed-run atomic group,
including prepared live-session persistence and model-operation callbacks.
Output admission and terminal completion retain their existing separate
transactions. Worker failure retains one Stop-claim/Event/terminal transaction
with dispatch afterward. Broader Worker, Chat, Runtime, Platform, and newly
integrated Memory ownership remain subsequent work. No new mechanism is added.

Phase 28 PR #2052 is validated at `e5b6ed552` after the requester's second
conflict report and a documentation-only rebase onto `83231ed4b`. Latest local
backend validation passed 6,998 cases with three existing Redis-only variant
skips; ty and pre-commit passed. Latest PR checks are 38 passed, three skipped,
none failed or unfinished; mergeability is CLEAN/MERGEABLE. No Agent merge.

Phase 29 proceeds from that validated parent with 25 Account/Auth lifetimes:
User (6), UserEmail (5), Workspace (6), SystemUserRole (6), and HTTP subject /
Workspace membership admission (2). Preserve account-disable, role cleanup,
Session revocation and purge-job atomicity, the shared system-role advisory lock,
last-admin protection, missing versus accepted deletion, post-commit terminal
invalidation, atomic Workspace plus owner membership, and required/optional HTTP
authorization behavior. Credential's two scopes and six session-taking
declarations remain a named later batch, not a prerequisite or exclusion.
Canonical pure inputs/errors replace touched API-to-repository data imports.
Public/admin OpenAPI must be identical to the saved pre-implementation baseline.
The new main Historical Memory context invalidates the earlier 599-context
checkpoint. A fresh comparable AST scan at the Phase 29 parent finds 600 contexts
in 111 files: the only added candidate is Historical Memory snapshot refresh.
This remains discovery evidence rather than a complete violation count.

Phase 29 implements that entire 25-context slice. The requester merged parent
PR #2052; the phase rebases cleanly onto `main` at `f42dc1f26` without any patch
change. Latest-base backend validation passed 7,111 cases with three existing
Redis-specific memory-variant skips; ty, full pre-commit and exact public/admin
OpenAPI equality passed. The retained independent reviewer covered all 111 files
with no findings and independently passed 84 regression cases. Exact-head PR CI
remains the final phase delivery gate. The refreshed current inventory remains
575 candidates in 106 files, including one test-infrastructure candidate, rather
than a repository-wide violation count or closure claim. Worker Session/Stop
ownership and the larger services/Runtime/API groups remain later work.

Phase 29 PR #2056 is submitted at `574020052` and its normalized exact-head CI
has no failed or unfinished checks (38 passed, three skipped on the latest
verification). No Agent merge. Phase 30 starts from that clean validated parent
with the completed Platform settings discovery rather than waiting for Worker
call-path mapping. This changes execution order only; Worker scope remains later
work and Design delta remains None.

Phase 30 owns System Settings (10), concrete GitHub settings (3), Workspace model
defaults (5), and removal of a dormant generic migration runner (1), with eight
service session declarations and three session callback aliases. Eighteen
contexts are reachable ownership violations; the runner is a removed obsolete
capability, not an infrastructure exemption. Retain executed migrations/marker
infrastructure, committed expiry deletion before service errors, same Section
version/generation/impact authority, current Workspace member/null/catalog policy,
and final settings+downgrade marker atomicity. Generic lifecycle and concrete
GitHub confirmation share one implementation owner; Workspace defaults is an
independent workstream. Neighboring catalog reads remain explicit residuals.
The same reviewer and full root validation/OpenAPI/CI gates apply.

Phase 30 PR #2057 is validated at `cd4df4362` against main `dfd441aef` after
requester merger of parent #2056. The only conflict was the Model Catalog change
history; both records remain, with this phase's entry at v37. All Python patches
remain identical. Latest backend validation passed 7,201 cases with three existing
Redis-only memory skips; ty/pre-commit/OpenAPI gates passed. Independent review
covered all 37 paths with no findings and 87 cases passed. Exact-head CI is 38
passed, three skipped, no failures/pending. No Agent merge. Current inventory is
556 candidates in 103 files, not a confirmed residual violation count.
The requester merged #2057 as `602b1720e`; its tree is exactly the validated parent
tree. Phase 31 fast-forwarded to that main commit without changing any dirty file.

Phase 31 starts the verified Worker Session/Stop slice: lifecycle 17, Stop 2,
canonical snapshot 1, live projector 2, recovery 1 and runner pending-command 1.
It removes two dormant scopes and the generic application Session callbacks while
preserving Worker-specific owner errors, lock order, command/Run/parent atomic
sets, and the separate partial/cancel/terminal/marker/clear Stop commits. One
remaining Executor in-session owner consumer and eleven borrowed Run repository
references receive explicit narrow repository wiring; its 17 larger contexts
remain later work. Three non-overlapping owners implement Session/core, Stop and
projection; root owns shared Worker fixtures and the same review/validation gates.
Design delta remains None and no broader issue closure is claimed.

Phase 31 implementation and root integrated validation are complete: 385 focused
cases and 7,311 full backend cases passed, with three existing Redis-specific
contract variants skipped. Root type/Ruff/format/pre-commit/OpenAPI gates passed;
public/admin contracts remain identical at 234/69 paths. All 24 scoped factories,
generic callbacks, dormant helpers, old raw-service exports and no-op ownership
test adapters are absent. Candidate inventory is 532/97, not a confirmed violation
count. The same retained reviewer covered all 34 paths with no findings and
independently passed 385 cases. Main-base PR #2058 is open at `e14bf1de8`;
exact-head required CI passed (38 passed, two path-condition skips, none
failed/pending), MERGEABLE/CLEAN. No Agent merge.

Phase 32 preparation owns the next 21 verified contexts: Executor 17 (11 reads
and six coherent model/profile groups), Metadata capture one and Wait observation
one, plus two Kimi runtime persistence scopes required by resolve factory closure.
One owner integrates the entire Executor/fixture surface; the read owner
supplies completed reads and closes Engine resolve factory callers; a dedicated
PG test owner proves model groups. Canonical selector/data relocation updates all
eight actual production callers without compatibility exports. Preserve fresh
normal-Failure commits, quota-exhaustion commits, compaction-inside-error rollback,
the existing three-attempt/final-operation fences and external resolution order.
The recorded parent gate is confirmed. Implementation and root QA passed:
624 focused cases and 7,419 full backend cases, with three existing Redis-specific
contract skips; type/Ruff48/format/pre-commit/OpenAPI234/69/removal checks passed.
Candidate inventory is 511/93, not a verified remaining-violation count. All
21 assigned lifetimes and factory/canonical interfaces are removed. The same
retained reviewer covered all 53 raw paths / 52 Git changes with no findings and
independently passed 624 cases. Stacked PR #2060 is open over #2058 at
`b71c391fb`; exact-head CI passed (34 passed, two path-condition skips, none
failed/pending), MERGEABLE/CLEAN. Design delta is None; no Agent merge.

Phase 33 owns 16 Runtime protocol contexts: Owner/route six,
Provider/Runner reports five and reconciliation five. Three non-overlapping
owners retain route epoch/SQL-clock lease/nonce, distinct report/handoff groups
and post-coordination dispatch authority; root owns shared control-server
constructors and wrappers. Preserve current lock-order asymmetry, committed nonce
expiry behavior, stale normal-return commits, optional Redis and no-replay policy.
Implementation and frozen owner handoffs are complete. Root integrated validation
passed 867 focused and 7,570 full backend cases with three existing Redis-only
memory contract skips. Whole type checking, Ruff/format for 19 Python paths,
OpenAPI 234/69 equality, docs/whitespace and removal/caller/import scans passed;
source hashes remained stable. Eight real distinct-connection PostgreSQL races
prove route contention, with separate actual write-fault/cancellation and
post-coordination revalidation evidence. All old test definitions remain.
Comparable candidates are 495/89 (services 478, API 9, Scheduler 7, conftest 1);
zero direct Runtime candidates is not complete alias/indirect-call coverage.
Runtime Control 92, Persistence 41 and Run Resume 38 record the completed internal
groups. No new cross-I/O lock or protocol/TTL/retry/fallback policy; Design delta
remains None. Initial/final pre-commit passed with source bytes unchanged. The same
retained reviewer covered all 24 paths with no findings and independently passed
867 cases with the same three existing skips; final frozen checks passed.
Only execution metadata changed afterward. Commit 24bc7d8b1 is submitted as
stacked PR #2065 over #2060; its actual-head workflow passed with 33 native
successes and two path-condition skips. Rollup 34 passed / two skipped includes
one inherited base status. Required E2E four shards, web shard and aggregate
passed; OPEN/MERGEABLE/CLEAN, no Agent merge.

Phase 34 owns nine bounded Scheduler/ingress contexts: seven Scheduler state
groups, guarded Testenv release one and explicitly included diagnostic read one.
The diagnostic is completed rather than silently excluded. Separate Scheduler
source and PostgreSQL owners share a published completed contract; the ingress
owner closes both reads and API/service/CLI callers. Root owns scheduler/deps.py,
plans/Specs and all integration/review/delivery gates. Preserve application clock,
whole-loop now, strict lease cutoff, task-key/lease-owner-only settlement, prior
ensure/claim commits, JobRuntime cancellation and error ordering, explicit ingress
read commit before 404/submit, and bounded sanitizer/metrics projection.
The exact Phase 33 parent gate is confirmed; implementation may start after the
tracked phase plan is reported. Design delta None. Public OAuth eight contexts
and concrete Runtime-facing service/shared-Session helpers remain later scope.

Phase 34 implementation and frozen owner handoffs are complete. Root passed
183 focused and 7,664 full backend cases, with three existing Redis-specific
memory contract skips only in the full suite. Whole type checking, Ruff/format
for 13 Python paths, OpenAPI 234/69 plus bounded three-path ingress equality,
docs/whitespace and removal/caller/import scans passed; source bytes stayed
stable. Eighteen actual distinct-connection claim/reclaim/settlement cases carry
PID/blocking witnesses; separate real SQL/LocalJobRuntime/API/CLI proofs establish
completion before external effects. Old definitions and narrow query bytes remain.
Candidate inventory is 486/86 (services 477, API 8, fixture 1), not complete
indirect coverage or remaining violation counts. Periodic Execution 24 and
Provider Ingress 64 record the unchanged internal contracts. Initial/final
pre-commit passed with source bytes unchanged. The same retained reviewer covered
all 18 paths with no findings and independently passed 183 cases without skips,
repeated the overlapping 18 contention cases, and verified bounded OpenAPI and
final frozen checks. Only execution metadata changed afterward. Commit d1c3a7d47
is submitted as PR #2067 over #2065. Actual-head workflow attempt 2 succeeded
with 33 native successes / two path skips; rollup 34 passed / two skipped includes
one inherited base status, OPEN/MERGEABLE/CLEAN. Attempt 1 Slack history timeout
and same-head local 1/3-case plus diagnostic rerun passes are preserved without
root-cause or source-fix claims. No new mechanism, cross-I/O lock or Agent merge.

Phase 35 owns the eight Public Toolkit OAuth/setup/test-credential lifetimes and
actual service/helper/Agent-caller closure. API/service, repository/authority/data,
and PostgreSQL proof owners have non-overlapping paths. Root owns shared wiring,
plans/Specs and all integration/review/delivery gates. Post-HTTP installation and
shared connection writes repeat existing exact active User/Auth Session, admitted
Workspace/current membership/TOOLKITS_WRITE predicates and shared Toolkit identity
inside the completed final group. This is bounded fresh evaluation, not a new
stable-through-commit lock/isolation guarantee. No new initiating-User/redirect,
config/version/connection/credential CAS, revoke/compensation or retry policy.
Current Shared/Agent and setup/refresh distinctions remain. The parent gate is
confirmed; implementation starts only after the tracked phase plan is reported.
Design delta None; public schemas, protocol, permissions and lock policy remain.

The requester's subsequent #2058 conflict report repairs the four open phases
onto main `83fc6e43a`. Phase 31 preserves both Spec records; Phase 32 retains the
current data-only catalog source and completes its metadata read without
restoring retired authority. Phase 33/34 patch identities remain unchanged.
Repaired local heads are `fba0ba1bd`, `5c8e849ae`, `0918ee793`, and `a52ef0254`.
Root repair QA passed 910 focused and 8,234 full backend cases with three existing
Redis-only skips, whole ty/Ruff/format/docs/whitespace and final pre-commit.
The same reviewer completed all 118 repair paths with no findings and 311
independent cases passed. One atomic explicit-lease push updated all four remote
heads after checking exact old official tips. Exact new-head CI remains pending;
previous CI records above are historical evidence, not proof for these new SHAs.

All Phase 35 implementation owners are frozen: 13 Python paths, with separate
repository regression, application sequencing, real SQL/savepoint/standalone
fault-cancel, and 45 actual-service independent committed-invalidation evidence.
Root verified the hashes before and after moving the dirty phase to `a52ef0254`
through an identified preserved stash. Fresh Public/Admin and candidate baselines
remain 234/69 and 486/86. Root integrated phase QA passed 328 focused and 8,409
full backend cases with three existing Redis-only skips, whole ty/Ruff/format,
full Public/Admin JSON equality, absence/retention/inventory/docs/whitespace and
pre-commit. All 13 source hashes are stable. Candidates are now 478/85, not
complete coverage. The same retained reviewer completed all 18 paths with no
findings, independently passed 328 cases and the overlapping 45 actual-service
M3 repeat, verified bounded OpenAPI and final frozen state. Only execution
metadata changes afterward. Stacked PR submission and exact-head CI remain
root-owned unfinished delivery gates.

The requester externally merged all four repaired parent PRs while Phase 35's
review was completing, and #2067's remote branch was deleted. The first Phase 35
PR creation over that branch failed without losing its pushed commit. Current
main `a500f7594` contains the reviewed a52ef0254 parent; only dependency/hook paths
changed afterward. A source-identical conflict-free rebase preserved the full
18-path Phase 35 patch. Fresh dependency-environment QA again passed 328 focused
and 8,409 full cases with the same three existing Redis-only skips and all nine
gates. Only execution metadata changes; source/Spec review remains valid.
The Phase 35 PR now targets main; parent and new exact-head CI are still checked
separately, not inferred from externally merged state. No Agent merge.

Phase 35 is delivered as main-base PR #2073 at `8c949fbff`. Latest actual
CI37079167588 attempt1 succeeded with native37success/two path-condition skips,
including four external CodeQL checks; actual CI jobs33success/two skips.
Required E2E4shards/web1/aggregate passed; OPEN/MERGEABLE/CLEAN. All four repaired
parent exact-head latest runs also succeeded; older cancelled duplicate-workflow
placeholder checks remain separate evidence, not current test failures.
No Agent merge or issue closure. Completed clean repair worktree was removed
without force/discard after restoring its allocation branch; exact owned Phase35
stash was dropped only after reviewed source, commit, remote and CI preservation.

Phase 36 starts the bounded Credential projection read slice: two application
contexts, six Session-taking provider declarations, four default query factories
and actual Auth/Security constructor closure. Completed ordered facts retain User
and address guards/redundant reads/duplicates, while SMTP/environment validity and
last-valid-credential projection stay session-free. There is no post-external-I/O
final mutation; no new disabled-user/auth/lock/isolation/TTL policy is authorized.
Actual password deletion authority and adjacent Auth/Security writes are unchanged.
The same reviewer, unchanged schema/test/caller/removal gates and genuine closure
proof apply. Implementation begins only after the tracked Phase36 plan is reported.
Design delta None; the overall478/85 lexical checkpoint is not complete coverage.

Phase 36 implementation and the same retained all-14-path review are complete
with No findings. Original root QA passed 252 focused and 8,550 full cases;
source-identical rebase onto main `48aaa5464` after external #2073/#2072 merges
preserved the entire phase diff and all reviewed hashes. The seven unrelated
Model Catalog/web-search changes have no phase overlap or dependency change.
Fresh root QA passed 252 focused and 8,563 full cases with the same three
Redis-only skips and all nine gates. Completed reads preserve exact query/order/
duplicate/absence/SMTP/projection contracts and separate deletion authority.
Delivered as main-base PR #2074 at `abd26825ca`, OPEN/MERGEABLE/CLEAN. Actual
CI37089093549 attempt1 SUCCESS/native37success/two path skips; required E2E4shards,
web1, aggregate, Python, Docker, migrations, pre-commit and CodeQL pass. No Agent
merge, implementation marking, live action or #1718 closure.

Phase 37 starts the complete SignupToken five-group Registration slice. Required
prepared inputs retain pre-DB strength/hash/RNG/captured-clock order; one completed
redemption keeps token eligibility/email/conditional claim/User+verified email/
PasswordLogin/AuthSession/audit atomic before JWT. SMTP/helper/public contracts,
including existing failure retention and status policies, remain. Canonical pure
failure relocation updates actual defining callers with no aliases. The same
reviewer and root integrated/removal/schema/real-SQL/CI gates apply. PasswordReset
rollback/restart concern remains source-only deferred investigation, not a chosen
new policy or reproduction. Broader WorkspaceInvitation and other residual
coverage remain; Design delta None. Implementation starts only after the full
tracked Phase37 plan and required interfaces are reported.

## Delivery Boundaries

1. Correct the title-generation and ChatGPT OAuth persistence boundary as one
   independent implementation PR. Provider refresh and model/title projection
   execute after completed repository operations.
2. Correct the confirmed Project and Mailbox external-I/O overlaps and extract
   their bounded database-only repository operations. Their shared Toolkit State
   dependency follows in a dependent implementation PR.
3. Complete remaining transaction ownership and confirmed external-I/O violations
   by domain, using the exhaustive inventory to determine bounded PR interfaces.
   Open each delivery PR before monitoring CI or starting a dependent phase.
   Do not close the overall issue while any confirmed violation or coverage gap
   remains.
4. Re-run entrypoint and indirect-call inventory, report unavoidable locking
   exceptions, verify affected E2E/required CI, promote current Specs, and remove
   this effort's temporary plans after verified completion.

Later phases' exact file partition remains an execution decomposition, not authority
to change behavior. Record it before those edits. The six research areas are
External Channel; Runtime/Projects; Session/Agent lifecycle; models/integrations/
files; account/workspace/configuration; and non-service entrypoints.

## Shared Contracts and Constraints

M1–M3 require complete typed repository calls, external work outside transactions,
and preservation of existing atomicity/authority. M4 owns inventory, evidence,
tests, and delivery. M5 owns lock avoidance and the exception ledger.

Repository code never calls service orchestration or arbitrary external
callbacks. Shared DTO/helper relocation requires caller inventory and explicit
ownership assignment. No generated API, schema, dependency, migration, provider,
retry, or configuration changes are planned.

Read-only research can overlap implementation; reports identify the baseline SHA
and distinguish changed-line evidence from baseline findings. Implementation
owners do not edit one another's source files or shared documents.

## Verification and Cleanup

Each phase includes scoped tests, Ruff/format, configured type checks,
pre-commit, one independent review, and required CI. Existing E2E flows remain
product-contract evidence. Testenv prerequisites are used only where needed;
secrets are never recorded. Record exact missing prerequisites rather than
claiming skipped tests pass.

At completion, report residual entrypoints, exclusions, stale-authority/rollback
evidence, and each unavoidable cross-I/O lock (or a verified none). Standalone
memory coordination and distributed Redis-loss safety are distinct checks.
Do not merge PRs or modify live infrastructure. Remove completed clean managed
worktrees and their Project registrations when no further edits are needed.
