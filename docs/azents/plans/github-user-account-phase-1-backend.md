---
title: "GitHub User Account Toolkit Phase 1 Backend"
created: 2026-10-08
tags: [github, toolkit, backend, security]
---

# Phase Execution Plan

- Phase: 1/3 backend authorization and cleanup contracts.
- Branch/base: `feat/github-user-261008-backend` -> `main` at `e9f8ff027`; approved research baseline remains `279db5f1f`.
- PR boundary: complete backend setup/persistence/Public contracts; new user methods are not offered by the UI until phase 2 and execution is enabled in phase 3.
- Inputs: confirmed REQ-1..13, ADR-D1..D3, approved Design revision 3.
- Deliverables: distinct user registration, bound one-use attempts, non-expiring envelope validation, staged activation/account identity, paginated personal/multi-org observations, exact-token revocation and encrypted failure/retry, redacted availability/connection summaries, additive migration and focused tests.
- Non-goals: UI overhaul, refresh/proxy/hub/actor, live provider setup, merge/deployment.
- Interfaces: detached provider/repository DTOs; exact requester/context/current-registration publication; Workspace and exact-Agent ownership-symmetric endpoints; only encrypted persistent token material.
- Approved Design mechanisms: M1-M5, M7, M9-M11; backend contracts for M8.
- Authority: `github-261008/REQ-1..13`, `ADR-D1..D3`, `DESIGN`; current Toolkit/System Settings contracts.
- Design delta: None.
- Removal obligations: extend auth discriminator/serializers rather than replace old variants; keep temporary installation cleanup separate from strict user cleanup; new user modes must not fall through old installation issuance.
- Absence verification: exhaustive branches, old-mode regressions, no user expiry/refresh state or provider-grant deletion.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| SDK provider | `/root/github-user-provider` | new core provider module + provider tests | fixed Design | typed non-expiring exchange, account/access/revocation | MockTransport assertions |
| Persistence | `/root/github-user-persistence` | new core domain DTO/model/repository + migration/tests | existing authority/encryption | short completed atomic attempt/publication/retirement operations | repository/migration/race tests |
| Service/routes | `/root/github-user-service` | new service/routes/tests | agreed provider/repo DTOs | ownership-gated orchestration with no HTTP in transaction | service/route tests |
| Existing integration | `/root` | core config/credential union, Toolkit mapping/mutation and route registration | owner outputs | old-mode-compatible API integration | integrated lint/type/tests |
| Parent-deletion safety | `/root/github-user-provider` (after SDK completion) | new parent guards and exact Agent/Workspace deletion paths/tests | completed persistence models | actionable rejection rather than FK cascade loss/500 while cleanup incomplete | PostgreSQL and parent route tests |

- Integration order: domain contracts and SDK -> operations/service -> existing contract/serializer/mutation integration -> root checks -> frozen complete diff -> reviewer -> fixes -> commit/PR.
- Independent review: `/root/github-user-reviewer`, root request only after the phase is stable.
- Final validation: root-owned Ruff/configured typecheck/backend targeted suite/docs checks; inspect migration chain; public schema import/generation compatibility.
- Scope-drift check: all listed phase deliverables and M11 failure/retry must exist; no later UI/runtime activation, new authority or unrelated changes.
- Context checkpoint: backend contracts, provider adapter, encrypted setup/connection/cleanup, exact-token revocation, Public routes/summaries, and parent-deletion protection implemented. User execution remains explicitly unavailable until phase 3. Main synchronization preserved visibility-scope removal and advanced the new generated migration's parent to `7b6d0eb501fb`; no obsolete scopes restored. Root final post-sync related suite passed 241 tests, including already-invalid-token verification and deletion failure ordering; full-subproject Ruff/format/typecheck passed. OpenAPI and Python/TypeScript Public clients are source-generated and direct Public-client TypeScript compilation passed. The single stable-diff review found two lifecycle corrections. Root implemented current-row mutation guards and application-owned completion of already-admitted exchange/capture; 173 affected tests and full-subproject Ruff/format/typecheck passed after those corrections. Initial whole-backend evidence before review corrections was 11,770 passed / 3 skipped; it is not presented as a rerun of the corrected diff. Targeted same-reviewer re-review, commit and PR remain before phase 2.

## Integration Details Within Approved Mechanisms

- A reload-safe BYOA edit bag retains omitted identity/write-only fields only from the same saved user registration. New App/client identity prevents incompatible secret inheritance; fresh registration still needs all required values. No additional public secret projection.
- Captured retired-token cleanup can verify an already-invalid token via supported GitHub REST `GET /user`; only structured REST 401 is evidence. Generic deletion 403/404/422 or missing/wrong client secret is never treated as success by itself.
- OAuth request-validation errors omit transient code/state/token values. Received tokens are encrypted before identity work; cancellation then late identity cannot reactivate or duplicate cleanup.
- Agent deletion blocks only its owned user Toolkits until cleanup; shared attachments are not disconnected. Toolkit-before-Agent lock order is retained. No Workspace deletion API exists and none is added.
- Explicit unknown initial-exchange results cannot be claimed revoked. No shutdown revocation side effect, scheduler, token epoch or credential hub is introduced.
- Current GitHub mutation/deletion guards lock and reread the Toolkit before deciding from its current mode and registration, including stale PAT/installation snapshots. Real PostgreSQL shared/owned update/delete witnesses preserve newly active user credentials.
- The existing application resource context strongly owns the already-admitted exchange/capture sequence. Request cancellation sets only a transient detached marker and immediately rethrows; the owned sequence durably captures and retires/revokes any received token. Application pre-close drains this existing work before DB resources close. No independent scheduling or automatic activation occurs.
- Cancellation before receipt, after receipt before DB capture, around result delivery, and with cleanup failure have explicit event/PostgreSQL witnesses. Expiry alone never permits teardown while capture can still be running. Hard process death with no durable receipt remains honestly incomplete; no exactly-once or forced time-bounded physical deletion guarantee is made.
