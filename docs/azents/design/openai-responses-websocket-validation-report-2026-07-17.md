---
title: "OpenAI Responses WebSocket Validation Report — 2026-07-17"
created: 2026-07-17
tags: [backend, engine, llm, openai, oauth, testing, websocket]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/openai-responses-websocket-validation-report-2026-07-17.md"
---

# OpenAI Responses WebSocket Validation Report — 2026-07-17

## Scope

This report validates implementation commit `d09ccfee` against [responses-260716/ADR](../adr/responses-260716-openai-responses-websocket-lifecycle.md) and the OpenAI Responses WebSocket transport design. Validation covers dependency resolution, formatting, linting, type safety, deterministic backend behavior, worker retry ownership and propagation, timeout cleanup, custom-endpoint HTTP compatibility, and the product E2E suite in Docker-enabled CI.

No external provider call was made. No credentials, account headers, provider payloads, response identifiers, model output, or raw WebSocket frames were captured as evidence.

## Environment

- Branch: `feature/openai-responses-websocket-validation`
- Implementation commit: `d09ccfee`
- Python: 3.14.6
- OpenAI SDK: 2.45.0
- WebSockets: 15.0.1
- Docker daemon: unavailable in the validation runtime
- External OpenAI and ChatGPT OAuth credentials: not used

## Results

| Area | Command or evidence | Result |
| --- | --- | --- |
| Dependency lock | `uv lock --check` from `python/apps/azents` | Passed |
| Installed dependency versions | `uv pip list` filtered to OpenAI and WebSockets | OpenAI 2.45.0; WebSockets 15.0.1 |
| Backend formatting and lint | `uv run ruff check --fix .` and `uv run ruff format .` | Passed; no remaining changes |
| Backend types | `uv run pyright` | Passed with 0 errors |
| Backend tests | `uv run pytest` | Passed: 1,373 passed, 391 skipped |
| Focused transport and worker regression | OpenAI adapter, watchdog, engine adapter, worker executor, and worker tests | Passed: 132 passed |
| E2E static quality | `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright .` from `testenv/azents/e2e` | Passed |
| Docker-enabled deterministic E2E | CI run `29553142775`, job `87799775860` | Passed: 164 passed, 11 skipped, 7 deselected |
| Documentation validation | `uv run python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | Passed before this report; rerun after report generation |
| Diff integrity | `git diff --check` | Passed before this report; rerun after report generation |

## Deterministic Behavior Verified

The backend suite and focused tests verify the following accepted behavior:

- Eligible official OpenAI and ChatGPT OAuth sampling can select the standard Responses WebSocket transport.
- Custom OpenAI base URLs, including `AZ_OPENAI_BASE_URL` and the SDK-supported `OPENAI_BASE_URL`, remain HTTP-only.
- Stable organization, project, account, and custom routing headers are forwarded to the WebSocket handshake without entering the logical request.
- Explicit `stop` and per-request header requests remain HTTP-only.
- One execution-owned socket is reused serially across healthy sequential responses.
- OpenAI API-key continuation remains strict and resets across socket invalidation or physical transport changes.
- ChatGPT OAuth retains complete input, `store=false`, and no `previous_response_id`.
- Connect, send, receive, protocol, and decode failures invalidate the socket, activate keyed HTTP-only state, and surface a safe transient failure code through the failed-Run boundary.
- Authentication, authorization, quota, provider-availability, User Stop, cancellation, and watchdog timeout paths do not activate sticky HTTP fallback.
- Application connect, parsed-event idle, and absolute-attempt deadlines close abandoned WebSocket work through the existing watchdog cleanup boundary.
- The operation-scoped OpenAI SDK client has automatic HTTP retries disabled, so failed-Run retries remain the only provider retry budget.
- No SDK automatic reconnect or inline WebSocket-to-HTTP replay is enabled.

## Product E2E Selection

The planned local E2E selection included:

- custom-endpoint single-turn chat;
- failed-Run retry recovery;
- client-tool call/result/follow-up persistence;
- REST User Stop;
- model-stream idle, absolute, retry-exhaustion, compaction, and Session-title timeout scenarios.

The local validation runtime had no Docker socket, so its focused 12-scenario selection stopped during Testcontainers setup before product assertions ran. The Docker-enabled CI rerun then completed the deterministic E2E job successfully with 164 passed, 11 skipped, and 7 deselected tests.

The AIMock fixture sets `AZ_OPENAI_BASE_URL` to a custom HTTP endpoint. The passing CI suite therefore verifies that the deployment-default WebSocket setting preserves custom-endpoint HTTP behavior, including the failed-Run retry recovery scenario that originally exposed SDK-owned HTTP retries consuming multiple fixture responses.

## External Validation

Live OpenAI Platform validation was not run because it is optional under [responses-260716/ADR](../adr/responses-260716-openai-responses-websocket-lifecycle.md) and no provider credential was supplied for this validation phase. The previously retained ChatGPT OAuth probe evidence remains external to the repository and was not rerun or disclosed.

## Privacy Review

The implementation and tests log only bounded operational fields such as provider, model, selected transport, connection reuse, safe failure stage, bounded handshake status, fallback activation, and timeout classification. Tests additionally assert that provider exception details do not enter captured logs. Provider content and identifiers remain outside logs and repository evidence.

## Conclusion

All deterministic backend, dependency, formatting, linting, type, static E2E, and Docker-enabled product E2E checks passed. The implementation matches the accepted ownership, fallback, retry, timeout, continuation, provider rollout, and privacy policy.
