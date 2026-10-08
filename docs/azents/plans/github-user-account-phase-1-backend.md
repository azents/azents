---
title: "GitHub User Account Toolkit Phase 1 Backend"
created: 2026-10-08
tags: [github, toolkit, backend, security]
---

# Phase Execution Plan

- Phase: 1/3 backend authorization and bounded fail-open cleanup.
- Branch/base: `feat/github-user-261008-backend` -> main at `e9f8ff027`; current PR [#2222](https://github.com/azents/azents/pull/2222).
- Inputs: confirmed REQ-1..13, current ADR-D1/D2/D4, Design revision 4, M1-M10 and M12. M11 is retired.
- Design delta: None relative to revision 4.
- Deliverables: distinct user registration, exact-bound one-use OAuth, non-expiring validation, staged account confirmation, personal/multi-org observations, redacted summary/availability, additive schema, and a captured-token SDK cleanup attempt that fails open.
- Non-goals: refresh/proxy/hub/actor, retained cleanup/retry, cleanup-completion proof, cleanup deletion blockers, live provider operations, merge/deployment.
- Interfaces: detached typed request/attempt/connection/revocation facts; repositories finish local transactions before service SDK calls. Revocation facts are transient, not a new persisted aggregate.
- Removal obligations: remove unmerged cleanup table/enum/DTO status, retry routes and summaries, invalidity probes used for cleanup, parent cleanup barriers, issued-receipt/in-flight cleanup guarantees and exchange task owner. Keep real setup/current authority and source-identity checks.
- Absence verification: source/schema/API search and tests show no cleanup pending/retry/owner/deletion barrier; revoked-token targeting remains captured and no App grant deletion/uninstall occurs.

| Workstream | Owner | Paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Persistence simplification | `/root/github-user-persistence` | core user DTOs, user DB models/repository/tests and existing unmerged migration | active/candidate encryption; transient cleanup facts; no retained cleanup or tombstone | SQL lifecycle, migration and one-use/replacement tests |
| Service/API simplification | `/root/github-user-service` | user service/API/tests; removal of exchange owner | bounded awaited revoke; sanitized warning on expected failure; local success; no retry API | fail-open success/failure, late result and redaction tests |
| Parent deletion simplification | `/root/github-user-provider` | Agent delete/decommission paths and obsolete parent guards/tests | known-token cleanup attempted outside DB without deletion gate | deletion with failed cleanup and exact-scope tests |
| Existing Toolkit integration and generated contracts | `/root` | Toolkit summaries/mutation/delete integration, generation/docs/plans | no cleanup status/retry fields; retained locked-current identity protection | integrated quality/regression/client checks |

- Integration order: DTO/repository -> service/API -> parent/Toolkit integration -> root checks -> stable targeted single-reviewer check -> commit and normal PR update.
- Single independent reviewer: `/root/github-user-reviewer`; root requests review after integration is stable. The reviewer must use fail-open authority, not reintroduce superseded completion guarantees.
- Root validation: backend Ruff/format/typecheck, focused and full suites as appropriate, schema/client generation, docs validation and deterministic races.
- Scope drift: fail-open is cleanup-only. Wrong OAuth state, replay, stale identity/context, unauthorized mutation and execution fallback still fail closed.
- Checkpoint: earlier backend commit `8eb20d65f` passed 11,786 tests /3 skipped and independent review under revision 3. That evidence does not verify this revision 4 change. UI work is safely stashed while the backend contract is simplified; no deployment or live provider mutation occurred.

## Revised Integration Checkpoint

- Revision-4 production source is frozen for the same independent reviewer. Root integrated atomic current-row Toolkit deletion capture, post-transaction revocation, removal of duplicate API disconnect preflights, parent ownership isolation and redacted response simplification.
- Root full-subproject Ruff, formatting and `ty check --error-on-warning` passed. Related user OAuth, repository, Toolkit/API and service suite: **146 passed**, 14.47 seconds. Whole backend: **11,757 passed, 3 skipped, 9 warnings**, 410.06 seconds.
- Separate parent evidence: **48 passed**, including PostgreSQL ownership isolation and GitHubKit failure/timeout fixtures. Persistence's **10 PostgreSQL tests** exercise the simplified migration upgrade/downgrade, three stored attempt states and full unique Toolkit attempt index.
- Public OpenAPI and Python/TypeScript clients were regenerated. The generated Python user-contract import/absence smoke and direct Public-client TypeScript compilation passed. Documentation catalog and whitespace checks passed.
- An earlier API test used the synchronous SDK transport argument and did not reliably intercept async requests. That evidence was invalidated; the corrected `async_transport` fixtures assert intercepted exact-token DELETE requests for both 204 and 503. No real credentials or App registration were used. Final related and whole-backend results above include the corrected fixture.
- Production/schema/API absence checks find no user cleanup pending/retry, retained cleanup table/enum, issued-token receipt/in-flight flag, proof probe, completion owner or cleanup-based parent deletion barrier.
- Expired or stale review candidates remain unconfirmable. New setup, explicit cancellation, disconnect and deletion remove staged candidate material; this is not a retained cleanup aggregate or retry protocol.
- UI remains preserved in stash `141645cd7b3870583b8e66ef12a1e2cb5f047481`. Product setup-to-Worker/browser E2E and current-row MCP/Runtime implementation still belong to phase 3. No merge or deployment was performed.

The independent review found one rollback data-loss issue: unconditional schema downgrade could discard local active/review credentials. Root restored a guard against local credential presence only, with no dependency on provider revocation success. Three real PostgreSQL cases prove active and reviewed credentials survive refused rollback, fail-open local disconnect permits rollback even after provider failure, and pending setup without a known token does not block rollback. Root reran whole-subproject quality checks and the related suite: **149 passed**, 14.28 seconds. The prior whole-backend result predates this narrow migration-only correction; affected migration/lifecycle/API evidence was rerun afterward. The same reviewer completed targeted re-review and closed the finding with no residual issues. All revised phase-1 review findings are resolved.
