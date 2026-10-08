---
title: "Transaction Ownership Phase 36: Credential Read Projections"
created: 2026-10-02
tags: [backend, security, database, architecture]
---

# Phase Execution Plan

- Phase: `36, close Credential read lifetimes and provider Session contracts`.
- Branch/base: `refactor/transaction-ownership-261002-24-credential-reads` ->
  `main` at `48aaa54646471e4748d09f88c799582e18ea86cc`. Original implementation
  and review parent: PR #2073 exact head
  `8c949fbffac8ac24020d760725f40aaafcacf4a1`.
- Start gate: Phase35 root 328 focused / 8,409 full cases with three existing
  Redis-only skips; latest-main/dependency environment repeats, whole ty/Ruff/
  format/full OpenAPI234/69/absence/docs/whitespace/pre-commit pass. Same retained
  reviewer all18paths No findings / independent328 plus overlapping45 M3 and final
  freeze pass. Parent actual CI37079167588 attempt1 success, native37success/
  two path-condition skips including four external CodeQL checks; actual CI jobs
  33success/two skips. Required E2E4shards/web1/aggregate pass, OPEN/MERGEABLE/CLEAN.
  Earlier2058/2060/2065/2067 exact-head CI success separately verified; externally
  merged, no Agent merge. Parent branch existed at the start gate; #2073 was
  externally merged/deleted before submission, so delivery now targets main.
- PR boundary: exactly two CredentialService read factory contexts and six
  Session-taking declarations (Protocol two / concrete four), actual provider
  query/default-factory/constructor closure, and Auth/Security test composition.
- Inputs: current Credential five files, selected User/UserEmail/PasswordLogin
  narrow reads, EmailService.configured pure availability, existing Auth/Security
  admission, current User/Auth Spec and frozen read-only discovery.
- Deliverables: two completed repository read groups, canonical detached ordered
  facts, session-free application providers/projections, unchanged public APIs/
  User absence/order/last-credential rules, genuine PostgreSQL closure/error/
  cancellation/order proof and unchanged original test definitions.
- Non-goals: password/OTP/hash/session/signup/reset/OAuth mutation, disabled-user
  eligibility/privacy policy, new final authorization/locks/isolation/TTL/retry,
  deduplicated queries/providers, provider-order reduction, schema/client or
  infrastructure changes. No post-external-I/O final mutation exists here.
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ1-5; [ADR](../adr/transaction-260908-repository-ownership.md) D1-D3;
  [DESIGN](../design/transaction-260908-repository-ownership.md) revision1;
  current [User/Auth](../spec/domain/user-auth.md) and repository constraints.
- Design delta: `None`.

## Required Local Interfaces

These are local typed execution details within M1/M2, not new Design authority.

Canonical pure module `azents.core.credential_read`:

- `CredentialReadKind(StrEnum)` with PASSWORD and EMAIL query kinds. Query kind
  describes the actual built-in query behavior, independently of a provider's
  existing projection credential_type attribute.
- Frozen required `CredentialReadFact(kind: CredentialReadKind, configured: bool)`.
- Frozen required `CredentialReadSnapshot(facts: tuple[CredentialReadFact, ...])`.

`azents.repos.credential_read_operations.CredentialReadOperationRepository` is a
frozen dataclass with four required canonical Depends collaborators: session_manager,
user_repository, user_email_repository and password_login_repository. Public async:

```python
read_user_snapshot(*, user_id: str,
                   kinds: tuple[CredentialReadKind, ...]) -> CredentialReadSnapshot | None
read_login_snapshot(*, email: str,
                    kinds: tuple[CredentialReadKind, ...]) -> CredentialReadSnapshot
```

One original group per call, including empty kinds; User absence is None only for
user snapshot's initial User read. Facts preserve input order and duplicates.
No callbacks/providers/services/EmailService/API imports, live Session/ORM/factory
return, completed operation nesting, compatibility alias or optional constructor.

CredentialService replaces its raw factory/User query dependencies with one required
completed repository; its required provider list and all five public signatures
remain. Providers expose a pure fixed read_kind (property/class constant, not a
new optional constructor field) and session-free get_user_summary/get_login_summary
methods consuming the corresponding required fact. Keep the existing async method
names if useful; no Session/user query argument or repository constructor remains.
Their pure _build projection bodies and existing credential_type behavior remain.
EmailService stays an application collaborator; configured remains a pure bool.
Registration retains Password then Email. No concrete provider or duplicate is
removed. Summary/projection/removal/public types stay in their existing actual
service defining module; repositories need only new pure fact types.

Actual defining names can be refined mechanically only with coordinated callers,
but no compatibility wrapper/re-export/private raw constructor or generic DB runner
is permitted. Source owner publishes exact shapes before PG consumers implement.

## Original Atomic Reads and Preserved Policy

- User group: initial User.get; None skips every provider. For each ordered PASSWORD
  kind, PasswordLogin.exists_for_user. For each EMAIL kind, repeat User.get even
  after initial eligibility; late absence gives configured=False only for that
  Email fact, otherwise UserEmail.list_by_user and ANY verified linked email.
  Do not collapse the second User read, require primary-only or split the group.
- Login group: each PASSWORD kind reads User.get_by_email accepting any linked
  email, then password EXISTS only when User present. Each EMAIL kind reads
  UserEmail.get_by_email regardless of Password absence, and verified presence
  determines configured. No enabled-user/primary/verified-address filter is added
  to public password availability. Empty provider list retains an operation scope.
- Current plain READ COMMITTED reads are not an immutable-snapshot or commit-time
  serialization guarantee. No row locks, isolation, retries or subject revalidation.
- Service builds summaries only after completed facts. Public by_type keeps LAST
  Password result; removal check keeps FIRST matching summary. Lists preserve
  order/multiplicity. _apply_remove_invariants counts duplicate valid summaries
  and overwrites raw can_remove; configured but SMTP-invalid Email is removable,
  sole valid credential gets last_valid_credential. Recovery reason remains valid.
- Public email_available is any actual EmailCredentialProvider (including subtype)
  with configured EmailService, independent of supplied address/verification/User.
  A Protocol object merely claiming EMAIL still does not satisfy that isinstance.
- Security enabled=valid; elevation enabled=can_elevate; exact fields/null reasons
  and current conversion stay unchanged. Missing User remains normal None/404.
- Public login-methods stays unauthenticated and minimal; security/auth-methods
  requires existing current subject then elevation; elevation-methods requires
  current subject only. Preserve401/Bearer ->403elevation ->404projection absence.
- M3 final-write obligation: None in this slice. Credential projection is not
  password deletion authority; existing SecurityOperationRepository final DELETE,
  SMTP flag and verified-email predicate remain untouched.
- SMTP/HTTP/files/hash/crypto are not reached inside the current built-in groups;
  EmailService.configured is only config/client presence. No new sends/effects.
  Unexpected DB/provider/Pydantic errors and CancelledError remain transparent.

## Ownership and Integration

| Workstream | Owner | Owned paths | Required result / checks |
| --- | --- | --- | --- |
| Required source, pure facts and application closure | `/root/tx-chat-inventory` | new core/credential_read.py and repos/credential_read_operations.py; services/credential/service.py, providers.py, original service_test.py and bounded new providers_test.py; Auth/Security original service_test.py constructor helpers only | Exact completed groups/required DI, pure projections, no Session interfaces/factories; all original5/15/3 test definitions retained; focused Ruff/format/ty/tests |
| Genuine PostgreSQL and closure proof | `/root/tx-engine-input` | new repos/credential_read_operations_test.py; bounded new services/credential/read_boundary_test.py only | Actual SQL/query order/absence/duplicates/secondary-email/disabled/read detachment/fault/task-cancel/closure, pure provider and public reply witnesses; actual completed source, no fake SQL guarantee |
| Integration and delivery | `/root` | plans/current Spec/shared composition only if required; integrated corrections/QA/freeze/review/commit/PR/CI | Required exact contracts, source hash/retention/API/removal/inventory gates, sole retained reviewer, latest-head CI |

No peer coedit, source outside ownership, global formatter/quality/stage/Git/PR or
live action while owners work. No implementation starts before root reports this
FULL tracked plan and contracts, with Design delta None.

Integration order: source contract -> repository and service defining callers -> PG/
provider/constructor fixtures -> owner frozen handoffs -> root integration/QA ->
all-path freeze -> SAME `/root/phase25-independent-review` read-only full phase ->
grounded fixes/affected validation -> commit/new PR over#2073 -> exact-head CI/E2E.
Root requests every review and owns every integrated gate. No next implementation
phase before this PR exists; complete source/CI checkpoints remain explicit.

## Removal and Validation

Remove both application contexts, service factory/raw UserRepository declaration,
all six Session-taking provider declarations, two live-Session invocation sites,
four default query factories, application SQLAlchemy/RDB imports and obsolete raw
constructor test plumbing. Preserve actual narrow repositories/migrations/fixtures,
service data/projection outputs and all adjacent completed Auth/Security operations.

Absence proof: current source AST/import/caller/constructor/defining symbol scan,
new service/provider no Session or raw query dependency, repo no reverse application
imports/callback/lazy return/added lock; actual original5Credential/15Auth/3Security
name/order retention and original narrow query bytes. Compare full Public/Admin
OpenAPI234/69 and bounded three unchanged operations/models/status/details/schema,
no generated-client diff. Candidate baseline478/85 expected476/84, but inspect
actual source and do not claim full alias/indirect coverage from lexical counts.

PG matrix: initial/late User absence, configured/unconfigured password, ANY verified
secondary address, exact email lookup, unverified/unknown/public availability,
disabled-user current read behavior, ordered duplicates/reverse/empty provider
kinds; real errors/cancellation after each selected SQL read close scopes with no
mutation. Scoped actual service/provider config/property/summary/projection witnesses
assert completed DB before pure application work. Preserve last/first/duplicate
removal invariants and SMTP-invalid removability; retain existing protected admission
and original Auth/Security regression. No invented write/lock/blocking guarantee.

Root final gates: owner hash/contracts -> integrated focus/full backend/whole ty/
scoped Ruff+format/pre-commit/OpenAPI/client equality/AST/query/test retention/
removal/caller/alias/inventory/docs/whitespace -> stable freeze -> same independent
review -> commit/PR -> exact-head required E2E/security consumers/CI. Existing ten
required security E2E consumers are product proof; missing/live/browser credentials
and optional skips are explicit, not claimed passed. No production secrets/resources.

## Context and Scope Checkpoint

Discovery `phase35-credential-next-discovery.md` is frozen outside-repository input,
not execution authority. Root read current User/Auth Spec and actual four Credential
bodies. Five primary files match the discovered a52 parent and current8c source.
Original query/cancel cleanup source inference is NOT executed proof; genuine tests
remain required. Actual scope is two reads, not a new Auth/Security rewrite.
Parent #2073 exact-head CI/QA/review is verified and was externally merged.
Both owner handoffs are frozen; integrated source/contracts/PG, root QA and the
retained review are complete. Submission and exact-head CI remain pending.
Design delta None; cross-I/O exception ledger None. No live action, Agent merge,
issue #1718 closure or implementation markers. Broader services/remaining coverage
stays explicit after this slice.

## Integrated Validation Checkpoint

- Source owner: all eight frozen hashes match; 60 focused cases passed, including
  37 new pure/completed-contract cases and all 23 original Credential/Auth/Security
  cases. Scoped Ruff/format/ty passed. Root independently verified original whole
  test ASTs (5/15/3), all five public service signatures, both provider projection
  bodies, narrow query/model/public API/data and adjacent authority byte retention.
- PostgreSQL owner: 104 cases passed with no skips (61 repository and 43 actual
  service/provider/API conversion boundary cases). Of the 61, 59 are real fixture
  SQL cases and two use independently committed changes on distinct PostgreSQL
  connections. The overlapping 16 fault/cancel/late-change repeat passed and is
  not added to the unique count. All seven selected read positions execute actual
  SQL before error or an explicit task-cancellation barrier; normal/None/empty/
  error/cancel paths await actual close and have no active transaction. Original
  reads, secondary verification, duplicate/reverse/empty kinds and disabled/late
  User semantics are preserved. Plain-read evidence is not serialization proof;
  protected-route current-user admission is explicitly stubbed, not JWT proof.
- Root-owned final matrix: 252 focused passed/no skips; full backend 8,550 passed,
  three existing Redis-only contract skips, six warnings, 343.88 seconds. Whole
  backend ty, all ten changed Python Ruff/format, pre-commit, docs validation,
  documentation catalog 18 tests and whitespace passed. Full generated Public/
  Admin OpenAPI remains exactly equal at 234/69 paths; generated clients/schema
  have no diff. All source hashes were unchanged during integrated validation.
- Removal: two Credential application scopes, six provider Session declarations,
  two live-Session invocation sites and four query default factories are absent.
  Canonical required facts/operations have no callback/lazy/ORM/factory escape or
  reverse application imports. No write/lock/isolation/policy mechanism added;
  actual password deletion authority remains untouched. Comparable candidate
  inventory is 478 contexts/85 files -> 476/84 (475 service contexts and one
  fixture), not a confirmed residual-violation or complete coverage count.
- The same read-only reviewer `/root/phase25-independent-review` completed all
  14 frozen paths with No findings; independent 252-case focus, whole original
  test AST/caller/byte retention and logical index/tree/file freeze passed.
  Raw index metadata refreshed without changing any staged blob or source.

## Submission Checkpoint

- Reviewed tree `38cbd3bcf6e8f5f67050328294bc2fdd7559f478`, complete binary/full-index
  diff SHA256 `ad210243aa2c86b0423d04f2a2fb71cb07682488ad25ccc4b911cc8efdaebfb2`.
  Reviewed commit `18a4a138f` was rebased without conflict to `c2faade704`.
- Parent #2073 was externally merged into main at `c90fbbec9`; that tree was
  identical to the fixed review parent. A later fresh fetch also found external
  #2072 at `48aaa5464`, affecting seven Model Catalog/web-search/docs/test paths
  with no phase overlap or dependency change. The safety equality gate stopped
  before rebase; after inspection, the canonical rebase script preserved the
  entire 14-path phase patch and every reviewed file hash exactly.
- Fresh main-environment root QA passed all nine gates: 252 focused/no skips,
  8,563 full backend cases with the same three Redis-only skips/six warnings,
  348.13 seconds; whole ty/Ruff/format, OpenAPI234/69 equality, absence, docs and
  whitespace. Original 8,550-case evidence remains separately retained. All ten
  Python and the User/Auth Spec hashes remain reviewed; only plan execution
  metadata changes after review. No behavior correction or re-review trigger.
- Submitted as PR #2074 against main at exact head
  `abd26825cadbc1980168300ae2bef0225d4e4826`. Actual CI37089093549 attempt1 succeeded:
  native37success/two path-condition skips including four external CodeQL checks;
  actual CI33success/two skips. Required E2E4shards/web1/aggregate, Python, Docker,
  migrations, pre-commit and CodeQL all pass. Final OPEN/MERGEABLE/CLEAN; parent
  #2073 exact-head checks separately remain successful and externally merged.
  No Agent merge, live change, implementation marking or issue #1718 closure.
