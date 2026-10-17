---
title: "Personal Tools Phase 2: Management and Provider Authentication"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, implementation, api, authentication]
---

# Phase Execution Plan

- Phase: 2/4, personal management and Provider authentication.
- Branch/base: `feat/personal-tools-management-261017` ->
  `design/personal-tool-access-261017` at e5add532e; depends on phase 1 PR #2316.
- PR boundary: authenticated owner-only personal Toolkit management and access-policy API, common
  configuration/validation/readiness behavior, owner-bound Provider setup/callback/current-grant
  adapters, preserving existing shared/Agent contracts, and generated public clients.
- Inputs: confirmed Requirements and accepted ADR D1-D3, approved Design revision 1 M1-M11,
  phase 1 canonical owner/policy schema and operations, existing Provider registry and setup flows.
- Deliverables: create/list/read/update/delete personal connections; complete eligible-Agent policy
  reads and atomic delta saves from both editor contexts; Provider option/authentication parity;
  personal MCP, GitHub and Google setup/review/reconnect/disconnect targeting the exact active owner;
  explicit owner-target schema migration where current setup state requires a Workspace.
- Non-goals: personal execution-source activation, root Session admission, Tool dispatch/Runtime
  export, production Web UI, live Provider accounts, deployment or merge. Do not add personal-only
  Provider exclusions, export restrictions, alternate aggregates, fallback, flags or versioning.
- Interfaces: derive User/Auth Session from current active authentication; never accept arbitrary
  owner identity in request JSON. Preserve Workspace-only response contracts; personal public DTOs
  omit credentials and carry explicit owner/access summaries. Use required expected-mode plus
  membership deltas, not a filtered selection replacement. Provider setup targets are closed owner
  variants; old shared payloads retain their current contract and cannot be interpreted as personal.
- Approved Design mechanisms: M3/M4/M10/M11; consume M1/M2 and preserve M7 parity without activating
  M5/M6/M8 execution. Common Provider implementations remain authoritative.
- Authority: REQ-1/2/3/5/6/7/8/9; ADR-D1/D2/D3; Design sections 3.3/4/5/8/9/10; current Toolkit,
  MCP OAuth and Google connection Specs and account authorization conventions.
- Design delta: None.
- Removal obligations: replace Workspace/Agent-only setup target assumptions in the personal path;
  remove duplicate ownership interpretation at touched management boundaries by decoding typed
  owner variants. Retain valid existing shared callbacks, staged attempts, grants, setup resources,
  namespaces and all common configuration/credential validation.
- Absence verification: exact owner-target rejection and no-workspace tests; shared/Agent regressions;
  foreign Auth Session, owner/target swap, canceled/replayed attempts, stale publication/refresh and
  option parity tests; source-generated clients and migration metadata alignment.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Common management | /root | `core/toolkit*`, `repos/toolkit*`, `services/toolkit*`, personal management service | phase 1 | common validation/readiness with owner-scoped completed operations | CRUD/foreign owner/field parity and SQL boundary tests |
| Provider owner targets | /root | MCP/GitHub/Google core contracts, repositories, services and setup RDB models/migration | common management | exact owner/current-session setup and unchanged Provider lifecycle | staged/callback/replay/stale-grant and existing owner regression tests |
| Public interfaces | /root | `api/public/toolkit/v1`, related router registration, generated OpenAPI and public clients | stable services/Provider contracts | authenticated personal API with redacted typed responses | route authorization/schema tests and source regeneration |
| Integration evidence | /root | phase plans and relevant Specs when newly reachable | stable integrated diff | root-owned validation and single-reviewer checkpoint | Ruff/ty/pytest/migrations/docs/diff and PR CI |

- Integration order: inspect current Specs/Provider contracts and current-account dependency ->
  common owner-aware validation/readiness and personal CRUD/policy operations -> closed Provider
  setup targets and preserving schema -> authenticated personal routes -> source-generated clients ->
  focused real PostgreSQL/service/route regressions -> root integrated validation -> frozen reviewer
  request -> corrections and affected validation -> commit/phase PR.
- Independent review: `/root/personal-tools-reviewer`, read-only one-way review of the complete
  integrated phase diff, requested only by root after implementation and validation. Root applies
  every correction and requests targeted re-review only for material boundary findings.
- Final validation: backend Ruff format/check and configured ty; focused pytest across owner/current
  account/Toolkit/MCP/GitHub/Google services, repos and routes; full migration suite if schema changes;
  generated client checks; documentation catalog and diff check. Prepare deterministic fake Provider
  routes/barriers for cross-boundary acceptance in the final phase; no live-provider claims.
- Scope-drift check: no prepared personal source is made executable in this phase. No new product
  configuration, authority, fallback, auth family, relay, Runtime or version mechanism is introduced.
  Any new material requirement returns to approved authority; equivalent helper layout stays local.
- Context checkpoint: phase 1 PR #2316 open, review/re-review clean, 320 scoped tests and 48 migration
  tests passed. Additional complete backend regression on phase 1 completed: 12777 passed,
  3 existing Redis-only contract cases skipped for the non-Redis backend, 9 warnings in 362.11s.
  Phase 1 CI, including required/Web E2E regression gates, completed successfully; no merge.
  Phase 2 plan was recorded and reported before implementation. No production schema or Provider
  account action performed.

## Working Integration Checkpoint

- Common Provider configuration creation and update preparation now accepts owner-independent
  fields while preserving existing shared service/response contracts. Personal management uses
  completed current User/Auth Session operations, current Platform registration checks, canonical
  parent locks and existing source revision comparisons after external preparation.
- Personal CRUD, full eligible-Agent listing, connection access deltas and atomic exact-Agent batch
  endpoints are integrated locally. Redacted response fields reuse the common Toolkit projection;
  transient request validation excludes credential/code/state inputs from error bodies.
- Personal MCP connect/exchange/disconnect reuses common discovery/registration/manual-client/PKCE
  helpers. Its encrypted callback binds exact User owner, initiating Auth Session, Toolkit identity
  and existing source revision. Disconnect/source replacement invalidates late publication. This
  reuses the existing source revision; no new permission version or alternate credential authority.
- Google staged setup/review/confirm/reconnect/outcome/disconnect now accepts an explicit personal
  target beside existing Workspace/Agent contexts. Personal callback purpose/owner/Auth Session is
  distinct; final publication reuses canonical Toolkit/grant storage and starts All. Reconnect
  preserves allowance and unrelated concurrent metadata, retaining existing Provider grant checks.
- GitHub saved connection and unpublished creation contexts now include explicit User ownership.
  Both use existing App verification, candidate review, current registration/grant replacement,
  cancellation and bounded cleanup. Personal publication preserves all transport/Runtime injection
  settings, default All and canonical identity. PAT/provided-App/Platform-App setup verification
  shares the existing service and exact current Platform installation checks.
- Generated migration `004bda2b6938` extends Google attempts and GitHub attempts/creations with legal
  owner kinds/keys. Existing staged payloads remain unchanged; inconsistent old ownership fails
  explicitly. User-owned cleanup cascades correctly, and downgrade refuses to discard personal
  staged state. No new source of truth or migration is applied to production.
- Personal saved/unsaved connection-test endpoints use common Provider validation, credential merge
  and Platform binding; foreign saved IDs reject before Provider I/O, drafts do not persist, and
  current account/source is checked after external preparation.
- Root validation of this partial phase: 555 focused repo/service/API/OAuth/core tests passed in
  36.95s (four existing warnings); complete migration suite: 50 passed in 80.52s (two warnings).
  Backend-wide Ruff/format (2546 files) and ty passed. OpenAPI plus both public clients regenerated
  from source after the new endpoints; Python generator-template tests: 16 passed; direct generated
  TypeScript `tsc --noEmit`: passed. No live Provider acceptance is claimed.
- Personal Platform GitHub install/start/sync now reuses the common SDK acquisition and revocation
  sequence. Encrypted state binds explicit User owner, exact Auth Session and Platform generation.
  The post-Provider transaction rechecks current account, current Platform settings and App authority
  before updating the existing User-global installation inventory; failed synchronization does not
  run success cleanup. Controlled tests cover foreign User/login/shared state, generation changes,
  revoked login, database failure, owner-scoped persistence and pruning.
- Production Provider-registry parity tests preserve common config, credential, prompt and exposure
  fields through personal create/update, including MCP none/header/bearer/OAuth, Notion, Sentry,
  AWS, GCP, Google Analytics, Brave, GitHub PAT/provided-App and all four Kubernetes credential
  families. Google and GitHub user-account publication remain on their existing staged lifecycle.
  Personal installation HTTP tests cover exact account projection and safe validation/denial.
- Latest root focused selection: 583 passed, four existing warnings in 40.32s. Complete migration
  suite: 50 passed, two existing warnings in 80.42s. Backend Ruff/format (2549 files) and configured
  ty passed. Final OpenAPI and both public clients regenerated; Python template tests: 16 passed;
  direct generated TypeScript client typecheck: passed. Full backend regression: 12867 passed,
  three existing Redis-specific contract cases skipped, nine warnings in 357.35s.
- Current reachable management behavior is recorded in Toolkit, MCP OAuth and Google connection
  Specs without claiming personal runtime or Web activation. Combined feature Spec promotion and
  deterministic end-to-end acceptance remain in the final phase. Design delta: None.
- Remaining phase work: complete the full backend regression, freeze the integrated diff, obtain
  the mandatory read-only review, apply findings and affected validation, then commit and open the
  Phase 2 PR. No live Provider acceptance, deployment or production migration is claimed.

## Independent Review Corrections

The fixed reviewer requested four corrections on the first frozen integrated diff:

- Platform GitHub connection tests now repeat exact current account, source, App generation and
  selected installation-inventory admission before server App token exchange or MCP I/O. Saved
  stale App identity cannot silently rebind. Real Provider tests with controlled external functions
  assert zero token/MCP calls for foreign IDs, withdrawn inventory, preparation-gap withdrawal,
  stale App and malformed installation IDs; an authorized installation remains testable.
- Personal PATCH uses the common safe GitHub error mapping for registration-change conflicts.
  HTTP tests exercise both reviewed and active real personal grants, expect 409, and preserve
  the saved registration/grant. Current Google projection denials use the common Google mapping.
- Personal Google list/detail/Agent-choice readiness uses the existing safe Google status service
  with explicit personal ownership, including disconnected/reconnect/client/operator conditions
  and disabled-state precedence. No renewal or remote probe is added.
- Personal GitHub user-account access observations now expose the common owner-authorized service
  with bounded cursor continuation. HTTP tests cover current owner, foreign owner, continuation
  and cursor validation; clients were regenerated from the new endpoint.

These corrections restore approved M3/M4 parity and authority; Design delta: None. Root-owned
correction validation: 12886 backend tests passed, three existing Redis-specific cases skipped,
nine warnings (381.77s). The final personal-only Google-denial mapping and its two additional cases
are covered by the final 604-test focused rerun (four warnings, 41.61s). Backend Ruff/format/ty,
OpenAPI/client regeneration, Python template tests (16), direct TypeScript client check, docs/diff
checks and staged pre-commit hooks passed. Migration source is unchanged from the 50-test result.
The same fixed reviewer completed targeted read-only re-review of corrected diff
`ad190259c496447aad699b0b38ae714aae2e971ef7d0d4787f6ed56d2d247a4c`: all four findings
cleared with no additional findings in the affected boundaries. This checkpoint records that result;
implementation is ready for commit and the Phase 2 PR. No live Provider or final product-E2E
acceptance is implied.
