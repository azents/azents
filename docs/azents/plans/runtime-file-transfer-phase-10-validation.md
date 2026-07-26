---
title: "Runtime File Transfer phase 10: E2E and validation"
created: 2026-07-26
tags: [runtime, files, transfer, validation, e2e, testenv, security]
---

# Runtime File Transfer phase 10: E2E and validation

## Phase Execution Plan

- Phase: `10 — E2E and validation`
- Branch/base: `feature/runtime-file-transfer-10-validation` →
  `feature/runtime-file-transfer-09-deployment-cutover`
- PR boundary: Add deterministic large-file product E2E coverage and retain an exact,
  non-secret validation record. Correct only defects discovered by this validation.
- Inputs: Confirmed [`transfer-260725/REQ`](../requirements/transfer-260725-runtime-file-transfer.md);
  accepted [`transfer-260725/ADR`](../adr/transfer-260725-runtime-file-transfer.md);
  approved [`transfer-260725/DESIGN`](../design/transfer-260725-runtime-file-transfer.md);
  current living specs; completed phases 3–9; and the multi-phase implementation plan.
- Deliverables: A 6 MiB deterministic Slack-to-Runtime journey with bounded
  provider evidence; prerequisite enforcement; real RustFS/Runner/Redis E2E
  execution evidence; state-backend parity results; and
  [`runtime-file-transfer-validation-report-2026-07-25.md`](../design/runtime-file-transfer-validation-report-2026-07-25.md).
- Non-goals: New transfer contracts, gRPC message-limit changes, protocol compatibility,
  Runner storage authority, direct Runner S3 access, live credential provisioning, living-spec
  promotion, or source-file retention changes.

## Fixed Validation Contract

Core validation must run against a real Docker-backed Runtime substrate:

1. Testenv starts the current-worktree devserver with PostgreSQL, Valkey, RustFS,
   deterministic Slack fake, API Server, Worker, Runtime Control, and Docker Runtime Provider.
2. RustFS, Runner, and deterministic provider readiness are prerequisites for the core suite.
   Their absence is a failed/blocked validation result, never a skip or pass.
3. The deterministic Slack journey transfers an exact 6 MiB UTF-8 fixture. It retains only
   file sizes and SHA-256 digests in fake-provider evidence; it must not retain the file body,
   credentials, private URLs, object identities, or Runner storage authority.
4. The test proves the existing user-facing sequence:
   `download_external_file` → Runtime processing → `channel_action` publication.
   The Slack fake verifies each published file's exact length and SHA-256 digest without exposing
   the body in its evidence endpoint.
5. The transfer path retains the default gRPC message limit. No test, fixture, or product
   configuration may increase that limit to make the 6 MiB scenario pass.
6. Memory and Redis Transfer State modes execute the same required transfer semantics. Memory
   mode remains single-Control-owner only; Redis mode is required for supported handoff/multi-replica
   behavior.

## Required Execution Order

| Order | Command or action | Required result |
| --- | --- | --- |
| 1 | `cd testenv/azents && uv run testenv bootstrap local` | Current-worktree Docker/devserver substrate starts. |
| 2 | `cd testenv/azents && uv run testenv prerequisite prepare --profile live --json` | Credential snapshot is recorded without secrets; live Slack remains optional. |
| 3 | `cd testenv/azents && uv run testenv fixture doctor --all --json` | Devserver and `agent-basic` are ready. |
| 4 | `cd testenv/azents/e2e && uv run pytest -vv src/tests/test_runtime_transfer_storage.py` | RustFS bounded read, immutable copy, multipart, abort, and cleanup pass. |
| 5 | `cd testenv/azents/e2e && uv run pytest -vv src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey` | The 6 MiB Slack file completes through Runtime; provider records two exact output lengths and SHA-256 digests. |
| 6 | `cd testenv/azents/e2e && uv run pytest -vv src/tests/azents/public/test_file_resource_lifecycle.py::TestFileResourceLifecycle::test_present_file_attachment_reaches_model_as_metadata` | Runtime-to-Exchange presentation succeeds without model-visible file bodies. |
| 7 | Focused Runtime Control, Runner, state-store, provider, Helm, and protocol suites from phases 3–9 | Memory/Redis parity, authorization-before-byte, cancellation, cleanup, strict cutover, protected staging, and lifecycle defenses pass. |
| 8 | Credential-free deterministic and Runtime Provider lanes from `testenv/azents/AGENTS.md` | Product E2E passes; live-external tests remain a separately recorded optional diagnostic. |

The report records each command, exit status, prerequisite state, environment facts, failures,
fixes, and post-fix reruns. A missing local Docker or tmux installation blocks core product E2E;
it does not authorize a skipped test, spec promotion, `implemented` metadata, or rollout.

## Required Matrix and Evidence

| Requirement area | Primary evidence |
| --- | --- |
| Large Server-to-Runtime ingress | 6 MiB Slack fake input, Runtime destination success, default gRPC limits unchanged, exact published output digests. |
| Runtime-to-server publication | `present_file` and External Channel output journeys; verified object publication and no model-visible bytes. |
| Control/data isolation | Concurrent Control/transfer integration evidence with no control-channel disconnect. |
| Bounded streaming | RustFS multipart/bounded-read tests, actual-byte limits, admission/overload evidence, and no whole-file fixture evidence retention. |
| Integrity and destination safety | SHA-256/length assertions, corruption/ordering tests, protected-staging overwrite tests, and cleanup checks. |
| Cancellation and terminal failure | Cancellation, timeout, abort, typed-result, and no-replay-after-provider-mutation tests. |
| State backends | Shared state-store contract suite, memory restart failure-closed evidence, and Redis handoff/fencing evidence. |
| Runner boundary | Unauthorized-before-byte, adversarial transfer frames, and provider/Runner configuration checks proving no object-store authority. |
| Retention and lifecycle | One-hour logical expiry tests, best-effort cleanup evidence, RustFS multipart abort, and Phase 9 operator lifecycle acknowledgement. |

## Review and Promotion Handoff

Before review, compare the validated implementation with current specs and record only verified
promotion deltas for Phase 11:

- `spec/flow/agent-runtime-control.md`: dedicated transfer RPC admission, authentication,
  state backend selection, cancellation/terminal semantics, observability, strict protocol cutover,
  and the no-Runner-storage boundary.
- `spec/flow/file-exchange-storage.md`: transfer-prefix staging, S3-native immutable publication,
  consumer acknowledgement, bounded preview/read behavior, logical expiry, and cleanup ownership.
- External Channel domain/flow coverage: one verified Runtime upload per source, bounded
  provider-native stream, at-most-once provider mutation, post-provider acknowledgement, and
  no durable transferred body.

The implementation owner performs self-review, requests an independent reviewer, fixes accepted
Critical/Warning findings, reruns affected validation, and requests the same reviewer for any
required targeted recheck. Phase 11 may not mark the Requirements or Design implemented until the
required matrix passes.
