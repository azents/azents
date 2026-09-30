---
title: "Direct File Transfer Large-File Validation Report"
created: 2026-09-30
tags: [files, runtime, browser, qa, validation-report]
document_role: supporting
document_type: supporting-validation-report
---

# Direct File Transfer Large-File Validation Report

## Purpose and Scope

Preserve the bounded large-file acceptance evidence for [files-260929/REQ](../requirements/files-260929-direct-file-transfer.md) and approved `files-260929/DESIGN` revision 1. This is one feature-validation report, not a permanent heavyweight regression suite or a throughput benchmark.

The implementation previously placed two real 128 MiB journeys in required E2E. That recurring placement did not follow `.claude/conventions/global/load-tests-as-reports.md`. Their completed evidence is retained here; routine coverage is being replaced by lowered, injectable limit boundaries and small deterministic storage bodies. Fresh large-file evidence requires a new bounded execution/report rather than restoring a heavy default CI profile.

## Execution Identity and Environment

- Date: September 30, 2026, KST. JUnit start: **10:21:21.580918 KST** (`2026-09-30T01:21:21.580918+00:00`).
- Validated working tree: product sources from Phase 6 `ff2e08849`; integrated test changes were subsequently committed as Phase 7 **`85382b3aa`**, PR #1973. Do not confuse the subsequent lowered-limit follow-up with this original 128 MiB run.
- Environment: local Azents Agent Runtime, Docker testcontainers, real RustFS, PostgreSQL/Valkey, API/Worker/Runtime Control, Docker Runtime Provider and managed Runner, deterministic model/provider fixtures, Main/Admin Web, isolated HTTPS gateways and Selenium-managed Chromium.
- Fixture images were built from that worktree. Saved image-build records report full builds, no cache backend, and successful completion. Exact image digests and host CPU/memory allocation were not preserved in the safe summary; no claim about a production deployment, representative hardware, or resource-pressure threshold is made.
- Product general-file limit: **134,217,728 bytes (128 MiB)**. Independent model/image/provider policies remained enabled. RustFS CORS allowed PUT only; browser downloads used native navigation.
- Docker authentication used an isolated anonymous configuration directory, not a changed global Docker configuration.

## Workload and Checks

### Chat exact upper boundary

One synthetic `application/octet-stream` attachment of exactly **134,217,728 bytes** exercised metadata admission, a native checksum-bound single PUT, exact S3 size/checksum evidence, immutable source/product copy, and idempotent finalize. Assertions verified only one publication, exact returned metadata, and a byte-count/SHA-256 match while incrementally reading the original. Missing ingress did not publish.

The accepted attachment was admitted to a Session input and retained in the durable user message. The model-input preflight emitted the existing non-image budget warning instead of reading/encoding the original into model input. The associated model-request evidence remained bounded and free of raw file payload markers in this isolated run. The original test's use of the complete shared AIMock journal was subsequently found unsuitable for multi-journey CI; later regression checks must select the matching scenario request.

### RustFS streamed storage path

A temporary-file-backed **134,217,728-byte** synthetic source was generated in bounded chunks and exercised signed PUT, checksum-aware HEAD, immutable verified copy, signed GET, incremental byte counting/SHA-256, and owned-object cleanup. This proved the endpoint's compatible contract for the agreed boundary, not production network throughput or large multipart resource-pressure performance.

### Related browser evidence

The same integrated run separately confirmed a native Chat download of **135,168 bytes** (API 302, Web 302, storage 200, equal browser/source SHA-256, ticket lifetime below 60 seconds) and a native Workspace download of **50 bytes** with an exact synthetic Unicode filename and equal hash. These browser samples are ordinary correctness coverage, not the 128 MiB workload.

## Command and Results

Executed from `testenv/azents/e2e`:

```bash
DOCKER_CONFIG=/tmp/phase5-anonymous-docker-config \
AZENTS_E2E_ARTIFACT_DIR=/workspace/agent/.azents/sessions/garment-frost-desk/phase7-final-artifacts \
uv run pytest \
  src/tests/required/public/test_file_upload.py \
  src/tests/required/public/test_workspace_upload.py \
  src/tests/required/public/test_run_tool_to_file.py \
  src/tests/required/public/test_runtime_network_restriction.py \
  src/tests/required/test_runtime_transfer_storage.py \
  src/tests/web/public/test_chat_upload.py \
  src/tests/web/public/test_workspace_download.py \
  -q --junitxml=/workspace/agent/.azents/sessions/garment-frost-desk/phase7-final.xml
```

- Terminal exit: **0**. Integrated result: **32 passed, 22 warnings**, **203.73 seconds**. Warnings were existing deprecations and isolated-fixture self-signed HTTPS notices.
- JUnit recorded Chat upper-bound testcase time: **10.914 seconds**.
- JUnit recorded RustFS streamed 128 MiB testcase time: **0.741 seconds**.
- These are test-run durations, not transfer throughput measurements. Fixture/build and concurrent environment effects prevent extrapolation to production latency or capacity.
- Root E2E Ruff, formatting, and `ty --error-on-warning` passed before execution.
- Safe retained evidence in the Agent Session: `phase7-final.log`, `phase7-final.xml`, `phase7-final.exit`, and `phase7-final-artifacts/`. Browser summaries contain statuses, synthetic filenames, sizes, and hashes; transient signed capabilities are not publication artifacts.

## Limits and Reproduction

To repeat this acceptance check, use the recorded commit/compatible fixture sources, preserve the 128 MiB policy across API/Worker/Control/Runner, prepare the isolated storage/TLS/CORS prerequisites, and perform one bounded local execution with a fresh report. Restore lightweight test limits afterward. The current recurring suite uses lower injected limits; running it without an explicit acceptance workload does not repeat this report's 128 MiB proof.

This report does **not** prove deployed `proxy_required`/`no_network` packet-level storage egress, live Slack/Discord delivery, sustained throughput, memory-pressure tolerance, or production endpoint compatibility. The attempted read-only retained-object/custom-setting inventory failed authentication, so those counts remain unknown. All of these activation prerequisites remain explicit and are not waived by local test success.
