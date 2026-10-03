---
title: "Transaction Ownership Phase 37: Signup Token Operations"
created: 2026-10-03
tags: [backend, security, database, architecture]
---

# Phase Execution Plan

- Phase: `37, close all five SignupToken service transaction groups`.
- Delivery limit: the requester clarified on 2026-10-03 KST that this phase must
  finish through validation, independent review, PR creation and exact-head CI,
  then execution stops. Phase38 and later discovery/planning/implementation are
  outside the current instruction. No Agent merge or issue #1718 closure.
- Branch/base: `refactor/transaction-ownership-261002-25-signup-tokens` -> `main`
  at `e9fad839e32b0dd82094984026ae29b689c6dafc`. Original implementation parent:
  PR #2074 exact head `abd26825cadbc1980168300ae2bef0225d4e4826`.
- Start gate: Phase36 all14paths same retained review No findings; independent252
  and root252 focus, fresh main full8,563/three existing Redis-only skips, all nine
  QA gates and complete14precommit pass; full OpenAPI234/69 equality; actual CI
  37089093549 attempt1 SUCCESS/native37success/two path-condition skips; required
  E2E4shards/web1/aggregate/Python/Docker/migration/precommit/CodeQL pass.
  Parent was OPEN/MERGEABLE/CLEAN at the start gate and was subsequently externally
  merged/deleted. Submission targets main; no Agent merge. Preserve exact source,
  baseline and review evidence.
- PR boundary: create/list/preview/redeem/revoke's five application contexts,
  five raw query dependencies plus manager, eleven live-session query call-sites,
  one old constructor fixture and three canonical domain failure definitions.
- Inputs: current User/Auth Spec24, actual Signup service/data, selected narrow
  Signup/User/UserEmail/PasswordLogin/AuthSession queries, exact Public/Admin
  routes, WorkspaceInvitation direct consumer and frozen source-only discovery.
- Deliverables: five completed repository groups, typed prepared redemption input
  and detached success facts, session-free Signup service, canonical pure domain
  failures, unchanged public contracts/defaults/error precedence and atomic
  claim+account+password+Session+audit, genuine SQL closure/rollback/boundary proof.
- Non-goals: PasswordReset lifecycle/restart issue, wider WorkspaceInvitation,
  Auth/Security/Profile/Bootstrap rewrites, new registration-mode/Admin/elevation/
  enabled-user authority, TTL clock policy, distributed/row locks, retry/upsert/
  compensation/outbox, SMTP behavior, API status/schema/client/config/migration
  changes or live infrastructure/provider/production credential actions.
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ1-5; [ADR](../adr/transaction-260908-repository-ownership.md) D1-D3;
  [DESIGN](../design/transaction-260908-repository-ownership.md) revision1;
  current [User/Auth](../spec/domain/user-auth.md) and repository constraints.
- Design delta: `None`. Cross-I/O exception ledger: `None` in this slice.

## Required Local Interfaces

Local typed execution details implement fixed M1/M2; they are not new authority.

Canonical pure `azents.core.signup_token_operations` defines:

- Frozen required `SignupTokenRedeemCommand(token_hash: str, now: datetime,
  email: str, password_hash: str, refresh_token: str, expires_at: datetime,
  max_expires_at: datetime | None, user_agent: str | None, ip_address: str | None)`.
- Frozen required `SignupTokenRedeemFacts(user_id: str, session_id: str)`; no live
  User/ORM/Session/hash/plaintext token/factory/callback escapes in redemption.
- Move the existing frozen `InvalidSignupToken`, `SignupTokenEmailMismatch` and
  `SignupTokenEmailAlreadyRegistered(email: str)` here exactly, preserving fields
  and names. Remove old definitions; update every actual defining caller directly.
  No service.data imports/re-exports/aliases/duplicate definitions in repositories.
  WeakSignupPassword and SignupEmailDeliveryUnavailable remain application-only.

`azents.repos.signup_token_operations.SignupTokenOperationRepository` is a frozen
class with SIX required canonical Depends collaborators: session_manager,
signup_token_repository, user_repository, user_email_repository,
password_login_repository and session_repository. Five async completed methods:

```python
create(*, create: SignupTokenCreate) -> SignupToken
list_all(*, offset: int, limit: int) -> SignupTokenList
get_by_token_hash(*, token_hash: str) -> SignupToken | None
redeem(*, command: SignupTokenRedeemCommand) -> Result[
    SignupTokenRedeemFacts,
    InvalidSignupToken | SignupTokenEmailMismatch | SignupTokenEmailAlreadyRegistered,
]
revoke(*, token_id: str) -> bool
```

Existing SignupToken/Create/List are canonical detached narrow domain DTOs, not
ORM/live handles. Reuse rather than copy them or move unrelated public DTOs.
Revoke samples tznow within its owned scope before the existing narrow update,
retaining the original timestamp position. No new injected clock/options mode.

SignupTokenService replaces five raw query fields and manager with one REQUIRED
operation_repository; REQUIRED email_service/auth_config/config remain (four
fields total). All eight public method signatures/order and four pure functions
remain unchanged. Crypto/random/time/config and public DTO/JWT/SMTP projection
stay in the application. Pure command construction happens before repository
entry; only database composition runs while a repository transaction is active.

Source owner publishes exact materialized interfaces before PG consumers start.
Mechanical identifier refinement is allowed only with coordinated real callers;
no private raw constructor adapter, optional default, generic transaction runner,
callback, compatibility export or nested completed Auth/User operation.

## Original Groups and Policy Preservation

### Create/list/preview/revoke

- Create prepares token_urlsafe32, SHA256, captured app now, expiry/max-use defaults
  before DB. Keep `input.expires_at or default` and `input.max_uses or default`,
  strip/lower email, explicit nullable creator and current delivery enum. One
  insert/flush group; metadata/plaintext output is built only after completion.
  No new collision retry/creator-role/current-subject guard. Token hash stays in
  narrow internal domain data; metadata/list never exposes hash/plaintext.
- List keeps count+created_at-desc page in ONE group; required repository offset/
  limit receive unchanged public0/50 defaults. No extra sort/validation/filter.
- Preview hashes token and captures app now BEFORE DB; one exact lookup closes
  before original missing ->revoked ->expiry<=now ->used>=max predicate order and
  mask output. Invalid remains validFalse/emailNone/expiresNone. No consumption,
  email existence check, after-I/O clock change or new response data.
- Revoke retains exact ID update, fresh timestamp inside scope, True for any
  existing row including repeated revoke, False for absent, API absent404. No
  remote/auth-session/account revoke or stronger already-revoked policy.

### Redemption: one required atomic group

PRE-DB order remains: password-strength validation (Weak failure first even for
bad token), token SHA256, ONE captured app now, normalize email, bcrypt hash,
refresh RNG and expiry/max-expiry derived from the same captured now. Clock stays
before bcrypt; no SQL clock/current-after-hash TTL policy.

Within ONE repository Session retain exact order:

1. Existing get_available_by_token_hash exact hash/revokedNULL/expiry>capturednow/
   used<max; absent ->InvalidSignupToken.
2. Exact normalized pinned email mismatch ->SignupTokenEmailMismatch.
3. Existing UserEmail lookup ->EmailAlreadyRegistered, without consuming claim.
4. Existing conditional claim repeats all availability predicates and increments
   use count; lost claim ->InvalidSignupToken.
5. Narrow create_with_verified_primary_email's User+email circular FK/flush group.
6. Narrow PasswordLogin.create with prepared hash; typed Failure keeps existing
   EmailAlreadyRegistered mapping and ABANDONS prior claim/User writes through
   the primitive's actual rollback. Do not convert this to partial success/commit
   or issue queries after a rollback. Unexpected uniqueness/DB errors propagate.
7. Narrow AuthSession create with prepared refresh/expiries/agent/IP, then exact
   token/User/email/IP/agent/capturednow redemption audit.

Only committed success returns two IDs; JWT and final public output follow close.
Expected early failures keep original precedence; no JWT on failure. Exceptions
and actual task cancellation abort/close; post-commit JWT failure cannot undo or
repeat the accepted database group. No catch-all409 mapping, compensation/retry.
Keep natural SQL conditional UPDATE/unique/FK serialization; add no SELECT lock,
CAS/version/epoch/fence, new account eligibility or permission policy.

M3 is the existing final token/email/claim/unique authority inside this group after
local preparation; there is no provider round-trip or new authority to introduce.
No separately completed User/Auth operation may split this group.

### Direct helper and public consumers

- Email helper's configured check remains before create; actual render/SES send
  follows completed create. SendFalse/unexpected failure/cancel retains created
  token; no cleanup/revoke/outbox. Manual helper/build URL remain unchanged.
- WorkspaceInvitation.create commits its own invitation group and performs its
  Workspace read BEFORE Signup create and send. Preserve separate groups/body;
  do not absorb its wider outstanding scopes or change invitation failure policy.
- Six Public/Admin Signup operations keep exact route/model/schema/default/status
  contracts. Admin role/current subject admission is unchanged. Redeem preserves
  400weak/unavailable/mismatch,409existing-email and422 validation. Unexpected
  DB/hash/JWT/send errors remain transparent. Move only three actual error imports
  in Public Auth; all route bodies and public DTOs remain AST/byte-identical.
- Existing unavailable-email503 is NOT cleanup authority. Existing statusGET
  mode+SMTP versus requestPOST SMTP-only predicates are NOT new denial authority.
  Preserve both; no phase change to registration eligibility/status policy.

## Ownership and Integration

| Workstream | Owner | Owned paths | Required result/checks |
| --- | --- | --- | --- |
| Completed source and canonical application contract | `/root/tx-chat-inventory` | new core/signup_token_operations.py, repos/signup_token_operations.py; services/signup_token/__init__.py, data.py, service_test.py; api/public/auth/v1/__init__.py imports only; new services/signup_token/operation_contract_test.py | Required6collab5groups/4servicefields; canonical3failures; original10tests/eight signatures/four helpers and DTO/API body retention; no live Session/default/alias; focused Ruff/format/ty/tests and frozen handoff |
| Genuine PostgreSQL and application boundary | `/root/tx-engine-input` | new repos/signup_token_operations_test.py; new services/signup_token/operation_boundary_test.py only | Actual selected SQL/order/failure/rollback/cancel/commit/close, final conditional claim/unique state, no partial account group, pure preparation/JWT/output/SMTP after-close witnesses; explicit fixture versus independent-commit evidence and frozen handoff |
| Integration, Spec and delivery | `/root` | plans/current UserAuth Spec/shared corrections only if needed; all integrated QA/freeze/review/commit/PR/CI | Exact authority/scope/retention/canonical/removal/contracts/hash gates; SAME reviewer; parent/current exact-head required CI |

No peer coedit, global formatter/quality/stage/Git/PR/infra mutation by owners.
Integration: required source interfaces -> application/canonical caller closure ->
PG/provider/constructor fixtures -> BOTH frozen handoffs -> root integration and
finalQA -> full stable freeze -> SAME `/root/phase25-independent-review` READ-ONLY
full phase -> root grounded corrections/affectedQA -> commit/PR over#2074 -> actual
head CI/E2E. Root alone requests review/re-review. No next implementation phase
before this PR exists; waiting input preparation never substitutes for this plan.

## Removal and Validation

Remove all five Signup application contexts, manager/SQLAlchemy/RDB imports, five
raw query collaborators and11 Session query call-sites; replace old explicit test
constructor once. Remove exactly three moved service-domain failure definitions
and every old defining import; no compatibility alias/re-export. Preserve actual
narrow queries/models/migrations, public DTOs/data, all old10SignupService and
three narrow query test definitions/body/order, and adjacent Auth/Security/
PasswordReset/WorkspaceInvitation source bytes. Root body/signature/AST/caller/
constructor/alias/reverse-import/lazy/callback/default scans bind those removals.
Comparable candidate checkpoint476/84 expected471/83, NOTfull violation coverage.

Genuine SQL matrix: create/default/custom/hash metadata, count/page order, preview
missing/revoked/expiry/exhausted and captured-clock order, repeated/absent revoke;
redemption typed preconditions and claim loss, complete User/verified email/
PasswordLogin/AuthSession/audit success; actual fault/Task.cancel after selected
SQL, especially post-claim/write positions, rollback/no partial records and actual
close. Verify existing primitive rollback mapping truthfully, not with a fake
Failure that lacks its actual rollback. Distinguish savepoint SQL from standalone
commits; deterministic independent conditional-claim success/loss tests use explicit
barriers/authoritative state and bounded timeout, not sleeps or exploit workflows.
No stronger final-authority-through-commit or driver repeated-cancel promise.

Service witnesses assert no active transaction during strength/hash/RNG/JWT,
EmailService configured/render/send and public response conversion. Verify weak
password opens no SQL, failures create no JWT, lost/error/cancel SQL closes,
post-commit JWT/send failure leaves committed data, no sends when unavailable,
secret fields absent from public metadata. Actual caller/E2E proof stays separate
from named admission/provider doubles. No production secrets/provider effects.

Root finalQA: owner hashes/interfaces -> integrated focused/full backend +wholety,
changed-path Ruff/format/fullprecommit; full Public/Admin OpenAPI234/69 equality /
no generated clients; original models/methods/tests/helper/query/API retention;
removal/canonical/caller/candidate inventory/docs/whitespace; stable all-path freeze
and same review. Existing49directrequiredE2E Signup-fixture test consumers in14
files are source-only lowerbound, not executed or complete coverage; existing
required E2E4shards/web/security/auth/invitation and CodeQL CI remain product proof.
Missing/live prerequisites and skips are explicit; no live resources/credentials.

## Context and Scope Checkpoint

Root read fixed authorities/current Spec, full33.8KB frozen discovery, actual
Signup service/data/query/DTO/Password narrow rollback and WorkspaceInvitation
caller; root verified five scopes/one constructor/three moved-error caller closure.
Auth/Security/Profile production scopes are already completed; do not remigrate.
PasswordReset's separate rollback/query-restart concern remains SOURCEINFERENCE,
not reproduced/exploited/confirmed or selected policy. It is explicitly deferred,
not swallowed into this slice. Broader remaining domains/helper/callback/exclusion
coverage persists. No implemented snapshot marker/Agent merge/#1718closure.

Before implementation, root captured parent OpenAPI/AST/source bytes and candidate
checkpoint, then staged/reported and attached this FULL plan and required contracts.
Both owners started only after that gate. Discovery remains input evidence, never
execution authority. Design delta None; source/PG/root QA now complete, while
independent review, commit/PR and exact-head CI remain pending.

## Integrated Validation Checkpoint

- Source owner seven files frozen, all hashes verified: 30 passed/no skips,
  comprising 17 pure contract cases plus all original10service/3query cases;
  scoped Ruff/format/ty passed. Root retained all eight public signatures, four
  pure functions, three unchanged post-operation helpers, whole10/3test ASTs,
  canonical three moved errors/public DTOs and entire Public Auth nonimport AST.
  Fifteen selected narrow/model/API/adjacent source byte hashes remain unchanged.
- PostgreSQL owner two files frozen, both hashes verified: 79 passed/no skips,
  42 repository and37 boundary cases. Of those, 37+31 are savepoint-backed and
  5+6 are standalone. Eleven overlapping independent/commit cases repeated
  successfully; no unique-count addition. Actual primitive rollback, natural
  conditional-claim and email-unique contention, post-awaited real SQL faults/
  Task.cancel, original vendor close and post-commit JWT/delivery retention
  preserve existing authority and failure behavior. Named transport/bcrypt
  doubles are distinguished from real SQL, JWT/bcrypt and template witnesses.
  Root parsed final79/repeat11 XML, each with11distinct-PID cases; final14selected
  SQL fault properties include seven actual cancellations. No driver/repeated
  cancellation, live SES or new whole-feature coverage claim.
- Root global QA on the final main environment: 302 focused passed/no skips;
  8,698 full backend cases passed, three existing Redis-only skips/six warnings,
  348.43 seconds. Whole backend ty, all nine changed Python Ruff/format, full
  13-path pre-commit, documentation18tests/catalog/whitespace and complete
  Public/Admin OpenAPI234/69 JSON equality passed. All nine Python hashes stayed
  equal through QA; schema/client output has no diff.
- Parent2074 external merger and 18 incoming Engine/xAI/ExternalChannel repository/
  Spec/test changes were verified as non-overlapping, with no dependency changes.
  After both owners froze, root preserved all13phase files in an exact owned stash,
  rebased with the canonical script, then restored the index. Every file hash and
  complete binary/full-index phase diff remained identical. The owned stash is
  retained until commit, remote and CI preservation; other Session work is untouched.
- Removal/canonical/constructor checks passed: all five application scopes/six DB
  dependencies/eleven Session calls and old three failure definitions/imports are
  absent. Comparable candidate476/84 ->471/83; direct service475/83 ->470/82,
  with one fixture unchanged. These are bounded direct counts, not complete
  indirect/alias coverage. No later phase begins after this delivery.
- The SAME read-only reviewer `/root/phase25-independent-review` completed all13
  frozen paths with No findings. Independent302focus/no skips, original whole
  redemption-group/preparation AST equivalence, canonical/interface/API/retention
  and final index/tree/file freeze passed. Reviewed tree `f173a92c51446d8dd2bdb4cead65f47b7e3e0863`,
  full-index diff SHA256 `13b48458907f5c555d2eb23b5ff80f6981fa2ae267cebab417f9abb0eec13673`.
  No source correction or re-review trigger; only this execution metadata changes.
  Commit/PR and exact-head required E2E/CodeQL remain post-review gates, then stop.
