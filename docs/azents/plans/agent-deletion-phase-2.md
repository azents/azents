---
title: "Agent Deletion Phase 2: Status and Read-only Admission"
created: 2026-10-20
tags: [agent, lifecycle, backend, frontend, testing]
---

# Phase Execution Plan

- Phase: 2 of 4, deleting/error presentation and authoritative read-only behavior.
- Branch/base: `feat/agent-deletion-readonly` → `feat/agent-deletion-participants` (#2359).
- Inputs: approved `harbor-261020` Design revision 2, phase-1 contracts and registry.
- Approved mechanisms: M10–M12, composed with M2/M4/M6/M7; authority REQ8/9 and ADR-D4.
- Design delta: None.
- PR boundary: safe public deletion summary; one nullable internal failure attribution field; lifecycle mutation guard; localized desktop/mobile read-only presentation.
- Non-goals: new checkpoint ledger/versioning, manual retry/cancel/force-delete controls, changed retention/backoff, raw error disclosure, comprehensive phase-3 matrices or new E2E tests.
- Removal: claim-time error clearing; expected-wait exceptions; enabled-only deletion labels; mutating controls that ignore deletion; user-scoped final writes without atomic active-Agent admission.

| Workstream | Owner | Paths/interfaces | Depends on | Validation |
| --- | --- | --- | --- | --- |
| Failure evidence and waits | /root | job ORM/repository, core deletion results, participant/scheduler contracts, generated Alembic revision | Phase 1 | migration/DDL, latch/reclaim/recovery/wait tests, whole-backend types |
| Public projection | /root | Agent service/repo/API data, generated OpenAPI/public clients | Job evidence | authorized batched list/detail, no diagnostic leaks, fresh client generation |
| Server read-only admission | /root | shared active-Agent repository guard and API exception mapping; owning operations for settings/admin/avatar, memory/projects/environment, toolkits/OAuth, uploads and Runtime work | Canonical Agent lifecycle | direct/stale mutation and commit races; preserve permission and native cleanup boundaries |
| UI | /root | Agent list and shared headers, Agent settings/workspace/chat containers and mutation controls, locale messages | Generated deletion_status | component states, accessibility/mobile, TypeScript lint/types; inspection navigation retained |
| Current contracts | /root | relevant Agent/deletion specs | Verified behavior | schema ownership field documentation, docs validator |

Guard integration is an explicit owning-operation inventory, not middleware or a public bypass flag. Complete durable writes recheck active lifecycle in their transaction; external upload/OAuth stages recheck before attachment. Reads that currently reconcile mutable Agent settings must not bypass read-only admission. Existing cleanup/safety stops and shared owners retain their native explicit operations.

Integration order: schema/domain failure evidence → owned recovery/wait scheduling → safe batch status projection → mutation-family guard inventory → generated clients → UI controls/locales → baseline focused verification/spec. Validate first-unresolved and unknown-legacy error handling exactly; clearing a known boundary clears diagnostics atomically. Missing-job error copy makes no unsupported retry promise.

Independent reviewer: `/root/deletion-fix-review`, requested by root only after integrated stable validation. Root applies corrections. Final checks: backend Ruff/ty/pytest/migrations, generated clients, TypeScript formatting/lint/typecheck and relevant component tests, docs and hooks, latest-SHA CI. Context checkpoint records protected families, proof gaps, commands/results, removals, review and PR before phase 3 starts.

## Integrated checkpoint

Phase 1 (#2359) is open with successful required CI; no merge or deployment was performed.
Phase 2 implementation is integrated, validated and approved by the assigned independent
reviewer. Its commit and PR are the next boundary; phase 3 has not started.

Implemented scope:

- Nullable failure attribution, preserved claims, typed expected waits, exact-boundary recovery,
  safe batched Agent status projection, and generated OpenAPI/Python/TypeScript public clients.
- Transaction-bound guards for settings/admin/avatar, memory edits, automatic Project policy,
  catalog mutation groups, Agent environment and Workspace-variable selections, owned/shared
  Toolkit mutations, personal allowlist additions, GitHub/Google publication, Exchange upload
  publication, Runtime addition/removal confirmation, non-stop commands and Runtime Web writes.
- Root Session creation and user title/pin/goal/archive/restore/model/input mutations, Routine
  definitions, Scheduled Task management/provider controls, Session Project registration/removal,
  external-channel Agent routes/defaults/bindings/access decisions. Routine mutation now uses
  a lock that conflicts with lifecycle updates rather than PostgreSQL KEY SHARE. Native
  cleanup/reconciliation and explicit Session Stop remain separate from new-work guards.
- Workspace Runtime-work admission is a completed database operation separate from inspection.
  Workspace upload authorization rechecks lifecycle under the parent lock before native
  coordinator work. Terminal/Browser retain their native per-request lifecycle/generation
  denial and do not restore deleting resources for inspection.
- Localized status badges/notices in cards, focused/sidebar rows and desktop/mobile headers;
  per-control readonly behavior across settings, Toolkit, memory, environment, Projects,
  Scheduled Tasks, channel controls, chat input/retry/goal controls and workspace file actions.
  Search, paging, details, links, navigation and safety Stop remain available where native
  authority permits them. No manual recovery action was added.
- Bounded foreground polling, focus revalidation, final-404 directory navigation, safe tRPC
  conflict projection and cache invalidation. Stale server hydration preserves already-known
  deletion evidence; it cannot restore editability while an invalidation is pending.

Verification evidence: integrated related backend suite 1,909 passed, including the real
PostgreSQL blocking-writer race, latch/legacy failure behavior, native cleanup regressions,
OAuth/upload/Toolkit and channel paths. Migration single-head/model-DDL checks: 2 passed.
Whole-backend Ruff/format/ty and public client generation passed. Web typecheck and 759 node
checks passed, including stale deletion-cache hydration. Selected CI-contract component
stories: 42 passed across 9 files; other supplied story files were excluded by the existing
CI tag policy, not executed. Exhaustive state/family matrices and representative full product
E2E remain the approved phase-3/4 work, not claimed by this phase.

Component validation uses a secure SWC cache under `/home/agent` in this Runtime because
`/tmp` and the shared workspace have untrusted writable ancestors for SWC's validator.
Shared directory permissions and dependency versions were not changed. Final validation
logs and the exact review result are recorded in the Session checkpoint before publishing.

## Independent review corrections

The assigned reviewer reported three warnings on the frozen phase-2 diff: missing Single App
configuration/validation publication fences, stale Session directory mutation controls, and
Terminal/Browser panels lacking explicit read-only input admission. Root corrected all three:

- Single App config/policy transactions now acquire the Agent fence before child locks. Slack
  validation and Discord activation check the persisted Single App route before external work
  and before final health/callback publication; shared Multi Apps and native callback cleanup/
  Gateway operations keep their own authority. PostgreSQL tests cover deletion rejection and
  the shared-Multi exception.
- The Session directory consumes live lifecycle state, disables all mutation actions, and
  closes mutation modals while retaining tabs, paging and Session navigation.
- Terminal/Browser hooks suppress new tickets, attachment/reconnect and input after read-only
  observation, including checks after asynchronous ticket issuance. Existing output and local
  navigation remain inspectable; Terminal termination on an existing connection stays native.
  Their panels expose disabled mutation controls and have explicit CI-contract stories.

Affected correction suites passed: 132 backend checks and three focused component stories.
The complete backend run initially found 31 fixture/old-contract failures (13,316 passed);
root updated explicit SQL/hook test boundaries and replaced the old unlocked Project-write
expectation with preserved unlocked reads plus fenced writes. The next full run exposed
one stale Multi App query double; its synchronous row result was corrected.

The targeted re-review confirmed those corrections and found one provisional Discord
callback cleanup gap after final publication denial. Root preserved the existing exact
credential/generation/selector cleanup before re-raising the lifecycle conflict. Both
missing-target and decommissioning denials have regression coverage; the related 36
backend tests passed. The reviewer then confirmed every finding resolved on the final
integrated production diff.

Final validation: full backend `uv run pytest src -q` passed with 13,351 passed,
3 skipped and 8 warnings in 348.58 seconds. Ruff, formatting (2,672 files) and
`ty check --error-on-warning` passed. Web lint (6 tasks), typecheck (8 tasks),
759 node tests, the 42 baseline plus 3 correction component stories, and the
production build (3 tasks) passed. Remaining phase-3 matrices and phase-4 E2E
are not implied by these results. No Design delta or new external authority was added.
