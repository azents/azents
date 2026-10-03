---
title: "Agentic Historical Memory Phase 2: Scoped Storage and Writable VFS"
created: 2026-10-02
tags: [memory, storage, backend, implementation, security]
---

# Phase Execution Plan

- Phase: 2, current-source identity, durable work/draft storage, independent execution authority and optional writable VFS.
- Branch/base: `feat/memory-261002-2-storage-vfs` → `feat/memory-261002-1-shared-loop` at `972377431` (PR #2069).
- Inputs: approved [Requirements](../requirements/memory-261002-consolidated-history.md), [ADR](../adr/memory-261002-consolidated-history.md), [Design revision 2](../design/memory-261002-consolidated-history.md); completed phase1 common iteration/stream/batch interfaces.
- Approved mechanisms: M2, M3, M4, M5, M9, M15; prepare M6/M8 persistence interfaces without activating consolidation.
- Design delta: **None**.
- Implementation/integration/validation owner: `/root`, directly.
- Single read-only reviewer: `/root/memory-implementation-reviewer`.
- PR boundary: additive generated migration, scoped domain/persistence primitives, separate optional VFS mutation/batch protocols and Runtime-independent file dispatch with deterministic storage/authorization tests.
- Non-goals: model-driven background consolidation activation, new automatic aggregate snapshot selection, public aggregate UI, live schema changes, speculative writers or new model settings.

## Interfaces

- A job authority names one exact Agent/Workspace/scope/User, attempt and owner generation; no fake foreground Session/Run or Team+User combined inventory.
- Current evidence content version is generation/hash, separate from availability/grant continuity; metadata enrollment is idempotent and body-free.
- Source purge cannot cascade away the only aggregate/draft dependency evidence. Missing authority fails closed.
- Unit/draft/file/receipt/work records preserve approved lease, revisions, bounds, exact work acknowledgements and transaction ownership.
- Read-only VFS backends remain complete without mutation stubs. Mutation and atomic patch are separately optional; Runtime adapters retain current behavior.
- Draft reads establish execution-local observations, admission freezes preconditions, and mutations commit files/dependencies/receipts atomically. Replays reauthorize and do not pretend an old committed revision is current.
- Lifecycle producers advance availability identity; source enrollment does not take unit ownership locks inside the existing source-publication transaction. Each membership row also carries a fresh server-owned Memory grant identity, independent of its row ID, so delete/recreate cannot rehabilitate old dependencies even if an internal caller reused a row ID.

| Workstream | Owner | Paths | Depends on | Output / validation |
|---|---|---|---|---|
| Scoped domain and evidence identity | `/root` | `core/historical_memory_consolidation.py`, `core/historical_memory.py`, tests | Approved scope rules | Invalid Team/User keys rejected; canonical exact evidence hash/version |
| Additive schema | `/root` | `rdb/models/historical_memory*.py`, `rdb/models/workspace_user.py`, generated `db-schemas/rdb/migrations/versions/*`, revision file | Domain | Linear generated migration; explicit ENUM/constraint/index definitions; upgrade/downgrade/metadata tests |
| Repository operations and lifecycle | `/root` | `repos/historical_memory/**`, new consolidation repos, `repos/{agent,agent_session,workspace_user}/**` | Schema | Exact-scope pages; version/enrollment atomicity; lease/receipt/patch/revoke races |
| VFS and tools | `/root` | `services/vfs_{read,mutation,text}.py`, `services/historical_memory/{draft_vfs,source_vfs}*.py`, `engine/tools/{readable_storage,mutable_storage,builtin,write,edit,delete_file,apply_patch}*.py` | Repositories | Separate protocols; VFS dispatch before Runtime; no cross-domain writes or metadata disclosure |
| Shared strict patch primitives | `/root` | `python/libs/azents-runtime-control/src/azents_runtime_control/`, existing Runner `apply_patch.py` and its tests | Existing strict Runtime algorithm, M4/M5 | Extract context-free parsing/text applicability without changing native Runtime staging/partial-commit behavior; use it for all-or-none database patch batches |

## Integration and Validation

1. Domain contracts and direct unit tests.
2. Generate migration through Alembic, edit/review it, and update revision marker.
3. Repository-owned transactions, exact scope, source/lifecycle producers and concurrency tests.
4. Optional VFS interfaces/backend plus shared tool dispatch and Runtime regressions.
5. Root-owned focused/full backend Ruff/format/ty/pytest, migration checks and documentation validation.
6. Freeze integrated complete diff, request review, resolve findings, rerun invalidated evidence, commit/open dependent phase2 PR before phase3.

## Removal and Scope Checks

Replace Runtime-exclusive mutation registration only when its routed adapter is integrated; retain original Runtime policy and errors. Do not weaken or mutate immutable Skills/public read-only Memory. Preserve source bodies/Saved records and current foreground context selection until phase4 activates its replacement. Every new mechanism must trace to the approved IDs; new public behavior/mode/fallback returns to Design rather than being hidden in this plan.

## Checkpoint

Phase1 PR #2069 is open at `97237743123607d873fc0dab2be434347670ec09`; its final backend evidence is 7,231 passed/3 skipped and review-clear. Phase2 implementation, final integrated validation and the single independent review are complete. All three findings were corrected and targeted re-review is clear. This checkpoint authorizes the root-owned commit and dependent phase2 PR, not phase3 or production activation.

### Storage integration checkpoint

- Exact private principal/key/version contracts, current source generations/hash and a fresh per-membership Memory grant identity are implemented.
- Generated linear revision `3be144f78dca` adds units, attempts, exact source-work enrollment, current drafts/files, exposure/dependency manifests, mutation receipts and immutable publication storage. Body-free work enrollment does not lock consolidation units.
- The migration versions current prepared outcomes, including empty outcomes, then enrolls currently authorized sources in fifty-row pages. It preserves source bodies and Saved/history data.
- Repository-owned claim/renew/fail operations use database time, 120-second leases, ten-minute deadlines and owner-generation/token fencing. Duplicate claim preserves work; takeover cancels the expired attempt.
- Exact source reads/inventory record exposure receipts before returning. Draft/file reads bind private revisions and the source-exposure epoch. An atomic batch joins file changes, conservative influence and bounded replay receipts; stale revisions/epochs, payload overflow or digest conflicts leave the draft unchanged.
- Draft dependency identity remains independent of source-row deletion. Every read/mutation/replay rechecks source scope, current authority and availability/grant continuity. Nonwaiting authority/source locks prevent inversion with existing lifecycle writers from becoming unbounded waits.
- Both root-tree and direct archive advance availability in the lifecycle transaction; restore enrolls the new identity without resetting it. Membership removal/restoration enroll exact old/new-grant deltas. Memory disable/enable also records source denial continuity, so re-enabling cannot rehabilitate pre-denial prose.
- Completed focused integrated evidence: **110 passed** across scoped contracts/storage, Historical source repository, Agent, Session and membership repositories; scoped repository type checking passed.
- Disposable PostgreSQL 17 rehearsal passed upgrade, metadata comparison, downgrade to `459a4285993c`, re-upgrade and metadata comparison. A separate seeded migration test passed with 62 sources spanning multiple pages: 60 eligible work rows, preserved empty/prepared/archived/unprepared distinctions, canonical hash parity and non-destructive reversal.
- Test fixture corrections: seeded Agent options must satisfy the existing nonempty-chain DB constraint; committed concurrency fixtures must delete Agent before Workspace. These fixture corrections did not change product contracts.
- Remaining phase2 work: complete optional VFS mutation/patch interfaces, private draft adapter and shared tool routing/admission; source inventory/bounded-result tests and further lock/replay races; final integrated validation and the single read-only review. No consolidation host, foreground cutover or live migration is activated.
- Phase3 will integrate validated publication, durable dispositions/progress, invalidated-draft recovery and meaningful-progress accounting. Changed file revisions alone are not evidence of completed source coverage.

### Ordinary VFS tool checkpoint

- Read protocols, registry and router are context-parameterized with the existing foreground context as default. Independent jobs use their own concrete principal, preserving foreground fields and avoiding invented Session/Run IDs.
- Separate optional native mutation and atomic-patch protocols and explicit capability registration are implemented. Registration rejects false capability/interface claims; read-only summary backends remain complete without mutation members, and the ordinary draft writer currently has no patch stub.
- The private `memory-draft` mount uses execution-local read observations and frozen mutation tickets. New creation confirms absence; overwrite/edit/delete require prior existing-file reads. Source exposure or sibling writes invalidate old tickets rather than updating them silently.
- Safe receipt replay reauthorizes before evaluating text applicability, so an acknowledged-loss retry can replay an edit/delete after the original changed or removed its input. Replay does not change the read ledger or claim that its committed revision is still current.
- The closed `memory` summary mount exposes only the principal's exact corpus and a paged metadata inventory. All reads record influencing versions; ordinary foreground Memory/Skills bindings remain read-only. Drafts and source summaries have no transfer interface.
- Generic ordinary file registration now owns write/edit/delete exactly once; Runtime supplies lazy guarded native adapters and retains process/transfer tools. Unsupported/unknown/noncanonical VFS locations cannot resolve/start Runtime.
- Text reads reserve framing within the 12,000-byte tool-result limit and provide character continuation. Regex search uses the existing killable native worker after repository transactions finish; bounded result and incomplete source/page scans are explicitly marked.
- Latest integrated focused matrix: **237 passed**, with three existing dependency deprecation warnings. Whole-backend type checking and focused Ruff/format passed. Evidence: Session artifacts `memory-phase2-storage-vfs-integrated.log` and `memory-phase2-vfs-full-ty.log`.
- Fixed the canonical parser's leading-slash/private-key boundary, retained qualified call-name compatibility while using the actual server tool-call ID, and updated Runtime-owner tests to verify native edit behavior and duplicate-free generic registration.
- Remaining immediate action: extract/reuse the existing strict patch parser/text algorithm, add atomic private patch transactions/admission tests, route both JSON and plaintext patch dialects before Runtime, and move patch registration to the same generic owner. Current native Runtime patch registration has not yet been replaced. Then finish boundary tests, full integrated checks and the single reviewer gate before the phase2 PR.

### Atomic patch checkpoint

- Shared `azents_runtime_control.v4a` now defines the strict grammar, immutable plans, source decoding/newline semantics and exact text applicability. Runner delegates these primitives while retaining filesystem observation, staging, revalidation, cancellation/deadlines and partial-commit reporting. No Runner app import or second parser is used by the database adapter.
- Private patch admission validates every canonical target in the same bound draft domain and freezes execution-local read identities. All existing targets require reads; add targets confirm absence. Applicability, draft/file/epoch conflicts and UTF-8/NUL validation change no file. One repository-owned transaction joins every changed file, influence union and receipt.
- Both JSON-function and plaintext-custom variants route VFS before Runtime, retain the V4A model-profile requirement, and explain the different backend commit semantics. A model without V4A keeps the required ordinary tools rather than losing its candidacy.
- Patch registration moved alongside write/edit/delete into the generic owner. Native Runtime adapters retain capability checks, diagnostics/exclusions and exact operation behavior; no generic mutation name is also registered by Runtime.
- Added real PostgreSQL patch tests for multi-file create/update/delete, lost result replay in both dialects, later-target applicability failure with no earlier-file/revision change, mixed absolute/traversal/cross-mount targets, queued-ticket delete/recreate ABA, prior-read requirements and real compatibility projection without V4A.
- Latest focused backend matrix: **250 passed**, three existing dependency deprecation warnings. Whole backend type checking passed. Control library: **236 passed**; Runner: **295 passed** (including all 53 pre-existing native patch tests), with full project type checks and focused formatting/lint passing.
- Fixed a test prerequisite rather than product behavior: compatibility projection needs an explicit supported adapter profile; `None` correctly projects no transport variants. The no-V4A test now supplies the real OpenAI Responses adapter while leaving model profiles empty.
- Remaining phase2 gates at this checkpoint: finalize inventory/scan and interface boundary coverage, clean shared synthetic fixtures, run the complete backend/migration/regression validation matrix, freeze the diff for the assigned reviewer, apply corrections and create the dependent PR. No consolidation execution or foreground cutover is active.

### Final integrated validation checkpoint

- Completed bounded source inventory/regex scan, personal-scope sentinel isolation, optional mutation interface, lock-contention normalization and shared synthetic fixture boundary tests. Closing repository/VFS tests: **30 passed**; optional interface check: **1 passed**.
- Backend final command (from `python/apps/azents`): `uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -q`. Result: **7,283 passed, 3 skipped**, all lint/format/type checks passed. Local environment: Python 3.14, disposable PostgreSQL/Redis test containers; no live service credentials or production actions.
- Separate migration command: `uv run pytest -q migration_tests`; **13 passed**, including seeded backfill, upgrade/downgrade/re-upgrade and schema metadata parity. Current linear head: `3be144f78dca`, parent `459a4285993c`.
- Full control library: **236 passed**; full Runner: **295 passed**. Shared strict parser/text applicability retains existing native partial-commit and filesystem staging behavior. Their project type checks and focused lint/format passed.
- Initial full backend run exposed two stale expected migration-head assertions. Both now expect the generated head; focused assertions and the final full backend run passed. A package marker removes the new repository test module's collection-name collision. Neither correction changes product behavior.
- `python scripts/docs_catalog.py validate` and `git diff --check` passed. Durable Session evidence: `memory-phase2-detached-backend.log` / `.exit` (exit 0), `memory-phase2-final-migrations.log` / `.exit` (exit 0), `memory-phase2-control-full-tests.log`, `memory-phase2-runner-full-tests.log`, `memory-phase2-closing-focused.log`.
- Scope/removal check: no Design delta; scoped storage/private VFS prepare M2–M5/M9/M15 and M6/M8 persistence interfaces only. Runtime-exclusive mutation registration is replaced by one generic owner, preserving native guarded adapters. No background consolidation host, publication activation or foreground context cutover is implemented in this phase. Saved/source/history bodies remain preserved.
- Single independent review completed over all 43 frozen paths. It requires three corrections within approved M4/M5/M9/M15: invalidate mixed-version draft continuations until an explicit offset-zero restart (including delayed completions); narrow exact/literal-prefix source queries before page budgets; replace complete-manifest N+1 validation with indexed set checks, deduplicated locks and a deadline bounded by the current lease/attempt. Add deterministic edge/scale/deadline tests without dropping dependencies.
- Root owns these corrections and affected full integrated reruns. The same reviewer must perform targeted re-review after the corrected diff is frozen. Commit and dependent PR follow resolution; phase3 must not start before that PR exists. Design delta remains None.

### Independent review correction checkpoint

- R1: execution-local read generations fence delayed completions. A mixed identity invalidates usable observations for every mutation dialect until an explicit offset-zero restart. Same-version Unicode continuation, frozen queued tickets and authorized receipt replay remain covered; delayed initial reads and delayed continuation chunks cannot rehabilitate mixed evidence.
- R2: exact source IDs use the indexed equality predicate and useful literal ID prefixes narrow the scoped inventory before its page budget. Tests select a target after 55 additional sources with a one-file search budget, exact/native-prefix globs, scoped denial and explicitly truncated broad scans. Exact searches receipt only the selected source identity, not the first unrelated page.
- R3: complete inherited and exposed manifests stay database-side. Three indexed set-oriented checks lock distinct roots and current evidence once in sorted root-then-source order and validate every generation/availability/grant/hash dependency. One server-side insertion copies the full influence union without an uncapped Python/N+1 loop. Missing/purged sources remain denial.
- Protected job transactions bound admission by the approved 120-second lease and subsequently use the current lease/attempt deadline. PostgreSQL transaction-local statement timeout and an enclosing async operation timeout enforce cancellation through commit/rollback. Expected deadline and NOWAIT failures normalize only after rollback; unrelated failures and external cancellation propagate. Validation, reads, inventory, mutations, replay and renewal use this boundary.
- Real PostgreSQL tests cover 16 and 1,024 evidence versions plus inherited duplicates, a constant three manifest checks and one complete copy, source lock contention followed by successful renewal, and separately forced server/operation deadline rollback of files/receipts with owner-fence release. Test-only glob parser and committed-fixture cleanup ordering were corrected without product fallbacks.
- Review-fix integrated checks: **40 passed**, focused Ruff/format and whole-backend Ty passed. Final unchanged corrected backend: **7,293 passed / 3 skipped**; separate migrations **13 passed**; complete Ruff/format/Ty, docs catalog and whitespace validation passed. Evidence: `memory-phase2-review-fixes-integrated.log`, `memory-phase2-reviewed-backend.log` / `.exit` (exit 0). Prior control **236** and Runner **295** evidence remains valid because those files/interfaces are unchanged by these corrections.
- Targeted re-review by `/root/memory-implementation-reviewer` is complete and clear: R1–R3 resolved, no remaining findings. Reviewed full manifest SHA-256: `677f25239e5e08735212f65235490f9e3983afdfaa2ede42459581dd9a910988` (44 paths; exactly ten correction paths). No implementation file changed after that re-review; this plan records its result only.
- Delivery checkpoint: branch `feat/memory-261002-2-storage-vfs`, exact parent `97237743123607d873fc0dab2be434347670ec09`, PR base `feat/memory-261002-1-shared-loop` / #2069. Root owns commit and PR submission. Remaining feature scope is phases3–5, including the internal host/publication/progress, foreground context/cutover, E2E/capacity/operational QA and final Spec promotion/plan cleanup. No Design delta, phase3 implementation, merge, live migration or production action.
