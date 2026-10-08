---
title: "Transaction Ownership Phase 35: Toolkit OAuth API"
created: 2026-10-02
tags: [backend, toolkit, oauth, security, database, architecture]
---

# Phase Execution Plan

- Phase: `35, close Public Toolkit OAuth/setup/test-connection persistence`.
- Branch/base: `refactor/transaction-ownership-261002-23-toolkit-oauth` ->
  `main` at `a500f759427da66c1795e1c160d63783bf6dd0ec`.
  Parent PR #2067 was merged and its remote branch deleted during review.
  Previously repaired parent was `a52ef0254df0ec1ba793f3ce11478e26c2beb07d`;
  original admitted parent was `d1c3a7d4754ddf412813fab63cd703751c536211`.
- Start gate: Phase 34 root 183 focused / 7,664 full cases and retained all-18-path
  review with no findings / independent 183 plus overlapping 18 contention repeat
  passed. Public/admin/bounded router/type/format/pre-commit/removal gates passed.
  Parent actual-head workflow attempt 2 succeeded with 33 native successes and two
  path-condition skips; rollup 34 passed / two skipped includes one inherited base
  status. Parent OPEN/MERGEABLE/CLEAN. Attempt 1 Slack history timeout, same-head
  local 1/3-case passes and diagnostic rerun are recorded without a source-fix or
  proved root-cause claim. No Agent merge.
- PR boundary: eight existing application factory contexts in
  api/public/toolkit/v1/oauth.py: installation sync one; shared OAuth paired reads
  two and setup/token full writes two; shared read+disconnect one; saved and
  optional unsaved test-credential reads two. Scope includes actual service/helper/
  DTO/Agent consumer/fixture closure, not broader OAuth or Toolkit runtime rewrites.
- Inputs: current shared Toolkit, MCP connection, installation, User/Session,
  Workspace and membership queries; completed Agent operations; canonical cipher,
  OAuth discovery/token/state and Platform App runtime definitions; existing Specs.
- Deliverables: completed domain operations, session-free Routes -> Services ->
  Repositories, required defining caller/constructor closure and canonical domain
  payloads, exact original atomic groups, fresh final existing-authority checks,
  real PostgreSQL/write-fault/cancel/external-boundary evidence and unchanged APIs.
- Non-goals: schema/API/provider/PKCE/state/permission policy changes, new stable
  authorization-through-commit serialization, row/distributed locks, conflict/retry,
  version/config/credential CAS, refresh policy, compensation/revocation, shared
  initiating-User/redirect binding, connection/disconnect-wins/replay/fallback.
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current MCP OAuth, Toolkit, User Auth, Workspace and Platform App
  contracts. Design delta: `None`.

## Explicit M3 Execution Disposition

This phase implements the already-required revalidation of authority needed by a
final mutation after external work. It does not define a new permission, callback
binding, locking, versioning or delivery contract.

For the three post-HTTP persistence call sites (installation sync O1 and shared
connect/exchange O3/O5), repeat the existing admitted requester's exact User and
Auth Session eligibility, exact admitted Workspace ID and current membership,
and the same current role projection's TOOLKITS_WRITE condition in the final
repository-owned transaction. Shared connection writes also repeat exact Toolkit
ID, shared owner_agent_id=None and exact Workspace eligibility before full upsert.
The captured WorkspaceMember already carries user_id, session_id and workspace_id;
pass these trusted scalar facts, never a JWT, live Session or captured role as final
permission authority.

- Active subject repeats existing User missing/disabled and exact Session missing/
  foreign/revoked/expired checks. Account disablement can retain membership, so a
  membership-only check is insufficient. Reuse the canonical DB-only evaluation
  through a narrow helper; do not nest completed AccountAccess operations.
- JWT signature/expiry decoding remains at request ingress. Do not reparse/store a
  JWT or add a new JWT/time/CSRF policy inside persistence.
- Resolve final Workspace by the already-admitted immutable ID, not its possibly
  changed handle. Do not rebind Workspace or rebuild redirect URI during finalization.
- Membership is exact Workspace/User; current Owner or Manager projection remains
  write-authorized, Member does not. Workspace ownership transfer demotes old Owner
  to Manager and therefore still permits shared write. No membership-instance epoch.
- Shared Toolkit identity repeats current get_shared_by_id predicates and Workspace
  equality. Normal Toolkit update cannot move Workspace/owner/type; deletion remains
  a real invalidator. Do not invent an ownership-transfer product feature.
- Return expected detached authority outcomes in ingress precedence: inactive exact
  subject -> existing 401 Not authenticated/Bearer; missing Workspace -> existing
  404 Workspace not found.; missing membership -> existing 403 Not a member of this
  workspace.; missing write -> existing 403 Toolkit write permission required.;
  missing/shared-ineligible/foreign Toolkit -> existing 404 Toolkit config not found.
  Unexpected database/cipher errors propagate; no catch-all error-to-404 conversion.
- These checks detect committed invalidation when the final operation evaluates it.
  They do not promise authority remains serialized until commit. Use existing plain
  read/query behavior; add no FOR UPDATE/NO KEY UPDATE/KEY SHARE, isolation override,
  cross-I/O lock or retry. Do not imply unlocked reread is commit-time serialization.
- Do not recheck current config/auth-type/revision, final connection existence,
  connection ID/version/status or credential snapshot as a new final fence. Keep the
  captured discovery/client/token fields and current full-upsert replacement rules.
- Provider effects already completed are not automatically undone after authority
  denial. Preserve Workspace success-only temporary-token revoke and existing fatal
  errors; no compensation/revoke/finally/replay policy is added.

Shared disconnect has no external gap and retains its original shared Toolkit +
Workspace read/delete atomic group and existing ingress permission. The saved and
unsaved test reads are snapshots, not final writes. Existing Agent-owned operations
remain authoritative and unchanged in policy; only actual shared helper consumers
move to their canonical definitions. Do not silently add live-role/session checks,
locks or callback rules to Agent persistence as part of this shared slice.

## Ownership and Required Interfaces

| Workstream | Owner | Owned paths | Required output / validation |
| --- | --- | --- | --- |
| API/service and external orchestration | `/root/tx-platform-inventory` | api/public/toolkit/v1/oauth.py, oauth_platform_test.py, oauth_agent_test.py; new services/toolkit_oauth modules/tests and defining pure helper/data; necessary actual Agent helper import/seam updates | All eight API contexts/seven factories/nine query constructors removed; services own metadata/DCR/HTTP/provider tests/state/credential merge; original API AST/schema/error policy and existing Agent definitions retained |
| Completed repository/data/authority helper | `/root/tx-chat-inventory` | new repos/toolkit_oauth_operations.py and toolkit_oauth_data.py; narrowly canonical active-subject DB helper and repos/account_access.py mechanical helper reuse only | Completed typed operations, final existing authority checks plus original atomic groups; no service/API/provider reverse import, no nested operation/lazy handle/callback/alias; focused types/lint/proofs |
| Genuine PostgreSQL and final-authority proof | `/root/tx-engine-input` | new repos/toolkit_oauth_operations_test.py and bounded repository-only helpers/tests | Actual query/upsert/delete/sync/rollback/cancel/closure and independent committed invalidation during paused external work; original query tests preserved; scalar/live connection proof distinguished |
| Integration and delivery | `/root` | phase/master plans, current Specs, shared composition wiring if required; global fixes/QA/freeze/review/commit/PR/CI | Fresh contract baselines; complete caller/removal/authority/alias checks, full backend QA, same retained reviewer and exact-head CI |

No coedit of root/peer source, branch/stage/commit/PR or global formatter/pre-commit
while owners implement. Publish required exact constructors/method/data definitions
before dependent callers/tests. Local names/layout can be refined without new material
behavior; canonical pure helpers must have one actual definition, no compatibility
re-export, private raw factory adapter or optional constructor fallback.

### Completed operations and canonical inputs

A required ToolkitOAuthOperationRepository composes one real session manager and
original narrow queries. Method count need not equal eight contexts:

- Installation sync accepts trusted requester facts, captured Platform App ID and
  operation-specific typed ordered installation records. Re-evaluate existing
  requester admission and perform original full upsert/prune in one transaction.
- Shared OAuth context read returns a named frozen pair of nullable Toolkit and
  nullable connection. Preserve Toolkit then connection read even when Toolkit is
  absent, and one completed read per current connect/exchange call site.
- Shared connection full store accepts trusted requester facts, exact Toolkit ID and
  canonical OAuthConnectionWrite values. Required existing-authority evaluation and
  the original full upsert share one transaction. Metadata/connect and token/exchange
  remain separate later operations at their respective call sites, not one universal
  OAuth transaction.
- Shared disconnect reads/checks exact shared/Workspace Toolkit and deletes connection
  together, without remote revoke; missing connection is idempotent, ineligible Toolkit
  remains nondisclosing not-found.
- Saved/optional-unsaved Toolkit reads return canonical detached snapshots. A null
  unsaved Toolkit ID opens no repository context; ineligible/cross-Workspace/missing
  unsaved lookup remains form-only, while saved lookup remains strict not-found.

OAuthConnectionWrite is already pure in repos/toolkit_operations/owned_data.py; reuse
its actual defining module or relocate only if truly needed with all defining callers,
never re-export. Use existing Toolkit/MCP/metadata/token DTOs. New requester/context/
authority/write/installation payloads are named frozen values. Public request/response
models stay API-defined; no API model or provider registry/callback enters repository.

Decode provider installation JSON into domain records before persistence while keeping
old skip/default/order/duplicate behavior: persistence tolerates missing/non-string
avatar as empty string, public installation response requires a string avatar. Do not
make malformed rows fatal, change IDs/coercion or collapse those distinct projections.
Opaque submitted provider config/credentials are carried in an operation-specific
service input and validated/merged using existing provider definitions after closure;
no new serializer/credential schema or JSON-primitive business dispatch.

## Preserved External and Protocol Behavior

- Toolkit and connection pair snapshots precede metadata discovery/DCR/token exchange.
  No provider/HTTP/Redis/filesystem/Runtime work or arbitrary callback inside SQL.
- Preserve permission checks before external calls and generation-change409 before
  GitHub exchange. Platform resolve, token exchange, list, completed sync, success-only
  revoke, response projection retain order. Agent GitHub path keeps its existing finally.
  Do not recheck Platform generation/config at final write as a new fence.
- Shared connect keeps retained client/token/expiry fields and CONNECTED status even
  without tokens. Agent incomplete connect/reconnect-required behavior stays distinct.
- Shared state still checks Toolkit/Workspace only, ignores initiating User, and uses
  the encrypted redirect rather than adding expected-redirect equality. Agent state
  kind/Workspace/Agent/Toolkit/User/redirect/callback-target checks remain unchanged.
- Exchange absence of refresh token clears it through full upsert; runtime refresh
  retains its separate snapshot/rotation policy. Do not reuse refresh CAS for setup.
- Preserve 400 state/config/discovery/DCR, 404 Toolkit/connection, 409 generation,
  422 OAuth/provider/malformed-token and transparent non-4xx/cipher/DB/unexpected
  provider errors. Response model/operation ID/docs/status/body/callback URI unchanged.
- Preserve saved strict lookup versus optional form-only merge, nested blank/null
  credential retention, submitted discriminator replacement, Kubernetes cluster
  pruning and Platform App credential binding. No new saved-type/owner/version fence.
- Cipher/state/PKCE/provider protocol formats, TTLs, retries, config defaults and remote
  revoke/cleanup remain unchanged. No credentials in Public projection/log/report.

## Removal, Integration and Verification

Remove eight scoped application lifetimes, all seven raw SessionManager declarations,
SQLAlchemy/RDB imports, nine cipher-powered query construction sites and Session-taking
credential helpers from the touched API. Routes call services; repositories own every
transaction. Keep live narrow queries, executed migrations, Agent completed operations,
runtime refresh, generic state/crypto/provider helpers and generated clients.

Preserve all original Platform one and Agent seven test definitions and scenarios;
follow relocated helper monkeypatch sites to canonical owners, not compatibility aliases.
Preserve narrow installation nine and connection/query tests. Original raw factory
sentinels/fake SQL adapters become typed completed operations or genuine PostgreSQL.

Real isolated PostgreSQL matrix covers pair read order/detachment/cipher errors; full
write encrypted fields/retained token/null refresh/status/replacement; actual post-write
fault and cancellation rollback; original read/delete idempotency/atomicity; installation
upsert/prune/order/invalid/avatar/empty/User+App isolation and faults after writes/delete.
Pause actual service HTTP mocks with deterministic events and commit Toolkit deletion,
User disable, exact Session revoke/expire/foreign, membership remove/Manager demotion and
allowed Owner-to-Manager transfer using independent connections; assert approved final
outcomes and no write without introducing extra config/connection/credential fences.
Differentiate savepoint-backed semantics from independent-connection proof; scoped cleanup.

Metadata/DCR/token/GitHub list/revoke/provider-test/public reply witnesses assert no active
SQL on success/error/cancel/no-op. Workspace success-only and Agent-finally revoke are
separately proven. Real queued authority changes use supported primitives/isolated data,
never live credentials/resources. Required E2E shared/Agent unsaved credential tests remain
product proof; any local/live/browser prerequisites are explicit and missing tests are
not claimed passed.

Integration: required source/data contracts -> service/API callers/PG tests -> owner
focused frozen handoffs -> root integrated focused/full backend/whole ty/Ruff/format/
pre-commit/public+admin OpenAPI/client equality/docs/whitespace and actual constructor/
helper/canonical/import/alias/removal/authority scans -> stable freeze -> sole retained
`/root/phase25-independent-review` full-diff read-only review -> grounded corrections /
affected QA / material targeted re-review -> commit/stacked PR over #2067 -> exact-head
required CI/E2E. Root owns every global gate and review request; no next implementation
phase before this phase PR exists.

## Context and Scope Checkpoint

- Target source hash equals both discovery and parent d1c3a7d47. Supporting discoveries
  are outside-repository inputs; this tracked plan alone records approved execution.
- The requester's later #2058 conflict report triggered a separate-worktree stack
  repair onto main `83fc6e43a`. #2060 now preserves the current data-only catalog
  contract together with completed metadata capture; #2065/#2067 patches are
  unchanged. Root repair QA passed 910 focused and 8,234 full backend cases with
  three existing Redis-only skips, whole ty/Ruff/format/docs/whitespace and final
  pre-commit. The same reviewer completed all 118 repair paths with no findings
  and 311 independent cases passed. All four remote heads were updated by one
  atomic explicit-lease push after checking their exact old official tips.
  New-head CI remains a separate gate, not reused original-head CI.
- All three Phase 35 handoffs are frozen: repository three files/69 existing
  regressions; API/service nine files/67 cases; PostgreSQL one file/116 cases with
  an overlapping 45-case actual paused-service independent-commit repeat.
  These overlapping results are not summed as unique tests. Root verified all
  13 source/test hashes, preserved an identified stash, moved this branch to the
  repaired #2067 parent, and restored all 13 files byte-identically.
- Fresh repaired-parent Public/Admin baselines remain 234/69 paths; the OAuth
  API source is byte-identical to the original parent. Fresh comparable candidate
  baseline remains 486/86. Root Phase 35 integrated QA passed against that exact
  parent: 328 focused and 8,409 full backend cases, with three existing Redis-only
  skips in the full suite. Whole ty, changed-13-path Ruff/format, Public/Admin full
  JSON equality, removal/retention/candidate scans, docs/whitespace and pre-commit
  passed; all 13 source/test hashes remain unchanged. Current candidates are
  478/85 (services 477, fixture one); this is not complete indirect coverage.
- Baseline 486 lexical contexts / 86 files. Expected bounded delta eight ->478/85:
  services477 and fixture1, API/Scheduler/Runtime/Worker direct candidates zero. Verify
  actual count and indirect callers; no whole-directory exemption/completion inference.
- Parent attempt-1 transient-looking timeout remains causally unproven; same-SHA local
  1/3 and attempt-2 checks passed without fixture/source/policy edits. Preserve record.
- Implementation, owner checks, root integrated QA and the retained independent
  review are complete. All 18 paths received no findings; independent 328-case
  focus and overlapping 45 actual-service M3 cases passed, bounded 16-path/
  11-schema OpenAPI equality and final frozen-state checks passed. Only execution
  metadata changes after review; all 13 Python and two Spec hashes stay reviewed.
  Submitted as PR #2073 against main at exact head
  `8c949fbffac8ac24020d760725f40aaafcacf4a1`.
- The original PR creation over #2067 failed because that base branch had been
  merged/deleted. All four parent PRs are now externally merged; no Agent merge.
  Fresh main contains a52ef0254 and only three dependency/hook paths changed
  afterward. A conflict-free rebase preserved the complete 18-path patch exactly.
  Updated-environment root QA passed 328 focused and 8,409 full backend cases
  with the same three existing Redis-only skips; all nine gates passed.
  All 13 source/test and two Spec hashes remain independently reviewed.
  Latest actual CI37079167588 attempt1 succeeded: native37success/two path skips
  includes four external CodeQL checks; actual CI jobs33success/two skips.
  Required E2E4shards/web1/aggregate passed; OPEN/MERGEABLE/CLEAN. All four parent
  exact-head latest CI runs also succeeded. Superseded cancelled placeholder jobs
  are separately retained, not treated as current failures or silently discarded.
  Current and parent CI are verified, not inferred from merger. PR #2073 was
  subsequently externally merged on 2026-10-03 KST at merge commit `c90fbbec9`;
  the successor Phase36 therefore submits against main. No Agent merge.
  Design delta None; exception ledger None unless actual evidence
  requires an authority return. No live infrastructure, provider/credential
  mutation, Agent merge, implemented marker or issue #1718 closure.
