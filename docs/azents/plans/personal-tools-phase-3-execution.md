---
title: "Personal Tools Phase 3: User-root Execution and Current Admission"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, implementation, engine, runtime, security]
---

# Phase Execution Plan

> Historical revision 1 execution record. Its User-global candidate assumptions
> and validation are superseded by approved Design revision 2 and the
> [Workspace execution correction plan](personal-tools-workspace-execution-correction.md).
> Prior evidence is not corrected same-User cross-Workspace acceptance.

- Phase: 3/4, User-root execution and source identity.
- Branch/base: `feat/personal-tools-execution-261017` ->
  `feat/personal-tools-management-261017` at `4110594de`; depends on
  [Phase 2 PR #2317](https://github.com/azents/azents/pull/2317).
- PR boundary: canonical User-root personal effective sources, durable namespaces, current
  per-effect admission and Provider grant/discovery/refresh/Runtime-export integration. Existing
  shared, Agent-owned and automatic capabilities retain their authority and relative ordering.
- Inputs: confirmed [Requirements](../requirements/personaltools-261017-agent-access.md),
  accepted [ADR D1-D3](../adr/personaltools-261017-agent-access.md), approved
  [Design revision 1](../design/personaltools-261017-agent-access.md) M1-M11; canonical ownership,
  policy, management and Provider lifecycle from Phases 1-2; existing durable User-root lineage,
  Session execution ownership, Toolkit lifecycle, grant CAS and namespace allocation.
- Deliverables: private roots and their subagents resolve only their associated active User's
  currently eligible personal sources; Team/missing/inconsistent roots resolve none. Personal
  invocation, authenticated discovery/refresh and new Runtime credential export repeat current
  owner/ordinary Agent access/enabled/policy/Provider admission. Already admitted effects may finish;
  later effects reject after withdrawal. Exact source/schema/executor and namespace identity remain
  stable without credential fallback. Existing management destinations reflect actual ownership.
- Non-goals: Web/tRPC forms, Agent access UI, composer navigation, final product E2E and Spec promotion,
  new Provider/auth options, schema or public API changes unless an existing source contract requires
  generation, deployment, merge, production migration, live credentials, new Runtime isolation,
  exported-token recall or in-flight remote cancellation.
- Interfaces: generic Run/Turn/Worker/Toolkit execution context remains Userless. Canonical Session
  identity alone resolves the durable associated root User at the narrow personal boundary. A
  source-bound admission handle may carry exactly that personal authority to protected effects;
  sender/viewer/requester/tool arguments cannot select it. Execution Workspace remains workload
  placement, never a surrogate personal owner. Current-grant comparisons and existing source revision
  remain authoritative. FunctionTool wire variants, cancellation behavior, and final executor pairing
  are preserved across lowerers and hooks. Provider I/O remains outside database transactions.
- Approved Design mechanisms: M5/M6/M7/M8/M11; consume M1/M2/M3/M4 without changing their contracts.
- Authority references: REQ-4/6/7/8/9; ADR-D1/D2/D3; Design sections 3.2, 5, 6.1-6.5, 9 and 10;
  current Conversation/Toolkit/MCP OAuth/Google/Runtime execution contracts and project rules.
- Design delta: None.
- Removal obligations: replace omission of personal effective-source ownership at its narrow
  User-root projection; replace prepared-source-only personal authority with current dispatch,
  authenticated discovery/refresh and later export admission. Preserve legitimate generic Userless
  context, shared queries, existing grants, retained namespaces and shared Runtime trust behavior.
- Absence verification: Team/foreign root and inconsistent lineage tests; prepare-withdraw-call and
  prepare-withdraw-export barriers; no Provider I/O on denial; old callback/refresh cannot restore
  access; current source identity mismatch never falls back; all wire/lowerer and shared regressions.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Canonical projection/admission | /root | personal core contracts, `repos/toolkit/personal_runtime*`, `repos/toolkit/data.py`, narrow Session/namespace adapters | Phases 1-2 | current canonical User-root sources, policy admission and allocation | real PostgreSQL lineage/access/policy/namespace races |
| Engine source and dispatch | /root | `repos/engine_resolve.py`, `repos/engine_read.py`, `engine/run/resolve.py`, Toolkit binding/lifecycle/catalog and `engine/events/tools.py` | canonical admission | exact source-bound final-handler guard without ambient User | source identity, hook routing, custom/function wires, cancellation and lowerer tests |
| Provider protected effects | /root | `core/tools.py`, common MCP/background transport helpers, configurable Provider adapters and MCP/GitHub/Google runtime grant repositories/services | bound admission | current admission before authenticated discovery/refresh/calls and grant publication | controlled Provider barriers, current-grant CAS, stale transport and shared regressions |
| Runtime export | /root | `engine/tools/builtin.py`, GitHub environment composition, peer Toolkit wiring | effective sources and Provider admission | current personal export check and unchanged deterministic merge | enabled/disabled export, mixed sources, withdrawal before later process, retained-process boundary |
| Integration evidence | /root | focused tests, phase/global plans and directly reachable Specs | stable integrated code | root validation and frozen same-reviewer checkpoint | Ruff/ty/full backend/docs/diff/hooks and PR CI |

- Integration order: inspect canonical Session/Agent authority and Provider effect boundaries ->
  source projection/current admission and namespace operations -> Engine effective-source/dispatch
  integration -> Provider discovery/refresh/current-grant integration -> Runtime export and exact
  management destinations -> deterministic cross-boundary tests -> root final integrated validation
  -> frozen read-only review -> root corrections/revalidation -> commit and Phase 3 PR.
- Independent review: `/root/personal-tools-reviewer`, the same fixed read-only one-way reviewer.
  Root requests review only after the complete integrated phase is stable and validated; root owns
  all corrections and affected reruns. Material boundary corrections receive targeted re-review.
- Final validation: backend Ruff check/format and configured ty; real PostgreSQL personal lineage,
  eligibility, namespace and withdrawal tests; controlled Provider token/discovery/refresh/effect
  barriers; Engine dispatch/hook/cancellation/schema-wire/lowerer/lifecycle tests; Runtime merge and
  later-export tests; complete backend regression, docs/diff/hooks and exact-commit PR CI. Migration
  evidence is reused only while the schema stays unchanged. No live-provider success is implied.
- Scope-drift check: no new ambient User, permission epoch/history, flag, fallback, relay, Runtime,
  personal-only Provider option restriction, remote rollback or isolation promise. No UI work in
  this phase. New material decisions return to authority/design; equivalent helper layout is local.
- Context checkpoint: Phase 1 PR #2316 remains open with verified successful CI. Phase 2 PR #2317
  is open at `4110594de`, clean worktree, normal push, four independent review findings corrected
  and cleared by the same reviewer. Root correction regression: 12886 backend tests passed,
  three existing Redis-specific skips; final personal API mapping is covered by 604 focused tests.
  Migration suite 50 passed; clients/ty/Ruff/docs/hooks passed. Phase 2 CI run `39022630805`
  completed successfully at `4110594de`; all PR checks have settled without failures. No merge,
  production migration, deployment or Web implementation has occurred. Root began this phase only
  after recording and reporting this plan.

## Integrated Implementation Checkpoint

- Canonical personal source projection reuses existing Session owner-generation and full lineage
  authority, reads only the durable User-root association and active User's ordinary Agent access,
  and allocates namespaces lazily through existing parent/Agent claim boundaries. Team/foreign
  roots, changed source and withdrawn policy do not obtain usable personal authority.
- Exact source-bound admission is carried explicitly, not as an ambient generic execution User.
  Engine catalog projection retains the final handler's admission across JSON/custom wires and
  model filtering. Cancellation cleanup remains independent of new effect admission.
- Existing enabled GitHub Runtime export checks current personal admission before credential
  acquisition; environment collection rechecks after the external credential gap. Disabled export
  obtains no credentials and does not gate unrelated Runtime work. Normal last-source-wins merge
  and redacted duplicate-key warning remain unchanged. Worker already refreshes peer Toolkit
  references after lifecycle reconciliation, so that mechanism is reused.
- Root partial-phase validation: 346 focused PostgreSQL, Engine catalog/projection/resolve/lifecycle,
  current invocation/export barrier, GitHub environment and Worker tests passed (three existing
  warnings, 25.20s). Backend Ruff/format (2557 files) and ty passed. These are controlled local
  boundaries, not complete Provider/runtime or product-E2E acceptance.
- Common MCP authorization and composed Notion/Sentry/GitHub/Google Toolkits now retain the same
  exact capability for authenticated discovery, refresh, cached requests and retry boundaries.
  Personal MCP grant loads and success/failure publication compose current parent admission with
  the existing dependent grant CAS. Google and GitHub user runtime adapters repeat canonical
  personal source admission while retaining current client/grant/task and exact failure checks.
- Platform GitHub installation tokens and caches recheck current User-global inventory and current
  operator App registration. AWS/GCP discovery and cached calls repeat checks around token work.
  Kubernetes rechecks lazy client/discovery gaps and cached-client reuse, cleaning up clients on
  denial. Native Google Analytics/Brave have no authenticated background preparation; their
  execution and SDK renewal begin inside the common catalog-admitted effect.
- Post-discovery snapshot publication now repeats exact parent admission in the same completed
  database operation as the write. Store Agent/Session identity must match the source. Shared
  snapshot operations remain unchanged; no personal snapshot can publish after withdrawal won.
- No configurable Provider currently publishes a VFS release source; the only resource root belongs
  to required auto-bound Scheduled Toolkit. Shared VFS selection still excludes personal rows.
  No configurable Provider consumes the workload Workspace handle for a management URL, so this
  phase has no incorrect ownership-dependent URL to replace; concrete personal UI destinations
  remain Phase 4. No public route/schema, migration or generated-client change is required here.
- Additional root validation: MCP/GitHub 125, Google 35, personal grants 15, cloud 106 focused tests
  passed. The first whole-backend regression passed 12945 tests with three existing skips before
  the final publication/native additions. Those additions passed 36 real-PostgreSQL focused tests,
  including discovery/preflight-write withdrawal, preserved snapshots, mismatched store identity,
  allowed publication and native lazy/cached-client cleanup. Ruff/format (2564 files) and ty passed.
- Final current-code whole-backend regression: 12963 passed, three existing skips and nine
  warnings in 363.09s. Two later test-only canonical archived-continuation cases are covered by
  the supplemental 33-test current-source/dispatch/publication/native run (all passed).
  The started archived continuation retains the same source/namespace; an admitted-only cycle
  cannot acquire it. No production code changed after the final full run began.
- The same fixed read-only reviewer verified the complete frozen diff and reported no actionable
  findings or material Design drift. No implementation corrections were required after review.
  Remaining: commit/hooks, Phase 3 PR and exact-commit CI. Live Provider interoperability and final
  product E2E are not claimed. Design delta: None.
