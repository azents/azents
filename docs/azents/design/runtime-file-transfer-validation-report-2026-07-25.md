---
title: "Runtime File Transfer Validation Report"
created: 2026-07-26
updated: 2026-07-26
tags: [runtime, files, transfer, validation, e2e, testenv, security]
document_role: supporting
document_type: supporting-validation-report
---

# Runtime File Transfer Validation Report

## Scope and Current Status

- Phase: `10/12 — E2E and validation`
- Branch/base: `feature/runtime-file-transfer-10-validation` →
  `feature/runtime-file-transfer-09-deployment-cutover`
- Baseline: `6e6b90a2e5f094cc049b03146132b4bd160f4b31`
- Inputs: [`transfer-260725/REQ`](../requirements/transfer-260725-runtime-file-transfer.md),
  [`transfer-260725/ADR`](../adr/transfer-260725-runtime-file-transfer.md), and
  [`transfer-260725/DESIGN`](transfer-260725-runtime-file-transfer.md).

This report records Phase 10 validation evidence and blockers. It is not evidence that the
implementation is complete, that a core test was skipped successfully, or that the Requirements and
Design can receive `implemented` metadata. Required Docker-backed E2E execution is currently
blocked in this runtime environment.

## Environment and Prerequisite Results

The current execution environment has no Docker CLI, Docker socket, Podman, Nerdctl,
Docker Compose, or tmux binary. The Docker-backed testcontainers substrate therefore cannot create
the required network, RustFS, Valkey, deterministic Slack fake, or Runtime Provider. The devserver
also requires tmux.

| Date (KST) | Command | Result | Evidence |
| --- | --- | --- | --- |
| 2026-07-26 | `git fetch origin main` | pass | `origin/main` refreshed. The stack and current main have diverged; Phase 10 does not merge main into only the top branch because that would contaminate its Phase 9 PR base. |
| 2026-07-26 | Review-rule comparison from stack merge-base to `origin/main` | pass | No changes under `AGENTS.md`, `.claude/`, or `docs/azents/AGENTS.md`; the current independent-review and targeted recheck rules remain applicable. |
| 2026-07-26 | `cd testenv/azents && uv run testenv fixture doctor devserver --json` | blocked | `FIXTURE_DEVSERVER_STATE_MISSING`: no fixture manifest or devserver state, no tmux session, and unhealthy public/admin readiness. |
| 2026-07-26 | `cd testenv/azents && uv run testenv bootstrap local` | blocked | The bootstrap stopped at `devserver-down` because tmux is not installed. It did not attempt to represent the missing substrate as ready. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest -vv src/tests/test_runtime_transfer_storage.py` | blocked | All three RustFS tests reached Testcontainers setup and failed with a Docker client connection error before any product test body executed. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest --collect-only -q src/tests/test_runtime_transfer_storage.py src/tests/azents/public/test_external_channels.py src/tests/azents/public/test_file_resource_lifecycle.py` | pass | 12 focused tests collected. Collection confirms the RustFS, deterministic External Channel, and `present_file` candidates are syntactically discoverable; it does not substitute for execution. |

## Grounded Validation Correction

The existing Runtime External Channel E2E selected a 10-byte Slack fixture (`b"alpha beta"`), so it
could not prove that the transfer path survives the historical gRPC message-size incident without a
limit increase. Phase 10 changes that journey to use an exact 6 MiB synthetic UTF-8 input.

The deterministic Slack fake retains the configured input only as fixture-internal source data so it
can serve the download. Its evidence endpoint returns only request metadata: each outbound upload's
received length and SHA-256 digest, never its body. The E2E asserts both processed output sizes and
digests after the existing user-facing sequence:

1. `download_external_file` selects one opaque locator.
2. Runtime downloads the provider file and executes the deterministic processing command.
3. `channel_action` publishes two result files through the provider-native upload API.
4. The fake verifies the exact output lengths and digests, while evidence excludes input/output
   bodies, credentials, private URLs, and file names.

This correction is collected locally but has not run because the required Docker-backed Runtime
substrate is unavailable.

## Static Validation and Correction Reruns

| Date (KST) | Command | Result | Evidence |
| --- | --- | --- | --- |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest -vv src/tests/test_slack_provider_fake.py src/tests/test_external_channel_file_proxy.py` | pass | 19 passed. The fake verifies sanitized outbound upload length/digest evidence and the proxy retains the three-step user-facing journey. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run ruff check . && uv run ruff format --check . && uv run pyright .` | pass | Ruff and formatter passed; Pyright reported `0 errors, 0 warnings`. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest --collect-only -q src/tests/test_runtime_transfer_storage.py src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey src/tests/azents/public/test_file_resource_lifecycle.py::TestFileResourceLifecycle::test_present_file_attachment_reaches_model_as_metadata` | pass | 5 Docker-dependent focused candidates collected. Collection is not product execution evidence. |
| 2026-07-26 | `git diff --check && python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | pass | No whitespace errors; documentation frontmatter and generated index check passed. |

Two test-code mistakes were found and corrected during static validation:

1. The new fake-provider contract assertion omitted `hashlib`; Ruff and pytest reported the
   undefined name. The import was added and the focused suite reran successfully.
2. The new E2E assertion allowed Pyright to infer `dict[Unknown, Unknown]` from serialized fake
   evidence. The collection now casts retained evidence to `dict[str, object]`; full E2E Pyright
   reran with zero errors.

These static results validate the deterministic fixture and evidence boundary only. They do not
replace real Docker-backed Runtime execution.

## Required Matrix Status

| Scenario | Candidate coverage | Current result | Completion evidence still required |
| --- | --- | --- | --- |
| 6 MiB Slack attachment to Runtime | `test_external_channel_file_transfer_journey` | blocked | Complete Runtime transfer and exact fake-provider output digest/size assertions with default gRPC limits. |
| RustFS bounded read, immutable copy, multipart upload/copy, abort, and cleanup | `test_runtime_transfer_storage.py` | blocked | 3 executed RustFS tests pass against a real container. |
| `present_file` Runtime-to-Exchange publication | `TestFileResourceLifecycle.test_present_file_attachment_reaches_model_as_metadata` | not started | Product E2E succeeds and model request contains attachment metadata rather than bytes. |
| External Channel outbound publication | `test_external_channel_file_transfer_journey` | blocked | One Runtime upload per source, two provider uploads, one completion mutation, and post-provider settlement. |
| Memory Transfer State restart behavior | Phase 3–9 Runtime Control/state suites | not rerun in Phase 10 | Active attempt fails closed; no orphan becomes a successful transfer. |
| Redis Transfer State handoff/fencing | Phase 3–9 Runtime Control/state suites | not rerun in Phase 10 | Shared state prevents duplicate stream ownership and preserves terminal settlement. |
| Control/data concurrency, authorization-before-byte, cancellation, corruption, and stale generation | Phase 4–5 protocol/Runner suites | not rerun in Phase 10 | Real gRPC evidence under default message limits. |
| Protected overwrite staging and object lifecycle defense | Phase 9 Runner/provider/Helm suites | not rerun in Phase 10 | Runtime destination safety and lifecycle/incomplete-multipart operator acknowledgement. |

No live Slack credential snapshot was inspected or used. Live Slack remains optional and cannot
replace the deterministic provider prerequisite.

## Pre-Promotion Spec Comparison

Current living specs already contain partial Runtime File Transfer coverage from earlier delivery
phases. Phase 11 must use the final passing Phase 10 evidence to consolidate and verify these exact
areas rather than marking the snapshot implemented from unexecuted local E2E:

| Living spec | Required Phase 11 promotion check |
| --- | --- |
| `spec/flow/agent-runtime-control.md` | Verify the complete dedicated transfer RPC contract: Runner and trusted-consumer authentication, opaque attempt identity, memory/Redis state ownership, admission/backpressure, cancellation and terminal settlement, observability, strict protocol/capability cutover, and no Runner object-store authority. |
| `spec/flow/file-exchange-storage.md` | Verify transfer-prefix object staging, S3-native copy/publication, consumer leases/acknowledgement, bounded preview/read paths, one-hour logical validity, best-effort physical cleanup, and retained product-resource ownership. |
| `spec/domain/external-channel.md` and `spec/flow/external-channel-delivery.md` | Verify one Runtime upload per authorized source, bounded provider-native streaming, at-most-once provider mutation, batch-held claims, post-provider acknowledgement/settlement, and the no-durable-transferred-body boundary. |

Phase 11 remains blocked until the core matrix above passes. It must not modify the accepted ADR and
must add the same implementation date to Requirements and Design only after completion evidence is
available.

## Docker-Enabled Rerun Procedure

```console
cd testenv/azents
uv run testenv bootstrap local
uv run testenv prerequisite prepare --profile live --json
uv run testenv fixture doctor --all --json

cd e2e
uv run pytest -vv src/tests/test_runtime_transfer_storage.py
uv run pytest -vv src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey
uv run pytest -vv src/tests/azents/public/test_file_resource_lifecycle.py::TestFileResourceLifecycle::test_present_file_attachment_reaches_model_as_metadata
uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src
uv run pytest -vv -m "runtime_provider and not live_external" ./src/tests/azents/public
```

After each rerun, record exact exit status, executed test count, Runtime/transfer state mode,
observed size/digest/terminal evidence, failures, fixes, and post-fix rerun results here. Do not
record credentials, bearer headers, provider private URLs, object keys, bucket names, transfer
handles, or file bodies.
