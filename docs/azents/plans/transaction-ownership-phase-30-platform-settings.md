---
title: "Transaction Ownership Phase 30: Platform and Workspace Settings"
created: 2026-10-02
tags: [backend, security, architecture, database]
---

# Phase Execution Plan

- Phase: `30, complete System Settings, GitHub App settings and Workspace model defaults`.
- Branch/base: `refactor/transaction-ownership-261002-18-platform-settings` ->
  `refactor/transaction-ownership-261002-17-account-auth`, parent `574020052`.
  PR #2056 is open, MERGEABLE/CLEAN, with 38 passed checks and three skipped checks
  on the latest verification. No failed or unfinished check and no Agent merge.
- PR boundary: 19 assigned application factory contexts: 10 System Settings,
  3 GitHub settings, 5 Workspace defaults, and 1 dormant migration runner.
  Eighteen are reachable ownership violations; the unused runner is removed.
- Inputs: approved transaction ownership revision 1; current System Settings and
  Model Catalog Specs; existing Section locks, typed registry, cipher/environment/
  HMAC primitives, GitHub impact queries, Workspace query and downgrade marker.
  The Settings discovery's historical `phase31` filename identifies its candidate
  preparation, not a fixed delivery order. It is delivered first while Worker
  Session/Stop discovery is completed; Worker scope remains subsequent work.
- Deliverables: completed domain repository operations, session-free services,
  concrete GitHub DB composition instead of application session callbacks,
  canonical pure shared inputs/results/dependency factories, unused interface
  removal, behavior-preserving atomicity and external-effect boundary tests.
- Non-goals: Worker/Runtime/Chat, full model/image catalog or provider sync,
  Credential, unrelated setting families, executed migrations, relational schema,
  public API/client fields, permissions, new locks/CAS/retries or delivery policy.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current System Settings and Model Catalog Specs.
- Design delta: `None`.

## Ownership and Interfaces

| Workstream | Owner | Owned paths | Dependencies/output | Validation |
| --- | --- | --- | --- | --- |
| System lifecycle and concrete GitHub composition | `/root/tx-platform-inventory` | services/system_setting and github_platform_system_setting; new/updated repos/system_setting and github_platform_system_setting; pure core setting contracts/helpers/factories; Admin system_setting data/route defining imports; external_account_link and external_account_oauth pure factory imports; all callers of relocated symbols and test constructors | One owner keeps generic lifecycle and concrete GitHub confirmation atomic. Completed Section operations and GitHub impact/audit operations; pure shared DTO/factory contracts; no session-taking service callbacks | Version/generation/expiry/impact/action checks; current/candidate/audit/health rollback; expiry committed deletion; redaction; HTTP/cancellation boundary; same Section lock |
| Workspace model default ownership | `/root/tx-chat-inventory` | services/workspace_model_settings; new repos/workspace_model_settings completed operations/tests; existing narrow repository only if needed for canonical imports; Workspace public route imports only if relocated shared symbols demand it | Complete current/get-or-create/final-update calls; typed catalog/image normalization stays outside Workspace transactions. Adjacent catalog lifetime migration is explicitly deferred | Empty row creation, null/omit/label/default-clear behavior, canonical snapshot fields; downgrade marker atomicity and failure rollback; existing membership policy |
| Integration and delivery | `/root` | phase/master plans, System Settings/Model Catalog Specs, integration corrections, root quality/review/PR/CI | Full validation, exact OpenAPI equality, same retained reviewer, bounded stacked PR, residual inventory | Real PostgreSQL focused/full backend, ty, Ruff/format, pre-commit, all defining callers/removed symbols and applicable required E2E |

No product-path overlap between implementation owners. Notify root before touching
any peer path. Implementation owners do not commit, stage, change branches or
open PRs. Root integrates the stable diff and requests the retained reviewer.
Shared identifiers are local implementation choices, not new Design mechanisms.

## Exact Preserved Boundaries

- Generic lifecycle keeps the existing signed SHA256-derived Section advisory lock
  namespace, expected/current/base version, candidate identity/status/expiry,
  effective-generation, health-generation, impact and allowed-action authority.
  No new Redis lock, retry, isolation or permission predicate is introduced.
- Mutate retains current/candidate/audit atomicity, including direct activation
  and candidate replacement. Validation record plus audit plus conditional
  autoactivation/current write/candidate deletion stay in one transaction.
- Expired prepare/confirm/cancel/validation-record operations commit ciphertext
  deletion before the service raises the existing expiry error. Return a typed
  committed-expiry outcome; do not raise inside the commit-on-exit scope.
  Conversely, mutate/get-state expiry cleanup must roll back if a later local
  validation/cipher failure previously rolled back that same atomic group.
- Replace GitHub's live-session impact/confirmation closures and binding service
  session methods with concrete database-only repository composition. Recompute
  impact, allowed action and exact Section authority inside the same locked final
  transaction. Preserve aggregate JSON, including confirmation action lists.
  Do not turn a generic callback or mixed-I/O service into a repository alias.
- External GitHub/Slack/Discord validation and health HTTP remains between completed
  database operations. No raw provider response, plaintext/ciphertext, private
  generation/fingerprint or resource-ID impact set enters public output/audit/logs.
- Pure payload migration/validation, cipher decoding, environment overlay and HMAC
  projection retain one canonical implementation usable by repository composition.
  Pure environment/hasher DI factories move out of service definitions, replacing
  the two reverse repository imports. Keep the existing behavior of all consumers.
- Workspace read-before-normalization and final write remain separate completed
  operations. Catalog/image callbacks accept detached typed data and run outside
  the Workspace transaction. Their own neighboring service contexts stay named
  residuals; this phase does not claim their completion.
- Workspace default options cannot be cleared once configured. Preserve empty-row
  get/create, omission and label-null fallback, option order/labels/subagent flags,
  capabilities/execution options, provider/source/catalog identity and fallback
  lightweight selection. Keep the existing distinct conversation/image predicates.
  Final columns and `mark_model_candidate_chain_write` commit or roll back together.
  No Workspace revision/CAS, stronger enabled predicate or auto-reselection is added.
- Admin routes retain global live system-admin authorization. Workspace model GET/
  PUT retain current WorkspaceMember authorization without a new OWNER/MANAGER
  or write-permission restriction.

## Removal and Absence Evidence

Root reconfirmed only a defining service and its one unit-test constructor use
`SystemDataMigrationRunner` / `SystemDataMigrationOperation`; no production/CLI
caller or `.resolve_in_session(...)` call was found in backend/testenv source.
Remove the unused runner, its general session callback alias and its sole
callback-once service test under REQ-1/M4. Retain executed migration scripts,
`system_data_migrations` storage, migration query primitives and inbound policy
migration tests. This removes an obsolete capability, not supported product data
migration behavior or a new infrastructure exception.

Remove dormant service `resolve_in_session`, all eight assigned service session
functions, and the three AsyncSession callback aliases; keep only necessary
narrow in-session repository primitives for concrete atomic composition. Remove
old shared definitions/imports when moved; update every canonical caller without
re-exports or compatibility aliases. Remove application manager/query injection
from migrated services. Search actual session lifetimes, returned handles,
callbacks, implicit restart, reverse imports and defining symbols, not just SQL
imports. Shared typed validator callbacks with no Session remain external service
orchestration. No executed migration or public contract is rewritten.

## Validation and Delivery

1. Capture public/admin generated OpenAPI before implementation; require exact
   JSON equality after integration. No client regeneration on an unchanged schema.
2. Real PostgreSQL regression for Section locking/competing mutations, partial
   failures/rollback, every committed-expiry branch, stale candidate/version/
   generation/impact rejection and validation+activation audit atomicity.
3. External HTTP collaborator checks zero active SQL context; failed/cancelled
   validation remains outside DB and never becomes an implicitly retried callback.
   Test secret/null/omit/present-empty ownership, redacted audit/API views and exact
   confirmation action list representation. No live provider credentials required.
4. Workspace completed operation/service tests for normalization closure, current
   empty-row behavior, rejection/null/label/omission, all stored snapshot fields,
   update+downgrade marker rollback and unchanged membership behavior. Retain
   existing catalog selection tests; do not add new selection policy.
5. Root focused suite plus full backend pytest, ty --error-on-warning, changed-path
   Ruff/format, full pre-commit, removal/caller scans. Preserve command logs/exits
   and exact skip/prerequisite reasons, not unverified success claims.
6. Independent read-only review by the single retained reviewer
   `/root/phase25-independent-review` after stable integration and root validation;
   root fixes findings and revalidates affected behavior. Required Admin System
   Settings and public model-selection E2E/CI on the shipping SHA.
7. Open a stacked PR over #2056 if still open; reconcile with fresh main if the
   requester merges it. Never merge without explicit authorization. Own corrections
   and exact-head normalized CI checks through completion.
8. Refresh the full candidate inventory and named residuals. Initial comparable
   inventory is 575 contexts / 106 files, not 575 confirmed violations. Worker,
   catalog normalization providers, Memory, Chat and other domains remain visible.
   Keep overall Channel Work active; no issue-wide closure from this batch.

## Context Checkpoint

- Prior Phase 29 delivery passed local full backend 7111 cases (three existing
  Redis-specific memory skips), ty/pre-commit/OpenAPI/removal checks; 111-file
  independent review had no findings and 84 independent cases passed. PR #2056's
  exact-head checks are passed/skipped with no pending/failure. No Agent merge.
- This phase starts from the clean parent 574020052. The earlier discovery's
  0d3de4115 differs only in two plan records, not assigned Python source.
- Scope drift: no product, public schema, provider, secret-storage, lock, retry,
  permission, option-normalization or default policy change. Design delta: None.
- Both implementation workstreams are stable. Eighteen reachable lifetimes now
  finish in domain repository operations; the unused runner is removed. Eight
  service session declarations and three session callback aliases are absent.
  Pure DTO/payload/factory definitions have one canonical core source, without
  repository-to-service imports or compatibility re-exports.
- Root integrated focused suite: `141 passed`. Full backend: `7167 passed,
  3 skipped`; skips remain the existing Redis-specific memory variants. Root
  full ty, changed-path Ruff/format, full pre-commit and removal/caller checks
  passed with saved log/exit evidence. Public/admin OpenAPI exactly equals the
  baseline at `234` / `69` paths.
- Comparable fresh candidate inventory is `556` contexts in `103` files, down
  by the assigned `19` from `575` / `106`. Counts are discovery candidates, not
  confirmed residual violations or issue-wide closure evidence.
- Retained independent reviewer `/root/phase25-independent-review` reviewed all
  `37` raw paths (`33` Git entries with four renames): nine import-only equivalent
  paths and 28 directly inspected implementation/DTO/test/document/removal paths.
  No findings. Independent PostgreSQL and regression subset: `87 passed`, no
  skips. Thirty relocated DTOs and both factories preserve their definitions.
  No source correction was required after review.
- The requester merged parent PR #2056 while Phase 30 CI ran. GitHub retargeted
  #2057 to main; the newer OAuth fencing Spec record caused a changelog conflict.
  The mandatory rebase onto `dfd441aef` preserves both records and advances this
  phase's Model Catalog ownership entry to v37. Range-diff confirms all Python
  patches are unchanged; only the Spec version/history bookkeeping differs.
  The reviewed source and prior 7167-case evidence are retained; latest-base
  full validation and exact-head CI are rerun before final delivery claims.
- Exact-head PR CI remains pending; overall issue #1718 is not close-ready.
