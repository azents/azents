---
title: "GPT Apply-Patch Function Tool Implementation Plan"
created: 2026-07-20
updated: 2026-07-20
tags: [plan, backend, engine, runtime, tools, testing]
---

# GPT Apply-Patch Function Tool Implementation Plan

## Feature Summary

Implement the GPT-only V4A `apply_patch` function tool defined by
[`gpt-apply-patch-function-tool.md`](./gpt-apply-patch-function-tool.md) and
[ADR-0172](../adr/0172-gpt-apply-patch-alongside-existing-edit.md).

The tool remains an ordinary completed JSON-schema function call. Runtime Runner owns one typed
`file.apply_patch` operation that parses, preflights, stages, revalidates, and commits the patch.
The existing `edit` schema and behavior remain unchanged. Multi-file commit is not transactional:
pre-commit failures mutate nothing, while a commit-phase failure retains and reports the committed
prefix without rollback.

## Stack Prefix

`GPT apply-patch`

## PR Boundaries

1. `GPT apply-patch [1/8]: Design`
2. `GPT apply-patch [2/8]: Implementation plan`
3. `GPT apply-patch [3/8]: Runtime protocol contracts`
4. `GPT apply-patch [4/8]: Runner parser and executor`
5. `GPT apply-patch [5/8]: Engine tool integration`
6. `GPT apply-patch [6/8]: E2E validation and fixes`
7. `GPT apply-patch [7/8]: Spec promotion`
8. `GPT apply-patch [8/8]: Plan cleanup`

Each branch is based on the preceding branch. Create the complete stack before waiting on CI. Do not
merge any PR without explicit approval.

## Phase 1 — Design

- Record the stable product and architecture decisions in ADR-0172.
- Define the strict V4A subset, exact matching, path confinement, optimistic revalidation, commit
  ordering, partial-failure contract, GPT-only exposure, cancellation requirements, and test matrix.

Completion criteria:

- The ADR and design contain no unresolved product decisions.
- The documentation index and documentation validation pass.

## Phase 2 — Implementation Plan

- Record this stack, dependency order, validation matrix, prerequisite support, spec candidates,
  rollout constraints, and cleanup requirements.
- Keep implementation details at behavioral and contract boundaries rather than duplicating a
  file-by-file task list.

Completion criteria:

- Every design responsibility has one owning implementation or validation phase.
- Later phases can be reviewed independently without changing the accepted contract.

## Phase 3 — Runtime Protocol Contracts

- Add a typed `file.apply_patch` Runner operation request with absolute `base_path`, patch byte count,
  and protocol/schema version.
- Carry the UTF-8 patch through the existing bounded Runner body stream.
- Add typed ordered applied-change records for add, update, and delete actions.
- Add typed success output with line deltas and resulting content hashes for add/update.
- Add typed failure detail containing phase, stable reason, applied changes, failed operation,
  not-attempted operations, and exactness.
- Preserve failure detail through Runtime Control operation folding and the Python client exception.
- Regenerate protobuf modules with the repository generator; do not edit generated modules manually.

Completion criteria:

- Request, success, and failure payloads round-trip through protobuf and client contract tests.
- Existing Runner operations retain their wire fields and behavior.
- Ruff, Pyright, and runtime-control tests pass.

Dependency: Phase 2.

## Phase 4 — Runtime Runner Parser and Executor

- Implement a bounded strict V4A parser for Add, Update, and Delete operations.
- Build immutable patch-plan types and enforce one operation per relative path.
- Implement exact and unique logical-line matching, anchors, ordered non-overlapping hunks, EOF
  assertions, LF/CRLF handling, and final-newline preservation.
- Confine paths below canonical `base_path`; reject absolute paths, lexical parent traversal,
  escaping symlink parents, final symlinks, unsupported file kinds, invalid UTF-8, binary content,
  mixed newlines, and destructive precondition failures.
- Enforce patch, path, operation, hunk, per-file, aggregate-byte, and deadline limits before mutation.
- Preflight all operations, stage add/update payloads, capture hashes and metadata, and revalidate all
  observations before commit.
- Serialize patch operations per Runtime while retaining optimistic checks against external writers.
- Commit add/update operations in patch order, then deletes in patch order. Revalidate before each
  operation and stop on the first failure.
- Use atomic per-path publication where supported. Preserve committed paths after later failure and
  clean only uncommitted staging files.
- Emit exact typed success or failure detail without logging patch/source/replacement content.
- Add a test-only fault-injection boundary for deterministic stage and commit failures.

Completion criteria:

- Parser fixtures cover accepted grammar and every malformed boundary.
- Executor tests cover exact matching, ambiguity, missing context, newline behavior, path safety,
  resource limits, concurrency, cleanup, deterministic ordering, and exact partial commit reporting.
- Every parse, preflight, stage, or pre-commit revalidation failure leaves the patch target unchanged.
- A later commit failure leaves the committed prefix and reports it as a failed operation result.
- Runner Ruff, Pyright, and Pytest pass.

Dependency: Phase 3.

## Phase 5 — Engine Tool Integration

- Add `apply_patch({base_path, patch})` as an ordinary `FunctionTool` with
  `additionalProperties: false`.
- Add a normalized client-tool compatibility profile for identified OpenAI GPT-family models.
  Determine eligibility from existing developer/family metadata, not provider hosting or raw model
  substring checks inside the tool.
- Prepare the executable catalog, GPT-only prompt fragment, and declaration budget together.
- Keep `edit` unchanged and visible to all supported models.
- Invoke the typed Runtime Runner operation with the invoking Session owner and bounded deadline.
- Render concise model-visible success and actionable failure text. Preserve typed generic metadata on
  `client_tool_result`; never repeat the raw patch or file contents.
- Map pre-commit cancellation to a no-change cancelled result. Once Runner commit begins, settle the
  bounded operation to its typed terminal result before finalizing the tool call.
- Preserve deterministic call/result identity across User Stop, stream interruption, reconnect, and
  model switches.
- Update every supported lowerer/catalog preparation test affected by Engine-level tool visibility.

Completion criteria:

- GPT profiles receive both `apply_patch` and `edit`; Claude, Gemini, and non-GPT profiles do not
  receive `apply_patch`.
- Tool-call admission remains completed-function-call-only and PostgreSQL remains authoritative.
- Success, preflight failure, exact partial failure, timeout, cancellation, and reconnect results
  produce one durable terminal `client_tool_result` and clear `active_tool_calls`.
- Backend Ruff, Pyright, and targeted Pytest pass.

Dependency: Phase 4.

## Phase 6 — E2E Validation and Fixes

- Add deterministic Azents E2E coverage using a real Runtime Runner and fixture model calls that emit
  complete `apply_patch` function arguments.
- Add portable workspace fixtures for repeated context, empty files, LF/CRLF, missing files, path
  escape, symlinks, multi-operation patches, and fault-injected commit failure.
- Verify durable call/result events, live/history consistency, active-call cleanup, terminal Run state,
  and final filesystem manifests.
- Validate model switching after historical patch calls.
- Run the full required test matrix and fix implementation drift in this PR or the responsible earlier
  phase, rebasing later branches when needed.
- Record commands, environment, deterministic evidence, fixture prerequisites, failures, and fixes in
  a validation report.
- Compare implementation against the current execution-loop and Runtime Control specs and record the
  exact promotion changes needed in Phase 7.

Completion criteria:

- The required deterministic E2E matrix passes without provider credentials.
- Optional OpenAI API-key and ChatGPT OAuth live evaluations record a skip reason when credentials are
  absent; configured live runs fail on provider or assertion errors.
- No scenario applies a patch outside `base_path` or reports a partial commit as success.
- Relevant Python quality checks and E2E tests pass.

Dependency: Phase 5.

## Phase 7 — Spec Promotion

- Run the spec review workflow against the complete implementation and validation diff.
- Update `agent-execution-loop.md` with GPT-only prepared tool exposure, ordinary completed function
  admission, partial-failure result metadata, and commit-sensitive cancellation settlement.
- Update `agent-runtime-control.md` with `file.apply_patch`, typed terminal results, limits, path/file
  semantics, staging/revalidation, deterministic commit ordering, and no-rollback partial failure.
- Update spec `code_paths`, `last_verified_at`, version, and changelog entries.
- Mark the feature design implemented only after required deterministic validation succeeds.
- Do not modify adopted ADR-0172; add a new ADR only if implementation requires a different durable
  decision.

Completion criteria:

- Specs describe the verified implementation rather than planned behavior.
- Spec review finds no remaining apply-patch drift.
- Documentation validation and indexes pass.

Dependency: Phase 6.

## Phase 8 — Plan Cleanup

- Remove this temporary implementation plan after implementation, validation, and spec promotion are
  complete.
- Remove only stale plan references. Do not mix behavior changes, refactors, or new requirements into
  this PR.
- Preserve ADR-0172, the implemented design, living specs, validation evidence, and production code as
  the source-of-truth set.

Completion criteria:

- No current documentation depends on this temporary plan.
- Documentation validation and the complete stacked CI suite pass.

Dependency: Phase 7.

## Validation Matrix

| Behavior | Primary validation | Supporting validation |
|---|---|---|
| GPT-only declaration | Deterministic E2E catalog snapshot | Engine profile/lowerer unit tests |
| Existing `edit` unchanged | Cross-model E2E tool catalog | Existing edit schema/behavior tests |
| Add/update/delete success | Real-Runner multi-file E2E | Parser and executor fixtures |
| Multiple ordered hunks | Real-Runner filesystem manifest | Exact matcher unit tests |
| Ambiguous or missing context | Failed E2E result with unchanged manifest | Matcher diagnostics tests |
| LF, CRLF, and final newline | Portable Runner fixtures | Text representation unit tests |
| Path escape and symlinks | Failed E2E result with unchanged manifest | Path-policy executor tests |
| Existing Add destination | Failed E2E result with no overwrite | Precondition unit tests |
| Pre-commit concurrent change | Failed E2E result with no patch mutation | Revalidation unit tests |
| Later commit failure | Failed E2E result with committed prefix | Fault-injected executor test |
| Stop before commit | E2E no-change terminal result | Cancellation contract test |
| Stop after commit begins | E2E waits for typed terminal result | Engine settlement test |
| Model switch after history | GPT-to-non-GPT E2E | Cross-lowerer history test |
| Resource limits | Failed operation with no mutation | Boundary tests per limit |
| Privacy | E2E/log capture excludes patch and contents | Structured logging tests |

## Fixture and Prerequisite Support

Required deterministic support:

- A fixture adapter that emits completed `apply_patch` function calls.
- GPT-family and non-GPT model snapshots using the same normalized compatibility registry as
  production.
- A real Runtime Runner workspace with portable before/patch/after manifests.
- Test-only Runner fault injection that can fail staging, the first commit, or a selected later
  commit. Production configuration must not expose this capability.
- Durable event and active-tool-call assertions.

No credential snapshot is required for the required matrix. Optional live verification needs an
explicit OpenAI API key or ChatGPT OAuth credential and must redact tokens, raw provider payloads,
patch text, and source contents from evidence.

## Known Blockers and External Actions

- Local E2E may be unavailable when the development environment cannot start the configured Runtime
  provider. Record the exact environment failure and rely on required CI rather than replacing E2E
  with unit tests.
- Some filesystems may not support an atomic no-overwrite Add publication primitive. The executor must
  fail before commit on those filesystems rather than weaken the contract.
- Live model evaluation is optional and credential-dependent. Missing credentials are not a blocker
  for deterministic implementation or required CI.

## Spec Impact Candidates

- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/agent-runtime-control.md`

Promote only after the deterministic validation phase confirms actual behavior.

## Rollout and Cleanup

- Land protocol and Runner support before the tool becomes model-visible.
- Enable exposure only through the reviewed GPT-family compatibility profile.
- Roll back by removing the tool from that prepared catalog profile; retain historical durable calls
  and results as transcript data.
- Monitor exposure count, operation sizes, phase/reason outcomes, duration, partial-commit counts, and
  exactness without logging patch or file contents.
- Delete this plan in Phase 8 once living specs describe the validated behavior.
