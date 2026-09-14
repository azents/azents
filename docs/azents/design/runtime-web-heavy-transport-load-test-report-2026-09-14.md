---
title: "Runtime Web Heavy Transport Load-Test Report"
created: 2026-09-14
tags: [runtime, gateway, performance, testing]
document_role: supporting
document_type: supporting-validation-report
---

# Runtime Web Heavy Transport Load-Test Report

## Purpose

Validate the Phase 3 replacement Runtime Web data path under a bounded heavy workload before removing the temporary load harness from the recurring E2E suite.

This is a one-time validation artifact. The heavy workload is not part of pytest collection or CI after this report is recorded.

## Validation Snapshot

- Date: 2026-09-14
- Branch: `feat/runtime-web-heavy-transport-3-clean-cutover`
- Base commit: `0626db889c9d1bebf927cbb246e9871fe0bef3e8`
- Server image: `sha256:a49166592dcca77c7accc3fa8975d3fbf14490a41f01484d1d06b49a5d526feb`
- Runtime Runner image: `sha256:6e9875c02a22ec6c00b70cec19da3c5283b68d6ea575d78b75aabf98873cd2f9`
- Capacity backend: in-memory
- Topology: TLS edge, Runtime Web Gateway, accepting Runtime Control, one-hop Owner Runtime Control relay, Docker Runtime Provider, Runtime Runner, and loopback aiohttp application
- Execution environment: one local Linux Docker host

The server image included the uncommitted Phase 3 integrated diff at the time of execution. The resulting fixes are included in that integrated diff; the temporary heavy workload code was removed before final review and PR creation.

## Workload

The one-time run exercised real application bytes through the replacement transport:

- browser upload: 64 MiB with a deterministic SHA-256 check;
- browser download: 64 MiB with exact byte-count verification;
- browser fan-out: 64 asset requests of 32 KiB each;
- browser-neutral chunked upload: 64 MiB with a deterministic SHA-256 check;
- browser-neutral download: 64 MiB with exact byte-count and digest verification;
- concurrent application barrier: 64 simultaneous held requests;
- slow producer upload: 32 MiB;
- slow application consumer upload: 32 MiB;
- slow browser receiver download: 32 MiB;
- HTTP, SSE, redirect, application error, WebSocket text, binary, Ping, Pong, and close behavior;
- Gateway and Control buffer, queue, credit, stream, resident-memory, and Runner-memory observations; and
- authentication, exact authority, generation fencing, and one-hop relay routing.

The checked load profile used 128 active streams, 128 pending opens, a 64 MiB Runtime buffer grant ceiling, 1 GiB/s inbound and outbound rates, and a 128 MiB burst allowance.

## Command

```console
cd testenv/azents/e2e
AZENTS_E2E_SERVER_IMAGE=azents-e2e:runtime-web-root-phase3 \
AZENTS_E2E_RUNTIME_RUNNER_IMAGE=azents-runtime-runner-e2e:runtime-web-root-phase3 \
AZENTS_E2E_RUNTIME_WEB_CAPACITY_BACKEND=memory \
uv run pytest \
  'src/tests/web/public/test_runtime_web_gateway.py::test_runtime_web_gateway_real_runtime_browser_and_cross_replica_relay[shared_cookie]' \
  -q -s --tb=short
```

The temporary harness selected the heavy workload values listed above for the `shared_cookie` parameter. To reproduce the load result, apply those values to a disposable local copy of the lightweight Runtime Web E2E journey, run the command, and discard the workload-only changes after recording the new report.

## Result

Final result: **passed**.

```text
1 passed, 3 warnings in 90.22s (0:01:30)
```

All byte counts, digests, concurrency barriers, WebSocket controls, routing assertions, and bounded pressure assertions completed successfully.

## Defects Found and Corrected

The validation exposed and drove fixes for:

1. concurrent Gateway sources assigning Runner stream IDs before enqueue ordering was secured;
2. late terminal response frames racing a local browser cancellation and terminating a persistent Gateway session;
3. masked WebSocket Ping/Pong payloads arriving as mutable buffer views rather than `bytes`;
4. late Runner responses targeting a closed Gateway source queue and terminating the Owner Runner session;
5. late relay responses targeting a closed Gateway source queue and terminating the shared relay session;
6. late post-terminal relay control frames resolving an already retired stream mapping and stalling a Gateway source session; and
7. a checked workload profile whose burst allowance was smaller than the intended successful transfer.

Focused unit tests cover each persistent transport race or payload normalization fix.

## Limits

- This was a bounded 64 MiB/32 MiB local load validation, not the 1 GiB production-scale benchmark from the Requirements scenario.
- The run used one Docker host and does not measure multi-node network variance, external load-balancer behavior, or production storage contention.
- The run validates correctness and bounded resource behavior; it is not a throughput or latency service-level benchmark.
- The in-memory capacity backend was used. Redis fallback and recovery remain covered by the lightweight functional E2E path.

## Reproduction Policy

Run a new load test only when a later feature, release, or incident requires fresh heavy-load evidence. Record a new dated report with the new commit or image identities, environment, workload, command, result, and observed limits. Keep recurring CI focused on deterministic lightweight protocol and behavior checks.
