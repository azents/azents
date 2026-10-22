---
title: "Google Direct Workspace Tools Verification"
created: 2026-10-22
document_role: supporting
document_type: supporting-verification
tags: [google, toolkit, oauth, verification, testenv]
---

# Verification Boundary

This supporting report records implementation verification of
[google-261021/REQ](../requirements/google-261021-direct-workspace-tools.md),
[ADR](../adr/google-261021-direct-workspace-tools.md) and the approved
[Design](google-261021-direct-workspace-tools.md), mechanisms M1–M13.
Design delta: None. It is evidence, not new product or design authority.

The final verification branch starts from Phase 3
`a56ac5311a0a698704a680305ac5f20c6cc344b2`. Its production source and generated
API contracts are unchanged; this phase replaces obsolete integration fixtures,
adds representative assembled tests, promotes current Specs and retires shipping
plans. The sole read-only reviewer is `/root/google-direct-reviewer`.
The final 17-file integrated phase review returned no concrete correctness,
security, authorization, data-integrity or authority findings. Remote stack CI
remains a separate outstanding gate; the review authorizes no external action.

## Prerequisites and Isolation

Root executed the repository E2E tests with Python 3.14, disposable Docker
PostgreSQL/API/Worker/Runtime Control/Docker Provider/Runner deployments and
content-matched Web/Admin images with Selenium Chromium. One assembled stack ran
at a time. No managed development environment, external credentials or product-DB
writes were used for scenario preparation.

Synthetic OAuth, signed OIDC, Workspace REST and Picker peers use fixed official
hosts inside that test network and ephemeral TLS/signing material. Product SDKs,
URLs, current authorization and response decoding are not replaced. The fixture
records operation names, effects and byte counts, not bearer values, bodies or
credential-bearing URLs. The browser peer implements only the documented Picker
builder/callback contract; it is not the live Google browser SDK.

## Root-Run Local Evidence

From `testenv/azents/e2e`:

- `uv run ruff check .`, `uv run ruff format --check .` and
  `uv run ty check --error-on-warning`: passed.
- `uv run pytest src/support_tests`: **1,492 passed**, 17 warnings, 23.15 s.
  These are Docker-free in-process tests; no sockets/browser were introduced.
- `uv run pytest src/tests/required/public/test_google_connection.py -xvv`:
  **5 passed**, 4 warnings, 65.15 s.
- `uv run pytest src/tests/web/public/test_google_connection.py -xvv`:
  **3 passed**, 4 warnings, 167.24 s including disposable-stack preparation.
- Final combined Google browser suite plus
  `test_runtime_capability_web.py::test_runtime_free_add_and_remove_progress`:
  **4 passed**, 4 warnings, 108.07 s. A second fresh focused Runtime deployment
  passed independently in **89.70 s** with the same source.
- Both TypeScript client generators ran twice against the current OpenAPI
  sources: all **32 generated TypeScript files** were byte-identical on the
  second generation. The earlier manifest's API/Python entries remain identical;
  ignored TypeScript output was freshly generated in this worktree.
- `python scripts/docs_catalog.py validate` and `git diff --check`: passed.

The initial Phase 4 pass reused Phase 3's unchanged production-source evidence:
**14,046 backend tests**, **799 Web tests**, **135 Admin tests**, **29 Chromium
component cases**, both production builds and source generation. The subsequent
fixed CI repeat exposed a shared root-creation backend defect described below.
That foundation correction intentionally changes common backend source; the prior
backend and remote green results cannot substitute for fresh assembled-stack
validation. The Google API and frontend components themselves remain unchanged.

### Observed Product Outcomes

- Operator preparation hides only Google when incomplete and does not claim live
  verification or Picker readiness. Unrelated providers remain in the catalog.
- Partial actual grants remain separate from request intent. Unpublished review
  creates no Toolkit. Exact confirmation is idempotent. Reconnect cancellation,
  replacement, historical noncurrent outcomes and local disconnect are observed
  through public APIs.
- The actual Worker/SDK Calendar read renews an expiring credential. The ungranted
  Calendar write is unavailable and never reaches the peer.
- Shared Team and personal User Session sources independently execute an allowed
  Calendar event creation, Gmail message read/send, Gmail filter creation, Drive
  download and Drive creation. Each journey records exactly four provider effects:
  `calendar.create_event`, `gmail.send_message`, `gmail.create_filter`,
  `drive.create_file`. A known non-app file is denied under `drive.file`; this
  resource denial does not revoke the current grant.
- Downloaded bytes become an ordinary authorized Artifact, are imported through
  the real transfer coordinator/Runner, and are uploaded from an authorized Runtime
  path using the official resumable SDK path. Upload SHA-256 equals the original
  **22-byte** fixture content. No Worker-local path or provider URL is accepted as
  the source.
- Personal management issues a minimal Picker token with both noncacheable response
  headers. The credential does not enter Worker results or saved projections.
  Revision-fenced local all-off preserves the connection and defeats a stale
  Picker issuance request.
- Real browser shared and Agent-owned setup keeps the same window, scrubs callback
  query values, stages partial review, explicitly publishes and preserves metadata
  and the independently confirmed timeout through reconnect.
- The deployed browser Picker loader obtains the manager-only credential from the
  real API, loads the fixed-host synthetic peer, selects/cancels, disposes the
  chooser and cleans up on navigation. The main connection projection is unchanged;
  neither credentials nor selected IDs enter browser persistent storage.

Permission/owner/refresh-CAS races, compound prerequisites, Calendar event/status
and recurrence matrices, Gmail MIME/header/filter semantics, Drive conversion/
shortcut/permission boundaries, parser budgets and migration corruption/preservation
matrices remain in their narrower backend/component tests. The assembled flows are
representative process/network/Runner/browser verification, not a duplicate of
all pure operation matrices.

### Failures Corrected During Verification

- Stale generated-client tests referenced removed `preview_verified` and task
  fields. Active tests now use service-access and canonical settings contracts.
- The old synthetic Google peer exposed only MCP routes and the model emitted
  empty Calendar arguments. It now receives the actual official SDK requests,
  including the resumable upload handshake and byte completion.
- In-process byte accounting mutated subclass state while the control projection
  read the shared Handler. Accounting now uses the shared state explicitly.
- Incremental Responses omit prior outputs. The deterministic model initially
  replayed its first Calendar write. Its progression now advances from exact
  previous-response identity, with two pure regressions; product write retry
  behavior was not changed or weakened.
- Browser assertions now match complete localized text. The disposable Picker
  peer uses a real modal dialog rather than page content that causes artificial
  scroll/header interception. Product layout and click handling were unchanged.
- PR #2372's retained CI screenshot/HTML shows a missing Reset confirmation after
  navigation while independently fetched metrics change the page above the
  lifecycle controls. The historical timeout did not reproduce in a fresh local
  run (95.13 s). The test now synchronizes on the actual ready metrics/chart before
  clicking Reset, rather than relying on API readiness as UI-layout readiness.
  Both subsequent fresh runs pass. This removes an ordering gap without claiming
  a definitive reconstruction of the historical browser event; product Runtime
  behavior, action submission, duration thresholds and retry policy are unchanged.

### Shared Root-Creation Correction from Fixed CI Repeat

Foundation CI run `39653017262` passed attempt 1 on `d12324401`; the prescribed
unchanged-SHA attempt 2 failed in Session Browser Team-primary setup with HTTP 500.
The preserved server trace identifies PostgreSQL `DeadlockDetected` in Runtime
insertion, not a Google provider or browser assertion failure. The canonical root
wrapper acquired Agent `FOR UPDATE` before Runtime acquisition, reversing the
existing Runtime-first repository/reconciliation order.

The foundation correction removes that preliminary lock while preserving inactive
Agent errors, Runtime-first acquisition, FK-compatible Runtime `KEY SHARE` and the
lower final ACTIVE/capability/version fence. Independent review also identified a
stale-authority gap between wrapper Project validation and lower authority capture.
After Project writes, both canonical created paths now revalidate the **original**
capability/version with the same lower fence. A removal or remove/re-enable ABA
transition rejects the transaction; existing-primary reuse remains unchanged.

Two deterministic real-PostgreSQL lock-order regressions cover non-primary and
Team-primary creation. Four additional cases cover both entrypoints under removal
and ABA; all four first reproduced stale acceptance, then passed with the original
snapshot fence. They exercise the production write-scope rollback and independently
verify no Session, Conversation, root/context or Project rows remain. The focused
repository suite passes **75 tests**; backend and E2E Ruff/format/strict ty and the
fresh previously failing browser journey (**84.97 s**) pass. The same sole reviewer
cleared the complete correction and Conversation Spec with no remaining findings.

Complete failed-run metadata and raw artifacts are preserved. Fresh whole-backend,
assembled Google and current-SHA stack CI evidence is required after propagation,
including two successful complete Linux foundation attempts on one unchanged SHA.
No application retry, fixed sleep, timeout/gate relaxation or manual success status
was introduced. [Conversation](../spec/domain/conversation.md) records the current
lock-order and original-authority contract; immutable feature authority is unchanged.

### Duration-Gate Test-Setup Correction

Execution CI `39667450452` passed its functional workflow on `994ef039b`, but the
trusted asynchronous comparison reported **471.17 s** against a **434.96 s** limit.
All 365 Required testcase IDs and lane assignments matched the foundation sample;
CPU-pressure and runner differences prevent attributing the timing change to Google
product code. The failed duration verdict and complete artifacts remain preserved.

The critical lane included five xAI image-generation provider/storage journeys that
created and started unused Docker Runtimes. Their actual assertions use API, Worker,
provider/OAuth, Exchange and ModelFile storage, not Runner. The execution-phase
correction explicitly creates Runtime-free Agents and verifies that capability,
retaining all five testcase IDs and all 35 original assertions. Separate Runtime
lifecycle/recreation and canonical Runner transfer coverage is unchanged.

Same-host fresh-stack runs pass all five cases before and twice after the change.
Call sums are **27.590817 s** before, **9.819407 s** and **9.877810 s** after. These
are local mechanism observations, not a causal whole-CI speed claim. E2E static
checks and **1,490 support tests** pass. The same sole reviewer cleared the one-file
setup change with no Spec impact. Final acceptance still requires two complete
successful unchanged-SHA execution CI attempts and fresh downstream rollups; no
product code, gate, timeout, retry, scheduling or runner count was changed.

## Removal and Spec Promotion

The active-source audit covers backend, Web/Admin, generated contracts, E2E and
current Specs. Google-only MCP execution/schema discovery, task ceilings,
security acknowledgement and scanner behavior are replaced. Frozen predecessor
values remain only in the one-time data migration and its preservation tests;
generic MCP, GCP remote MCP and unrelated providers remain intact.

Current behavior is consolidated in [Google Connection](../spec/domain/google-connection.md),
[Toolkit](../spec/domain/toolkit.md) and
[System Settings](../spec/domain/system-settings.md). Requirements, ADR and the
approved Design remain the historical authority; shipping plans are temporary.

## Remote and External Limits

Local success does **not** mean the stack's remote CI is green. PRs
[#2372](https://github.com/azents/azents/pull/2372),
[#2374](https://github.com/azents/azents/pull/2374),
[#2375](https://github.com/azents/azents/pull/2375) and
[#2376](https://github.com/azents/azents/pull/2376) require fresh final current-SHA
functional, migration, support, assembled E2E, build, duration and asynchronous
rollup verification after the shared foundation correction. Final evidence belongs in
the PR checks and the completion report, not a manually overwritten success status.

No live Google OAuth or Picker, real-account ACLs, quota/load test, actual restricted-
scope review, security/compliance certification or Google format-conversion
interoperability was performed. These remain separately authorized prerequisites.
No operational migration, merge, deployment or release was performed.
